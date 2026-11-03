"""新增／檢查租戶設定。證明「換客戶＝改資料，不改程式」。

用法：
    python3 tools/validate_tenant.py config/tenants.json
退出碼 0 = 通過，1 = 有問題（逐條列出）。
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
        problems.append("沒有任何 tenant")
    seen_ids = set()
    for i, t in enumerate(tenants):
        tag = f"tenants[{i}]"
        tid = t.get("tenant_id")
        if not tid:
            problems.append(f"{tag} 缺 tenant_id")
        elif tid in seen_ids:
            problems.append(f"{tag} tenant_id 重複：{tid}")
        seen_ids.add(tid)
        accts = t.get("accounts") or {}
        if not accts:
            problems.append(f"{tag} 沒有 accounts，收不到任何事件")
        for plat, acct in accts.items():
            if plat not in contracts.PLATFORMS:
                problems.append(f"{tag}.accounts 不支援的平台：{plat}")
            if not str(acct.get("account_id") or "").strip():
                problems.append(f"{tag}.accounts.{plat} 缺 account_id")
        pol = t.get("policy") or {}
        guard = pol.get("guardrails") or {}
        for k in REQUIRED_GUARD:
            if k not in guard:
                problems.append(f"{tag}.policy.guardrails 缺 {k}（會用預設值，但請顯式寫出）")
        if guard.get("min_confidence", 0) < 0.5:
            problems.append(f"{tag} min_confidence < 0.5，等於放任低信心自動回覆")
        for r in pol.get("rules") or []:
            if not r.get("id"):
                problems.append(f"{tag} 有規則缺 id")
            if r.get("action") not in ("reply_canned", "escalate", "ignore"):
                problems.append(f"{tag} 規則 {r.get('id')} action 不合法：{r.get('action')}")
            if r.get("action") == "reply_canned" and not r.get("reply"):
                problems.append(f"{tag} 規則 {r.get('id')} 是 reply_canned 但沒有 reply 內容")
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
        print(f"\n{len(problems)} 個問題：")
        for p in problems:
            print("  -", p)
        return 1
    print("設定檢查通過：可直接上線，無需改程式碼。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
