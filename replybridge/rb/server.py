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



CONSOLE_HTML = """<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
<title>ReplyBridge </title>
<style>body{font-family:system-ui,-apple-system,"Noto Sans TC",sans-serif;margin:0;background:#0f1115;color:#e8eaed}
header{padding:14px 20px;background:#171a21;border-bottom:1px solid #262b36;font-weight:600}
main{padding:20px;display:grid;gap:16px;max-width:1100px}
.card{background:#171a21;border:1px solid #262b36;border-radius:10px;padding:16px}
h2{font-size:14px;margin:0 0 10px;color:#9aa4b2;font-weight:600;letter-spacing:.04em}
td,th{padding:6px 8px;border-bottom:1px solid #222732;font-size:13px;text-align:left;vertical-align:top}
table{width:100%;border-collapse:collapse}
.k{color:#7dd3fc}.v{color:#fbbf24}.muted{color:#6b7280}
textarea,input{width:100%;background:#0f1115;border:1px solid #2a3140;color:#e8eaed;border-radius:6px;padding:8px;font:13px system-ui}
button{background:#2563eb;color:#fff;border:0;border-radius:6px;padding:8px 14px;font-size:13px;cursor:pointer;margin-top:8px}
</style>
<header>ReplyBridge  · </header>
<main>
 <div class="card"><h2> /stats</h2><div id="stats" class="muted">…</div></div>
 <div class="card"><h2> /queue</h2><table id="q"><thead><tr><th>
</main>
<script>
const g=async u=>(await fetch(u)).json();
function esc(s){return (s??'').toString().replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))}
async function load(){
 const s=await g('/stats');
 document.getElementById('stats').innerHTML =
  `<span class="k"></span> ${s.ledger_entries} · <span class="k"></span> ${s.chain_ok} · `
  +`<span class="k"></span> ${s.queue_open} · <span class="k">p50</span> ${s.latency?.p50_ms??'-'}ms · `
  +`<span class="k">p95</span> ${s.latency?.p95_ms??'-'}ms · <span class="k"></span> <span class="v">${JSON.stringify(s.by_action||{})}</span>`;
 const q=await g('/queue'); const tb=document.querySelector('#q tbody'); tb.innerHTML='';
 (q.items||[]).forEach(it=>{
  const tr=document.createElement('tr');
  tr.innerHTML=`<td>${it.id}</td><td>${esc(it.event.platform)}</td><td>${esc(it.event.text)}</td>`
   +`<td class="v">${esc(it.decision.escalate_reason||it.decision.reason)}</td>`
   +`<td><textarea rows="2" id="t${it.id}"></textarea><button onclick="resolve(${it.id})"></button></td>`;
  tb.appendChild(tr);
 });
}
async function resolve(id){
 const text=document.getElementById('t'+id).value;
 await fetch('/queue/'+id+'/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reply_text:text,by:'console_operator'})});
 load();
}
load(); setInterval(load,5000);
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

        def _text(self, code, text):
            body = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            flat = {k: v[0] for k, v in q.items()}
            parts = [p for p in u.path.split("/") if p]
            if u.path == "/":
                return self._text(200, CONSOLE_HTML)
            if u.path == "/healthz":
                return self._json(200, {"ok": True, "service": "replybridge"})
            if u.path == "/stats":
                return self._json(200, bridge.stats())
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
