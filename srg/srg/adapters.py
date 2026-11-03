"""Channel adapters: verify signature, normalize inbound, build outbound send request.
Status of each adapter vs the REAL platform is tracked in PLATFORM_STATUS and is NOT proven by tests here."""
import hmac, hashlib, base64, json
def _hmac(secret, body, digest=hashlib.sha256): return hmac.new(secret.encode(), body, digest).digest()
def _safe_eq(got, exp):
    try: return hmac.compare_digest(str(got).encode("utf-8"), str(exp).encode("utf-8"))
    except Exception: return False

class Unsupported(Exception): pass

class Adapter:
    name = ""
    def __init__(s, cfg): s.cfg = cfg
    def verify(s, headers, body): raise NotImplementedError
    def parse(s, payload): raise NotImplementedError   # -> list of normalized dicts
    def build_send(s, ev): raise NotImplementedError    # -> (path, headers, json_body)

class Meta(Adapter):  # covers facebook + instagram (same Graph webhook signature scheme)
    def __init__(s, cfg, name="facebook"): super().__init__(cfg); s.name = name
    def verify(s, h, body):
        sec = s.cfg.get("app_secret")
        if not sec: return False  # unconfigured secret never verifies (empty-secret forgery)
        return _safe_eq(h.get("x-hub-signature-256", ""), "sha256=" + _hmac(sec, body).hex())
    def parse(s, p):
        """Only NEW comments by other users and inbound non-echo text DMs become events. Own-page activity, likes, edits, posts are dropped."""
        out = []
        for entry in p.get("entry", []):
            acct = str(entry.get("id", ""))
            for ch in entry.get("changes", []):
                v = ch.get("value", {}) or {}; field = ch.get("field")
                frm = str((v.get("from") or {}).get("id", ""))
                is_fb_comment = field == "feed" and v.get("item") == "comment" and v.get("verb") == "add"
                is_ig_comment = field == "comments"
                cid = v.get("comment_id") or v.get("id")
                text = v.get("message") or v.get("text")
                if (is_fb_comment or is_ig_comment) and cid and text:
                    if not frm:
                        out.append(dict(event_id=str(cid), account=acct, sender="", kind="unsupported", text="", reply_ref=str(cid), reason="comment without from.id: cannot exclude own-account comments"))
                    elif frm != acct:
                        out.append(dict(event_id=str(cid), account=acct, sender=frm, kind="comment", text=text[:2000], reply_ref=str(cid)))
            for m in entry.get("messaging", []):
                msg = m.get("message") or {}
                sender = str((m.get("sender") or {}).get("id", ""))
                if not msg.get("mid") or msg.get("is_echo") or msg.get("is_self") or not sender or sender == acct: continue
                if msg.get("text"):
                    out.append(dict(event_id=str(msg["mid"]), account=acct, sender=sender, kind="dm", text=msg["text"][:2000], reply_ref=sender))
                else:
                    out.append(dict(event_id=str(msg["mid"]), account=acct, sender=sender, kind="unsupported", text="", reply_ref=sender, reason="non-text message"))
        return out
    def build_send(s, ev):
        if s.name == "instagram":
            # Per technical review (official docs read 2026-11-03): comment reply POST /<IG_COMMENT_ID>/replies {message}; DM POST /<IG_ID>/messages
            # with recipient.id + message.text; token as Authorization: Bearer header, never in body. Host/version (graph.instagram.com/v26.0) goes in the send base.
            # Comment-reply auth style is NOT separately verified (assumed same Bearer).
            h = {"Authorization": "Bearer " + s.cfg.get("access_token", "")}
            if ev["kind"] == "comment": return (f"/{ev['reply_ref']}/replies", h, {"message": ev["reply"]})
            return (f"/{ev['account']}/messages", h, {"recipient": {"id": ev["reply_ref"]}, "message": {"text": ev["reply"]}})
        # Facebook Page: official docs NOT read (fetch failed) -> endpoint below is UNVERIFIED recall. Kept only so the pipeline shape is exercised.
        # Official docs only prove POST /{page_post_id}/comments (new comment on a post), NOT a reply into the original comment thread.
        # So sending is OFF unless explicitly enabled (mock-only exercise); never silently turned into a new post-level comment.
        if ev["kind"] == "comment" and s.cfg.get("enable_unverified_comment_reply") and ev.get("_loopback"):  # test flag only honoured for loopback (mock) targets
            return (f"/{ev['reply_ref']}/comments", {}, {"message": ev["reply"], "access_token": s.cfg.get("access_token", "")})
        raise Unsupported("FB comment-thread reply / Messenger send not verified: disabled (handoff to human)")

