import json, time, urllib.request, urllib.error, socket, email.utils
from urllib.parse import urlparse
from .decision import decide
from .adapters import Unsupported
def http_post(base, path, headers, body, timeout=8):
    req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    try:
        r = urllib.request.urlopen(req, timeout=timeout); raw = r.read()
        try: b = json.loads(raw or b"{}")
        except Exception: b = {}
        return r.status, dict(r.headers), b
    except urllib.error.HTTPError as e:
        try: b = json.loads(e.read() or b"{}")
        except Exception: b = {}
        return e.code, dict(e.headers), b
    except (socket.timeout, urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return 0, {}, {"error": type(e).__name__}
def retry_after(h):
    v = (h or {}).get("Retry-After")
    if not v: return None
    try: return max(0.0, float(v))
    except ValueError:
        try: return max(0.0, email.utils.parsedate_to_datetime(v).timestamp() - time.time())
        except Exception: return None
def sent_id(body):
    if not isinstance(body, dict): return ""
    sm = body.get("sentMessages")
    return str(body.get("id") or body.get("message_id") or (sm[0].get("id") if isinstance(sm, list) and sm and isinstance(sm[0], dict) else "") or "")

OPEN = ("received", "held_autoreply_off", "decided")   # states process() may start from
MAX_REPLY = 500
class Pipeline:
    """Retry policy (conservative, because retry rules are not verified per endpoint):
       2xx sent | 401/403 failed_auth (no retry) | other 4xx failed | 429 failed_rate_limited (human/UI retry after Retry-After)
       5xx/timeout/network failed_unconfirmed (reply may have been delivered; never auto-retried, never fallback to push)."""
    def __init__(s, store, adapters, send_bases, llm=None, clock=time.time):
        s.st, s.ad, s.bases, s.llm = store, adapters, send_bases, llm
    def ingest(s, platform, headers, body):
        a = s.ad.get(platform)
        if not a: return 404, "unknown platform"
        try: ok = a.verify({k.lower(): v for k, v in headers.items()}, body)
        except Exception: ok = False
        if not ok:
            s.st.log(0, "rejected_signature", platform); return 401, "bad signature"
        try: evs = a.parse(json.loads(body))
        except Exception as e: return 400, f"bad payload {type(e).__name__}"
        ids = []
        for e in evs:
            if not e.get("event_id"): s.st.log(0, "dropped_no_event_id", platform); continue
            now = time.time()
            status = "ignored_unsupported" if e["kind"] == "unsupported" else "received"
            cur = s.st.q("insert or ignore into events(platform,event_id,account,sender,kind,reply_ref,text,status,error,created,updated) values(?,?,?,?,?,?,?,?,?,?,?)",
                         (platform, e["event_id"], e["account"], e["sender"], e["kind"], e["reply_ref"], (e["text"] or "")[:2000], status, e.get("reason") or None, now, now))
            if cur.rowcount == 0: continue
            pk = cur.lastrowid; s.st.log(pk, "received", {"kind": e["kind"]})
            if status == "received": ids.append(pk)
        return 200, ids
    def _claim(s, pk, froms):
        q = ",".join("?" * len(froms))
        return s.st.q(f"update events set status='processing',updated=? where id=? and status in ({q})", (time.time(), pk, *froms)).rowcount == 1
    def process(s, pk):
        try: s._process(pk)
        except Exception as e:
            s.st.q("update events set status='error',error=?,updated=? where id=?", (f"{type(e).__name__}: {e}", time.time(), pk)); s.st.log(pk, "error", repr(e))
    def _process(s, pk):
        if not s.st.get_setting("autoreply_enabled", True):
            s.st.q("update events set status='held_autoreply_off',updated=? where id=? and status in ('received','held_autoreply_off')", (time.time(), pk)); s.st.log(pk, "held", "autoreply off"); return
        if not s._claim(pk, OPEN): return   # already sent/processing/handled: no double work
        ev = s.st.rows("select * from events where id=?", (pk,))[0]
        ver, rules = s.st.latest_rules()
        if ev["reply"] and ev["decision"] == "reply": d = dict(action="reply", by=ev["decided_by"], reply=ev["reply"], reason="resume"); ver = ev["rule_version"] or ver   # keep original decision's rule version
        else: d = decide(ev["text"], rules, s.llm)
        s.st.log(pk, "decided", {k: d[k] for k in ("action", "by", "reason")})
        if d["action"] != "reply":
            st = "handoff" if d["action"] == "handoff" else "ignored"
            s.st.q("update events set status=?,decided_by=?,decision=?,rule_version=?,updated=? where id=?", (st, d["by"], d["action"], ver, time.time(), pk)); return
        if len(d["reply"]) > MAX_REPLY:   # never truncate approved text: send to a human instead
            s.st.q("update events set status='handoff',decided_by=?,decision='handoff',rule_version=?,error='approved answer longer than limit',updated=? where id=?", (d["by"], ver, time.time(), pk)); return
        s.st.q("update events set decided_by=?,decision='reply',reply=?,rule_version=?,updated=? where id=?", (d["by"], d["reply"], ver, time.time(), pk))
        s._send(pk)
    def retry(s, pk):
        """Manual retry (UI). failed_unconfirmed needs force=True via retry_force: the reply may already be visible."""
        if s.st.rows("select status from events where id=?", (pk,))[0]["status"] not in ("failed", "failed_rate_limited", "failed_auth", "failed_config", "error"): return False
        s.st.q("update events set status='decided' where id=?", (pk,)); s.process(pk); return True
    def retry_force(s, pk):
        s.st.q("update events set status='decided' where id=? and status='failed_unconfirmed'", (pk,)); s.process(pk)
    def recover(s):
        """Startup / re-enable: resume anything stuck. Held events are released only when autoreply is on."""
        n = 0
        stale = time.time() - 60
        s.st.q("update events set status='decided' where status='processing' and updated<?", (stale,))
        states = ["received", "decided"] + (["held_autoreply_off"] if s.st.get_setting("autoreply_enabled", True) else [])
        for r in s.st.rows(f"select id from events where status in ({','.join('?'*len(states))}) order by id", tuple(states)):
            s.process(r["id"]); n += 1
        return n
    def _send(s, pk):
        ev = s.st.rows("select * from events where id=?", (pk,))[0]
        base0 = s.bases.get(ev["platform"]) or ""
        ev["_loopback"] = (urlparse(base0).hostname or "") in ("127.0.0.1", "localhost", "::1")
        try: path, hdr, body = s.ad[ev["platform"]].build_send(ev)
        except Unsupported as e:
            s.st.q("update events set status='failed_config',error=?,updated=? where id=?", (str(e)[:200], time.time(), pk)); return
        base = s.bases.get(ev["platform"])
        if not base:
            s.st.q("update events set status='failed_config',error='no send base url configured',updated=? where id=?", (time.time(), pk)); return
        host = urlparse(base).hostname or ""
        s.st.q("update events set send_host=? where id=?", (host, pk))
        code, rh, rb = http_post(base, path, hdr, body)
        s.st.q("update events set attempts=attempts+1 where id=?", (pk,)); s.st.log(pk, "send_attempt", {"code": code})
        if 200 <= code < 300:
            s.st.q("update events set status='sent',sent_message_id=?,error=null,updated=? where id=?", (sent_id(rb), time.time(), pk)); return
        prior_unsure = bool(ev.get("error")) and "delivery unknown" in ev["error"]
        if prior_unsure and 400 <= code < 500 and code != 429: st, err = "failed_unconfirmed", f"http {code} after an unconfirmed attempt: first send may have been delivered"
        elif code in (401, 403): st, err = "failed_auth", f"http {code}"
        elif code == 429:
            ra = retry_after(rh); st, err = "failed_rate_limited", "http 429" + (f", retry after {int(ra)}s" if ra is not None else "")
        elif code == 0 or code >= 500: st, err = "failed_unconfirmed", f"{'timeout/network' if code == 0 else 'http ' + str(code)}; delivery unknown, not auto-retried"
        else: st, err = "failed", f"http {code}"
        s.st.q("update events set status=?,error=?,updated=? where id=?", (st, err, time.time(), pk))
