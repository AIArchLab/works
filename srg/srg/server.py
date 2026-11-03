import json, threading, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from .adapters import platform_status
from .decision import validate_rules
import secrets, hmac
UI = open(os.path.join(os.path.dirname(__file__), "admin.html"), encoding="utf-8").read()
MAX_BODY = 1_000_000
def make_server(pipe, host="127.0.0.1", port=0, verify_token=None, admin_token=None):
    if not admin_token: raise ValueError("admin_token is required")
    class H(BaseHTTPRequestHandler):
        def log_message(s, *a): pass
        def _send(s, code, body, ct="application/json"):
            b = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)).encode()
            s.send_response(code); s.send_header("Content-Type", ct + "; charset=utf-8"); s.end_headers(); s.wfile.write(b)
        def _admin_ok(s):
            got = s.headers.get("X-Admin-Token")
            if got is None:
                for part in (s.headers.get("Cookie") or "").split(";"):
                    if part.strip().startswith("srg_admin="): got = part.strip()[10:]
            return got is not None and hmac.compare_digest(got.encode(), admin_token.encode())
        def do_GET(s):
            u = urlparse(s.path)
            if u.path.startswith("/webhook/"):  # Meta verification handshake
                q = parse_qs(u.query)
                if verify_token and q.get("hub.verify_token") == [verify_token]: return s._send(200, q.get("hub.challenge", [""])[0], "text/plain")
                return s._send(403, "forbidden", "text/plain")
            if u.path == "/" and parse_qs(u.query).get("t") == [admin_token]:   # one-time login: set cookie, strip token from URL
                s.send_response(302); s.send_header("Set-Cookie", f"srg_admin={admin_token}; HttpOnly; SameSite=Strict; Path=/"); s.send_header("Location", "/"); s.end_headers(); return
            if not s._admin_ok(): return s._send(401, {"error": "admin token"})
            if u.path == "/": return s._send(200, UI, "text/html")
            if u.path == "/api/events":
                return s._send(200, pipe.st.rows("select * from events order by id desc limit 200"))
            if u.path.startswith("/api/audit/"):
                return s._send(200, pipe.st.rows("select * from audit where event_pk=? order by id", (int(u.path.rsplit("/", 1)[1]),)))
            if u.path == "/api/settings":
                v, r = pipe.st.latest_rules()
                return s._send(200, {"autoreply_enabled": pipe.st.get_setting("autoreply_enabled", True), "rule_version": v, "rules": r, "platform_status": platform_status()})
            s._send(404, {"error": "nf"})
        def do_POST(s):
            try: n = int(s.headers.get("Content-Length", 0))
            except ValueError: return s._send(400, {"error": "bad length"})
            if n < 0: return s._send(400, {"error": "bad length"})
            if n > MAX_BODY: return s._send(413, {"error": "too large"})
            u = urlparse(s.path)
            if not u.path.startswith("/webhook/") and not s._admin_ok(): return s._send(401, {"error": "admin token"})
            body = s.rfile.read(n)
            if u.path.startswith("/webhook/"):
                code, res = pipe.ingest(u.path.rsplit("/", 1)[1], dict(s.headers), body)
                if code == 200:
                    s._send(200, {"accepted": res})
                    for pk in res: threading.Thread(target=pipe.process, args=(pk,), daemon=True).start()
                    return
                return s._send(code, {"error": res})
            try: d = json.loads(body or b"{}")
            except Exception: return s._send(400, {"error": "invalid json"})
            try:
                if u.path == "/api/autoreply":
                    pipe.st.set_setting("autoreply_enabled", bool(d["enabled"]))
                    if d["enabled"]: threading.Thread(target=pipe.recover, daemon=True).start()
                    return s._send(200, {"ok": True})
                if u.path == "/api/rules": return s._send(200, {"version": pipe.st.add_rules(validate_rules(d))})
                if u.path.startswith("/api/retry/"):
                    pk = int(u.path.rsplit("/", 1)[1]); force = bool(d.get("force"))
                    threading.Thread(target=(pipe.retry_force if force else pipe.retry), args=(pk,), daemon=True).start(); return s._send(200, {"ok": True})
            except (KeyError, ValueError, TypeError) as e: return s._send(400, {"error": f"{type(e).__name__}: {e}"})
            s._send(404, {"error": "nf"})
    srv = ThreadingHTTPServer((host, port), H); return srv