class Line(Adapter):
    name = "line"
    def verify(s, h, body):
        sec = s.cfg.get("channel_secret")
        if not sec: return False
        return _safe_eq(h.get("x-line-signature", ""), base64.b64encode(_hmac(sec, body)).decode())
    def parse(s, p):
        out = []
        for e in p.get("events", []):
            m = e.get("message") or {}
            if e.get("type") == "message" and m.get("id"):
                ok = m.get("type") == "text" and m.get("text")
                stype = (e.get("source") or {}).get("type", "user")
                group = stype in ("group", "room") and not s.cfg.get("reply_in_groups")
                kind = "dm" if ok and not group else "unsupported"
                reason = "group/room message: not auto-answered (reply_in_groups is off)" if group else ("" if ok else "non-text message")
                out.append(dict(event_id=str(e.get("webhookEventId") or m["id"]), account=p.get("destination",""), sender=(e.get("source") or {}).get("userId") or "",
                                kind=kind, text=m.get("text","")[:2000] if kind == "dm" else "", reply_ref=e.get("replyToken",""), reason=reason))
        return out
    def build_send(s, ev):
        if not ev.get("reply_ref"): raise Unsupported("no replyToken (standby/unsupported event): reply API cannot be called; push is not used (quota)")
        return ("/v2/bot/message/reply", {"Authorization": "Bearer " + s.cfg.get("access_token","")},
                {"replyToken": ev["reply_ref"], "messages": [{"type": "text", "text": ev["reply"]}]})

class TikTok(Adapter):
    """PLACEHOLDER. Signature scheme and reply endpoint follow the technical review (Tiktok-Signature: t=<unix>,s=<hex>, HMAC(t + '.' + rawbody),
    reject stale; POST .../business/comment/reply/create/ with Access-Token). The inbound payload shape is ASSUMED (comment.update is a notification
    that likely requires a list call; not implemented). Never counted as verified."""
    name = "tiktok"
    TOLERANCE = 300
    def verify(s, h, body, now=None):
        import time
        sec = s.cfg.get("secret")
        if not sec: return False
        try:
            parts = dict(x.split("=", 1) for x in h.get("tiktok-signature", "").split(","))
            t = int(parts["t"]); sig = parts["s"]
        except Exception: return False
        if abs((now or time.time()) - t) > s.cfg.get("tolerance", s.TOLERANCE): return False
        return _safe_eq(sig, _hmac(sec, str(t).encode() + b"." + body).hex())
    def parse(s, p):
        if not (p.get("comment_id") and p.get("text") and p.get("video_id") and p.get("business_id")): return []
        if str(p.get("user_id", "")) == str(p["business_id"]): return []
        ref = json.dumps({"business_id": p["business_id"], "video_id": p["video_id"], "comment_id": p["comment_id"]})
        return [dict(event_id=str(p["comment_id"]), account=str(p["business_id"]), sender=str(p.get("user_id", "")), kind="comment", text=p["text"], reply_ref=ref)]
    def build_send(s, ev):
        r = json.loads(ev["reply_ref"])
        return ("/open_api/v1.3/business/comment/reply/create/", {"Access-Token": s.cfg.get("access_token", "")}, {**r, "text": ev["reply"]})

def make_adapters(cfg):
    return {"facebook": Meta(cfg.get("facebook", {}), "facebook"), "instagram": Meta(cfg.get("instagram", {}), "instagram"),
            "line": Line(cfg.get("line", {})), "tiktok": TikTok(cfg.get("tiktok", {}))}

# Capability table. default_enabled is derived from code policy; test results come from verification.json (written only by tests/run_all.py).
CAPS = {
 "facebook": [("comment_receive", True, "official docs partly read; comment event keys partly unverified"),
              ("comment_thread_reply", False, "DISABLED: docs prove only post-level comment; test flag works only against loopback mock"),
              ("dm", False, "DISABLED: not verified")],
 "instagram": [("comment_receive", True, "official docs; Advanced vs Standard Access unresolved"),
               ("comment_reply", True, "official docs (/<comment>/replies); comment-reply auth style assumed Bearer"),
               ("dm_receive_reply", True, "official docs; 24h window not enforced in code"),
               ("private_reply", False, "not implemented")],
 "line": [("dm_receive_reply", True, "official docs; reply success body shape unverified"),
          ("group_reply", False, "OFF by default (reply_in_groups)"),
          ("push_fallback", False, "never used (quota)")],
 "tiktok": [("comment_reply", False, "PLACEHOLDER: inbound payload shape assumed; real flow is notification then list call; needs reviewed app")],
}
import json as _json, os as _os
PLATFORMS = tuple(CAPS)
def platform_status(path=None):
    path = path or _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "verification.json")
    try: data = _json.load(open(path))
    except Exception: data = {}
    out = {"_note": "A = real platform account: none tested. B/C = local MOCK endpoints with self-made test keys.", "_generated_by": data.get("_ts", "no test run recorded"), "platforms": {}}
    for p, caps in CAPS.items():
        out["platforms"][p] = [{"capability": c, "default_enabled": en, "note": note, "A_real_platform": "untested",
                                "B_C_mock_tests": data.get(p, {}).get(c, "untested")} for c, en, note in caps]
    return out
