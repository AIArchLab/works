"""ReplyBridge 核心編排層：入站 → 政策 → 外送 → 帳本。

刻意不含 HTTP 細節，讓 E2E 測試可以同時跑真實 socket 與注入式 transport。
"""
import json
import os
import sys
import time

from . import contracts
from . import channels
from . import policy as policy_mod
from . import ai as ai_mod


class Tenant:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.tenant_id = cfg["tenant_id"]
        self.name = cfg.get("name", self.tenant_id)
        self.policy = policy_mod.Policy(cfg["policy"])
        self.accounts = {}
        for plat, acct in (cfg.get("accounts") or {}).items():
            self.accounts[plat] = str(acct.get("account_id", ""))

    def owns(self, platform: str, account_id: str) -> bool:
        return self.accounts.get(platform) == str(account_id)


class Bridge:
    """單一實例可同時服務多個 tenant（多品牌、多粉專）。"""

    def __init__(self, tenants, secrets: dict, store, transport, kb=None, drafter=None, clock=None):
        self.tenants = {t["tenant_id"]: Tenant(t) for t in tenants}
        self.secrets = secrets
        self.store = store
        self.transport = transport
        self.kb = kb or []
        self.drafter = drafter or ai_mod.Drafter(self.kb)
        self.clock = clock or time.time
        self._lat = []

    # ---------- 對外入口 ----------
    def verify_challenge(self, platform: str, query: dict):
        try:
            return channels.verify_challenge(platform, query, self.secrets)
        except TypeError:  # 相容只收兩個參數的實作
            return channels.verify_challenge(platform, query)

    def handle(self, platform: str, raw_body: bytes, headers: dict, query=None) -> dict:
        """處理一次 webhook 交付。回傳結構化結果，永不因單一事件失敗而整批 500。"""
        t0 = time.time()
        query = query or {}
        if platform not in contracts.PLATFORMS:
            return {"ok": False, "status": 404, "reason": "unknown_platform"}

        if not channels.verify(platform, headers, raw_body, self.secrets):
            self.store.append("verify_failed", {"platform": platform, "bytes": len(raw_body)})
            return {"ok": False, "status": 401, "reason": "signature_invalid"}

        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception:
            return {"ok": False, "status": 400, "reason": "bad_json"}

        events = channels.parse(platform, payload, "pending")
        results = []
        for ev in events:
            tenant = self._resolve_tenant(platform, ev.account_id)
            if tenant is None:
                self.store.append("unrouted", {"platform": platform, "account_id": ev.account_id,
                                               "message_id": ev.message_id})
                results.append({"message_id": ev.message_id, "action": "unrouted"})
                continue
            ev.tenant_id = tenant.tenant_id
            results.append(self._process(tenant, ev))

        return {"ok": True, "status": 200, "platform": platform, "handled": len(results),
                "results": results, "elapsed_ms": round((time.time() - t0) * 1000, 2)}

    # ---------- 單一事件 ----------
    def _process(self, tenant: Tenant, ev) -> dict:
        t0 = time.time()
        decision = tenant.policy.decide(ev, self._draft, self.store)
        out = None
        send = None

        if decision.action == "reply":
            out = channels.build_reply_request(ev.platform, ev, decision.reply_text,
                                               self._creds(tenant, ev.platform))
            send = self.transport.send(out)
            if send.get("status") not in (200, 201, 202):
                # 外送失敗：不得假裝已回覆，轉人工隊列
                decision.action = "escalate"
                decision.escalate_reason = f"send_failed:{send.get('status')}"
                self.store.enqueue(ev.to_dict(), decision.to_dict())
            elif hasattr(self.store, "mark_replied"):
                self.store.mark_replied(ev.dedupe_key())
        elif decision.action == "escalate":
            self.store.enqueue(ev.to_dict(), decision.to_dict())

        record = {
            "tenant_id": tenant.tenant_id,
            "platform": ev.platform,
            "account_id": ev.account_id,
            "kind": ev.kind,
            "message_id": ev.message_id,
            "thread_id": ev.thread_id,
            "author_id": ev.author_id,
            "inbound_text": ev.text,
            "action": decision.action,
            "reply_text": decision.reply_text,
            "policy_hits": decision.policy_hits,
            "confidence": decision.confidence,
            "model": decision.model,
            "reason": decision.reason,
            "escalate_reason": decision.escalate_reason,
            "send_status": (send or {}).get("status"),
            "endpoint_status": getattr(channels, "ENDPOINT_STATUS", {}).get(ev.platform, "unknown"),
            "latency_ms": round((time.time() - t0) * 1000, 2),
        }
        self._lat.append(record["latency_ms"])
        entry = self.store.append("decision", record)
        return {"message_id": ev.message_id, "action": decision.action,
                "confidence": decision.confidence, "model": decision.model,
                "policy_hits": decision.policy_hits, "escalate_reason": decision.escalate_reason,
                "reply_text": decision.reply_text, "send_status": (send or {}).get("status"),
                "ledger_seq": entry.get("seq"), "latency_ms": record["latency_ms"]}

    def _draft(self, ev):
        return self.drafter.draft(ev)

    def _resolve_tenant(self, platform, account_id):
        for t in self.tenants.values():
            if t.owns(platform, account_id):
                return t
        # 平台唯一後備：TikTok／部分平台的 webhook 不帶商家帳號 ID，
        # 若只有一個 tenant 配置了該平台，直接路由給它（多個就仍視為無法路由）。
        candidates = [t for t in self.tenants.values() if platform in t.accounts]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _creds(self, tenant: Tenant, platform: str) -> dict:
        acct = (tenant.cfg.get("accounts") or {}).get(platform) or {}
        creds = {**{k: v for k, v in acct.items() if k != "account_id"},
                 **{k: v for k, v in self.secrets.items() if k.startswith(platform)}}
        return creds

    # ---------- 人工隊列 ----------
    def resolve_queue(self, item_id: int, reply_text: str, by: str) -> dict:
        item = None
        for q in self.store.list_queue(limit=500):
            if q["id"] == int(item_id):
                item = q
                break
        if item is None:
            raise KeyError(f"queue item {item_id} not found or already resolved")
        de = item["event"]
        platform = de.get("platform")
        tenant = self._resolve_tenant(platform, de.get("account_id"))
        creds = dict(self._creds(tenant, platform)) if tenant else {}
        if platform == "line":
            creds["line_delivery"] = "push"  # 人工核准時 replyToken 已過期
        out = channels.build_reply_request(platform, contracts.InboundEvent(**{
            k: de[k] for k in ("platform", "tenant_id", "account_id", "kind", "message_id",
                               "thread_id", "parent_id", "author_id", "author_name", "text",
                               "created_at", "lang", "raw")}), reply_text,
            creds)
        send = self.transport.send(out)
        self.store.resolve_queue(int(item_id), reply_text, by)
        self.store.append("human_resolved", {"queue_id": int(item_id), "by": by,
                                             "reply_text": reply_text, "send_status": send.get("status")})
        return {"queue_id": int(item_id), "send_status": send.get("status")}

    # ---------- 觀測 ----------
    def stats(self) -> dict:
        s = dict(self.store.stats())
        s["tenants"] = sorted(self.tenants)
        s["latency"] = self._latency_summary()
        return s

    def _latency_summary(self) -> dict:
        vals = list(getattr(self, "_lat", []))
        if not vals:
            return {"n": 0}
        vals.sort()
        p = lambda q: vals[min(len(vals) - 1, int(len(vals) * q))]
        return {"n": len(vals), "p50_ms": p(0.50), "p95_ms": p(0.95), "max_ms": vals[-1]}
