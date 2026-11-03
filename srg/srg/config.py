import json, secrets
PLACEHOLDERS = {"", "change_me", "changeme", "todo", "xxx", "secret", "password", "admin", "token", "verify-me"}
def check_config(cfg):
    """Refuse placeholder/weak secrets. Raises ValueError listing every problem."""
    bad = []
    def weak(v): return not isinstance(v, str) or v.strip().lower() in PLACEHOLDERS or v.strip().lower().startswith("generate") or len(v) < 16
    if "admin_token" not in cfg: bad.append("admin_token is required")
    if "admin_token" in cfg and weak(cfg["admin_token"]): bad.append("admin_token is a placeholder or shorter than 16 chars")
    if cfg.get("verify_token") is not None and weak(cfg["verify_token"]): bad.append("verify_token is a placeholder or shorter than 16 chars")
    for plat, c in (cfg.get("platforms") or {}).items():
        for k, v in c.items():
            if isinstance(v, str) and any(w in v.strip().lower() for w in ("change_me", "changeme", "generate-", "your_", "xxx")): bad.append(f"{plat}.{k} is a placeholder")
    if bad: raise ValueError("; ".join(bad))
    return cfg
