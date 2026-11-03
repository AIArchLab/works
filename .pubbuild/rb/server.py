"""ReplyBridge HTTP stdlib only


    cd replybridge && RB_SECRETS_JSON='{...}' python3 -m rb.server --port 8080

    RB_CONFIG    config/tenants.json
    RB_KB       KB  config/kb.json
    RB_DB       sqlite  out/replybridge.db
    RB_SECRETS_JSON  
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import core
from . import ledger as ledger_mod
from . import transport as transport_mod

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default if default is not None else {}


def build_bridge(config_path=None, kb_path=None, db_path=None, secrets=None, transport=None):
    config_path = config_path or os.environ.get("RB_CONFIG", os.path.join(_ROOT, "config/tenants.json"))
    kb_path = kb_path or os.environ.get("RB_KB", os.path.join(_ROOT, "config/kb.json"))
    db_path = db_path or os.environ.get("RB_DB", os.path.join(_ROOT, "out/replybridge.db"))
    cfg = load_json(config_path)
    kb = load_json(kb_path, []).get("entries", []) if isinstance(load_json(kb_path, []), dict) else load_json(kb_path, [])
    if secrets is None:
        secrets = json.loads(os.environ.get("RB_SECRETS_JSON", "{}"))
    store = ledger_mod.Store(db_path)
    return core.Bridge(cfg.get("tenants", []), secrets, store,
                       transport or transport_mod.HttpTransport(), kb=kb)



CONSOLE_HTML = """<!doctype html><html lang="en"><meta charset="utf-8">
<title>ReplyBridge console</title>
<style>
:root{--bg:#0b0e14;--card:#12161f;--line:#1f2532;--tx:#e6e9ef;--mut:#8b95a5;--acc:#4f8cff;--ok:#34d399;--bad:#f87171}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.55 system-ui,-apple-system,sans-serif}
header{display:flex;align-items:center;gap:14px;padding:16px 24px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#10141d,#0b0e14)}
.brand{font-weight:700;font-size:16px}
.sub{color:var(--mut);font-size:12px;margin-top:2px}
.pill{margin-left:auto;display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:999px;padding:5px 12px;font-size:12px;color:var(--mut);white-space:nowrap}
.dot{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 8px var(--ok)}
.dot.bad{background:var(--bad);box-shadow:0 0 8px var(--bad)}
main{padding:20px 24px 40px;max-width:1280px;margin:0 auto;display:grid;gap:16px}
.tiles{display:grid;grid-template-columns:repeat(5,1fr);gap:14px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.tile .lab{color:var(--mut);font-size:11px;letter-spacing:.08em;text-transform:uppercase}
.tile .num{font-size:26px;font-weight:650;margin-top:6px;font-variant-numeric:tabular-nums}
.tile .hint{color:var(--mut);font-size:11px;margin-top:3px}
.grid{display:grid;grid-template-columns:1.55fr 1fr;gap:16px;align-items:start}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.card h2{margin:0;padding:12px 16px;font-size:12px;letter-spacing:.09em;text-transform:uppercase;color:var(--mut);border-bottom:1px solid var(--line);display:flex;justify-content:space-between;font-weight:600}
.feed{max-height:560px;overflow:auto}
.row{display:grid;grid-template-columns:68px 1fr;gap:10px;padding:10px 16px;border-bottom:1px solid #171c26}
.row:last-child{border-bottom:0}
.time{color:var(--mut);font-size:11px;font-variant-numeric:tabular-nums;padding-top:3px}
.msg{font-size:13px;color:#cbd3e1;margin-bottom:5px;word-break:break-word}
.meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.tag{font-size:11px;border:1px solid var(--line);border-radius:999px;padding:2px 8px;color:var(--mut)}
.tag.reply{color:#8ef0c4;border-color:#1d4d3b;background:#0e2b21}
.tag.escalate{color:#ffd58a;border-color:#5a4416;background:#2b2310}
.tag.ignore{color:#c2c8d4;border-color:#2a3040;background:#1a1e28}
.tag.other{color:#9dc0ff;border-color:#1e3556;background:#111a2b}
.q{padding:11px 16px;border-bottom:1px solid #171c26;display:grid;gap:7px}
.q:last-child{border-bottom:0}
.q .t{font-size:13px;color:#cbd3e1}
.q .r{color:var(--mut);font-size:11px}
input{width:100%;background:#0b0e14;border:1px solid #2a3140;color:var(--tx);border-radius:7px;padding:7px 9px;font:12px system-ui}
button{background:var(--acc);color:#fff;border:0;border-radius:7px;padding:6px 12px;font:12px system-ui;cursor:pointer;white-space:nowrap}
button:hover{filter:brightness(1.12)}
.legend{display:grid;gap:10px;padding:12px 16px}
.legend .l{display:flex;justify-content:space-between;font-size:12px;color:#c2c8d4}
.legend .l span:last-child{color:var(--mut);font-variant-numeric:tabular-nums}
.bar{height:6px;border-radius:4px;background:#1a1f2b;overflow:hidden;margin-top:5px}
.bar i{display:block;height:100%;background:var(--acc)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:var(--mut)}
.empty{color:var(--mut);padding:16px;font-size:13px}
html.light{--bg:#f6f7f9;--card:#ffffff;--line:#e2e6ee;--tx:#0f172a;--mut:#5b6675;--acc:#2563eb}
html.light .tag{color:#5b6675;border-color:#e2e6ee;background:#f2f4f8}
html.light .tag.reply{color:#067a52;border-color:#bfe6d5;background:#e9f9f1}
html.light .tag.escalate{color:#8a5b00;border-color:#f0dcae;background:#fdf5e3}
html.light .tag.ignore{color:#4b5563;border-color:#e2e6ee;background:#f2f4f8}
html.light .tag.other{color:#1d4ed8;border-color:#c7d7fb;background:#eff4ff}
html.light .row,html.light .q{border-bottom-color:#eef1f6}
html.light .msg,html.light .q .t{color:#1f2937}
html.light header{background:linear-gradient(180deg,#ffffff,#f6f7f9)}
html.light .bar{background:#e8ecf3}
html.light input{background:#fff;border-color:#d7dde8;color:#0f172a}
@media (max-width:960px){
  main{padding:16px}
  .tiles{grid-template-columns:repeat(2,1fr)}
  .grid{grid-template-columns:1fr}
  .msg{font-size:14px}
  .tag{font-size:12px}
}
</style>
<header>
  <div><div class="brand">ReplyBridge</div><div class="sub">Channel-agnostic inbound reply router - policy decisions &amp; audit trail</div></div>
  <div class="pill"><span class="dot" id="chainDot"></span><span id="chainTxt">checking ledger</span></div>
  <div class="pill" id="clock">--:--:--</div>
</header>
<main>
  <div class="tiles">
    <div class="tile"><div class="lab">Decisions</div><div class="num" id="tTotal">-</div><div class="hint">inbound events handled</div></div>
    <div class="tile"><div class="lab">Auto-replied</div><div class="num" id="tReply">-</div><div class="hint">rule or KB draft</div></div>
    <div class="tile"><div class="lab">Escalated</div><div class="num" id="tEsc">-</div><div class="hint">never guessed, queued</div></div>
    <div class="tile"><div class="lab">Decision latency p50 / p95</div><div class="num" id="tLat">-</div><div class="hint">milliseconds</div></div>
    <div class="tile"><div class="lab">Ledger integrity</div><div class="num" id="tChain">-</div><div class="hint">hash chain recomputed</div></div>
  </div>
  <div class="grid">
    <div class="card">
      <h2><span>Decision log (newest first)</span><span class="mono" id="feedCount"></span></h2>
      <div class="feed" id="feed"><div class="empty">loading...</div></div>
    </div>
    <div style="display:grid;gap:16px">
      <div class="card">
        <h2><span>Human queue</span><span class="mono" id="qCount"></span></h2>
        <div id="queue"><div class="empty">loading...</div></div>
      </div>
      <div class="card"><h2>Escalation reasons</h2><div class="legend" id="reasons"><div class="empty">-</div></div></div>
    </div>
  </div>
</main>
<script>
if (new URLSearchParams(location.search).get("theme") === "light") document.documentElement.classList.add("light");
const esc = s => (s ?? "").toString().replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c]));
const hhmmss = ts => new Date((ts || 0) * 1000).toLocaleTimeString("en-GB", {hour12:false});
const j = async (u, o) => (await fetch(u, o)).json();
const tile = (id, v) => { document.getElementById(id).textContent = (v === undefined || v === null) ? "-" : v; };

async function refresh() {
  let S = {}, D = [], Q = [];
  try { S = await j("/stats"); } catch (e) {}
  try { D = (await j("/decisions?limit=40")).decisions || []; } catch (e) {}
  try { Q = (await j("/queue")).items || []; } catch (e) {}

  const acts = S.by_action || {};
  tile("tTotal", S.total ?? Object.values(acts).reduce((a, b) => a + (b || 0), 0));
  tile("tReply", acts.reply ?? 0);
  tile("tEsc", acts.escalate ?? 0);
  const lat = S.latency || {};
  const p50 = lat.p50_ms ?? lat.p50 ?? null, p95 = lat.p95_ms ?? lat.p95 ?? null;
  const fmt = v => (v == null ? null : (v < 10 ? Number(v).toFixed(1) : String(Math.round(v))));
  tile("tLat", (p50 != null && p95 != null) ? (fmt(p50) + " / " + fmt(p95)) : "-");
  const ok = S.chain_ok;
  tile("tChain", ok === true ? "OK" : (ok === false ? "FAILED" : "-"));
  document.getElementById("chainDot").className = "dot" + (ok === false ? " bad" : "");
  document.getElementById("chainTxt").textContent = ok === true ? "ledger chain intact" : (ok === false ? "chain broken" : "chain unknown");

  const feed = document.getElementById("feed");
  document.getElementById("feedCount").textContent = D.length ? (D.length + " entries") : "";
  feed.innerHTML = D.length ? D.map(r => {
    const p = r.payload || {};
    const a = p.action || r.kind || "-";
    const cls = a === "reply" ? "reply" : (a === "escalate" ? "escalate" : (a === "ignore" ? "ignore" : "other"));
    const text = p.text || p.message || p.reply_text || p.reason || "";
    const bits = [];
    if (p.platform) bits.push('<span class="tag">' + esc(p.platform) + '</span>');
    bits.push('<span class="tag ' + cls + '">' + esc(a) + '</span>');
    if (p.confidence != null) bits.push('<span class="tag">conf ' + Number(p.confidence).toFixed(2) + '</span>');
    if (p.latency_ms != null) bits.push('<span class="tag">' + Math.round(p.latency_ms) + ' ms</span>');
    if (p.escalate_reason) bits.push('<span class="tag">' + esc(p.escalate_reason) + '</span>');
    if (p.send_status != null) bits.push('<span class="tag">send ' + esc(p.send_status) + '</span>');
    return '<div class="row"><div class="time">' + hhmmss(r.ts) + '</div><div><div class="msg">' +
           (esc(text).slice(0, 160) || '<span class="mono">seq ' + r.seq + ' &middot; ' + esc(r.kind) + '</span>') +
           '</div><div class="meta">' + bits.join("") + '</div></div></div>';
  }).join("") : '<div class="empty">No decisions recorded yet</div>';

  const q = document.getElementById("queue");
  document.getElementById("qCount").textContent = Q.length ? (Q.length + " open") : "";
  q.innerHTML = Q.length ? Q.slice(0, 6).map(it => {
    const ev = it.event || {}, d = it.decision || {};
    return '<div class="q"><div class="t">' + esc(ev.text || "(empty)") + '</div>' +
           '<div class="r">#' + it.id + ' &middot; ' + esc(ev.platform || "-") + ' &middot; ' + esc(ev.author_name || ev.author_id || "visitor") +
           ' &middot; reason ' + esc(d.escalate_reason || d.reason || "-") + '</div>' +
           '<div style="display:flex;gap:6px"><input id="rp' + it.id + '" placeholder="reply text...">' +
           '<button onclick="resolve(' + it.id + ')">Approve &amp; send</button></div></div>';
  }).join("") : '<div class="empty">Nothing waiting for a human</div>';

  const reasons = document.getElementById("reasons");
  let rs = S.by_escalate_reason || S.escalate_reasons || {};
  if (!Object.keys(rs).length) { rs = {}; D.forEach(r => { const e = (r.payload || {}).escalate_reason; if (e) rs[e] = (rs[e] || 0) + 1; }); }
  const keys = Object.keys(rs);
  if (!keys.length) { reasons.innerHTML = '<div class="empty">no escalations yet</div>'; }
  else {
    const max = Math.max(...keys.map(k => rs[k] || 0));
    reasons.innerHTML = keys.sort((a,b) => rs[b] - rs[a]).map(k =>
      '<div><div class="l"><span>' + esc(k) + '</span><span>' + rs[k] + '</span></div>' +
      '<div class="bar"><i style="width:' + Math.round(100 * (rs[k] || 0) / max) + '%"></i></div></div>').join("");
  }
}
async function resolve(id) {
  const el = document.getElementById("rp" + id);
  await j("/queue/" + id + "/resolve", { method: "POST", headers: {"Content-Type": "application/json"},
                     body: JSON.stringify({ reply_text: el && el.value ? el.value : "", by: "console" }) });
  refresh();
}
setInterval(() => { document.getElementById("clock").textContent = new Date().toLocaleTimeString("en-GB", {hour12:false}); }, 1000);
refresh(); setInterval(refresh, 5000);
</script></html>"""


class ConsoleTransport(transport_mod.Transport):
    """demo  API"""

    def __init__(self):
        self.inner = transport_mod.RecordingTransport()

    def send(self, req):
        res = self.inner.send(req)
        print(f"[SEND] {req.platform} {req.method} {req.url} "
              f"body={json.dumps(req.body, ensure_ascii=False)[:180]} -> {res['status']}")
        return res


def make_handler(bridge):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ReplyBridge/0.1"

        def log_message(self, fmt, *args):
            return

        def _json(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _text(self, code, text, content_type="text/plain; charset=utf-8"):
            body = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            flat = {k: v[0] for k, v in q.items()}
            parts = [p for p in u.path.split("/") if p]
            if u.path == "/":
                return self._text(200, CONSOLE_HTML, "text/html; charset=utf-8")
            if u.path == "/healthz":
                return self._json(200, {"ok": True, "service": "replybridge"})
            if u.path == "/stats":
                return self._json(200, bridge.stats())
            if u.path == "/decisions":
                try:
                    lim = int(flat.get("limit", "30") or 30)
                except ValueError:
                    lim = 30
                return self._json(200, {"decisions": bridge.store.recent_ledger(max(1, min(lim, 200)))})
            if u.path == "/queue":
                return self._json(200, {"items": bridge.store.list_queue(limit=50)})
            if len(parts) == 2 and parts[0] == "webhooks":
                ch = bridge.verify_challenge(parts[1], flat)
                if ch is None:
                    return self._text(403, "verification failed")
                return self._text(200, ch)
            return self._json(404, {"ok": False, "reason": "not_found"})

        def do_POST(self):
            u = urlparse(self.path)
            parts = [p for p in u.path.split("/") if p]
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            if len(parts) == 2 and parts[0] == "webhooks":
                res = bridge.handle(parts[1], raw, headers)
                return self._json(res.get("status", 200), res)
            if len(parts) == 3 and parts[0] == "queue" and parts[2] == "resolve":
                try:
                    body = json.loads(raw.decode("utf-8") or "{}")
                    out = bridge.resolve_queue(int(parts[1]), body.get("reply_text", ""), body.get("by", "human"))
                    return self._json(200, out)
                except KeyError as e:
                    return self._json(404, {"ok": False, "reason": str(e)})
            return self._json(404, {"ok": False, "reason": "not_found"})

    return Handler


def serve(port=8080, handler=None, bridge=None):
    bridge = bridge or build_bridge()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler or make_handler(bridge))
    return httpd


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("RB_PORT", 8080)))
    ap.add_argument("--demo", action="store_true", help=" API")
    args = ap.parse_args(argv)
    if args.demo:
        bridge = build_bridge(transport=ConsoleTransport())
        httpd = serve(args.port, bridge=bridge)
    else:
        httpd = serve(args.port)
    print(f"ReplyBridge listening on http://127.0.0.1:{httpd.server_address[1]}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
