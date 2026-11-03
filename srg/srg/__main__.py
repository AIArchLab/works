"""Run: python -m srg  (config via SRG_CONFIG json path). Real platform base URLs go in config; defaults point at real hosts but are untested."""
import json, os, sys
from .store import Store; from .adapters import make_adapters; from .pipeline import Pipeline; from .server import make_server
from .config import check_config
cfg = check_config(json.load(open(os.environ.get("SRG_CONFIG", "config.json"))))
st = Store(cfg.get("db", "srg.db"))
if not st.latest_rules()[0]: st.add_rules(cfg.get("rules", {"faq": []}))
bases = {"facebook": "https://graph.facebook.com", "instagram": "https://graph.facebook.com", "line": "https://api.line.me", "tiktok": "https://business-api.tiktok.com"}
bases.update(cfg.get("send_bases", {}))
import secrets as _s
admin = cfg.get("admin_token") or _s.token_urlsafe(24)
if not cfg.get("admin_token"): print("generated admin token (open /?t=TOKEN once):", admin)
p = Pipeline(st, make_adapters(cfg["platforms"]), bases, cfg.get("llm"))
srv = make_server(p, cfg.get("host", "127.0.0.1"), cfg.get("port", 8080), cfg.get("verify_token"), admin)
p.recover()
print("listening", srv.server_address); srv.serve_forever()
