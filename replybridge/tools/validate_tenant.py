"""


    python3 tools/validate_tenant.py config/tenants.json
 0 = 1 = 
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rb import contracts  # noqa: E402

REQUIRED_GUARD = ("min_confidence", "max_replies_per_thread_per_hour", "max_reply_chars")


def validate(cfg):
    problems = []
    tenants = cfg.get("tenants") or []
    if not tenants:
        problems.append(" tenant")
    seen_ids = set()
    for i, t in enumerate(tenants):
        tag = f"tenants[{i}]"
        tid = t.get("tenant_id")
        if not tid:
            problems.append(f"{tag}  tenant_id")
        elif tid in seen_ids:
            problems.append(f"{tag} tenant_id {tid}")
        seen_ids.add(tid)
        accts = t.get("accounts") or {}
        if not accts:
            problems.append(f"{tag}  accounts")
        for plat, acct in accts.items():
            if plat not in contracts.PLATFORMS:
                problems.append(f"{tag}.accounts {plat}")
            if not str(acct.get("account_id") or "").strip():
                problems.append(f"{tag}.accounts.{plat}  account_id")
        pol = t.get("policy") or {}
        guard = pol.get("guardrails") or {}
        for k in REQUIRED_GUARD:
            if k not in guard:
                problems.append(f"{tag}.policy.guardrails  {k}")
        if guard.get("min_confidence", 0) < 0.5:
            problems.append(f"{tag} min_confidence < 0.5")
        for r in pol.get("rules") or []:
            if not r.get("id"):
                problems.append(f"{tag}  id")
            if r.get("action") not in ("reply_canned", "escalate", "ignore"):
                problems.append(f"{tag}  {r.get('id')} action {r.get('action')}")
            if r.get("action") == "reply_canned" and not r.get("reply"):
                problems.append(f"{tag}  {r.get('id')}  reply_canned  reply ")
    return problems


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "config/tenants.json"
    cfg = json.load(open(path, encoding="utf-8"))
    problems = validate(cfg)
    n = len(cfg.get("tenants") or [])
    rules = sum(len((t.get("policy") or {}).get("rules") or []) for t in cfg.get("tenants") or [])
    plats = sorted({p for t in cfg.get("tenants") or [] for p in (t.get("accounts") or {})})
    print(f"tenants={n} rules={rules} platforms={plats}")
    if problems:
        print(f"\n{len(problems)} ")
        for p in problems:
            print("  -", p)
        return 1
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
