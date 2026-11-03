#!/usr/bin/env python3
"""ReplyBridge policy.py 單元測試（W2）。

直接執行：cd replybridge && python3 tests/test_policy.py
零依賴（stdlib only），不需要 pytest；印 PASS/FAIL，全綠才 exit 0。

覆蓋 12+ 情境：
  1 重複事件不重複回          7 高信心放行
  2 跨午夜靜默時段            8 草稿命中敏感詞（draft_blocked）
  3 速率超限升級              9 過長截斷 + 簽名
  4 入站命中敏感詞           10 drafter 拋例外
  5 canned 規則 + 變數替換   11 命中的 ignore 規則
  6 低信心升級               12 policy_hits 內容正確
  + 額外：drafter 自我放棄、PII、話術模板、壞 regex、store 例外不掉例外、
    'all' 比對、截斷後長度上限、created_at 無法解析、未知 action 保守升級。
"""
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, os.path.join(_ROOT, "rb")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import contracts                      # noqa: E402
from contracts import InboundEvent, Draft, Decision   # noqa: E402
import policy as policy_mod           # noqa: E402
from policy import Policy             # noqa: E402

RESULTS = []


# --------------------------------------------------------------------------- #
# 測試替身
# --------------------------------------------------------------------------- #
class FakeStore:
    """in-test 儲存層：去重 set + 速率計數器 + 呼叫計數（證明沒被偷呼叫）。"""

    def __init__(self, rate_limit_hits=None):
        self.seen_keys = {}
        self.rate = {}
        self.seen_calls = 0
        self.mark_seen_calls = 0
        self.incr_rate_calls = 0
        self.rate_values = list(rate_limit_hits or [])

    def seen(self, key):
        self.seen_calls += 1
        return key in self.seen_keys

    def mark_seen(self, key, meta):
        self.mark_seen_calls += 1
        self.seen_keys[key] = meta

    def incr_rate(self, bucket, window_s):
        assert window_s == 3600, f"window 應為 3600，得到 {window_s}"
        self.incr_rate_calls += 1
        cur = self.rate.get(bucket, 0) + 1
        self.rate[bucket] = cur
        if self.rate_values:
            return self.rate_values.pop(0)
        return cur

    # 其他 Store Protocol 方法：policy 不該呼叫
    def append(self, kind, payload):
        raise AssertionError("policy 不得寫帳本（append）")

    def enqueue(self, event, decision):
        raise AssertionError("policy 不得自己入隊（enqueue）")


class SpyDrafter:
    """記錄被呼叫次數的 draft_fn。"""

    def __init__(self, draft=None, exc=None):
        self.calls = 0
        self.draft_obj = draft
        self.exc = exc

    def __call__(self, ev):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        if self.draft_obj is not None:
            return self.draft_obj
        return Draft(text=f"draft for {ev.author_name}", confidence=0.9, model="llm:test")


def ev(**kw):
    base = dict(
        platform="meta_instagram",
        tenant_id="t1",
        account_id="ig_1",
        kind=contracts.KIND_COMMENT,
        message_id="m1",
        thread_id="post_9",
        parent_id="",
        author_id="u1",
        author_name="小美",
        text="請問還有貨嗎",
        created_at="2026-11-03T06:20:00Z",
        lang="zh-TW",
        raw={},
    )
    base.update(kw)
    return InboundEvent(**base)


def cfg(rules=None, guard=None, persona=None):
    return {
        "tenant_id": "t1",
        "rules": rules or [],
        "guardrails": guard or {},
        "persona": persona or {},
    }


def check(name, fn):
    try:
        fn()
    except AssertionError as exc:
        RESULTS.append((name, False, str(exc)))
    except Exception:
        RESULTS.append((name, False, traceback.format_exc(limit=3).strip().splitlines()[-1]))
    else:
        RESULTS.append((name, True, ""))


# --------------------------------------------------------------------------- #
# 1) 去重
# --------------------------------------------------------------------------- #
def t_dedupe():
    store = FakeStore()
    spy = SpyDrafter()
    p = Policy(cfg())

    d1 = p.decide(ev(), spy, store)
    assert d1.action == "reply", d1.to_dict()
    assert spy.calls == 1, f"首次應呼叫 drafter 一次，實際 {spy.calls}"
    assert store.mark_seen_calls == 1
    first_rate_calls = store.incr_rate_calls

    # 同一 key 再來一次
    d2 = p.decide(ev(text="同樣的訊息第二次送達"), spy, store)
    assert d2.action == "ignore", d2.to_dict()
    assert d2.reason == "duplicate", d2.reason
    assert spy.calls == 1, f"重複事件不得再呼叫 draft_fn（calls={spy.calls}）"
    assert store.incr_rate_calls == first_rate_calls, "重複事件不得再 incr_rate"
    assert store.mark_seen_calls == 1, "重複事件不得重寫 mark_seen"
    assert d2.policy_hits and "dedupe" in d2.policy_hits, d2.policy_hits


# --------------------------------------------------------------------------- #
# 2) 跨午夜靜默時段
# --------------------------------------------------------------------------- #
def t_quiet_cross_midnight():
    g = {"quiet_hours": {"start": 22, "end": 8, "tz_offset_hours": 8}}  # UTC+8
    p = Policy(cfg(guard=g))

    # 23:30 當地（UTC 15:30）→ 靜默
    d = p.decide(ev(created_at="2026-11-03T15:30:00Z"), SpyDrafter(), FakeStore())
    assert d.action == "escalate", d.to_dict()
    assert d.escalate_reason == "quiet_hours", d.escalate_reason

    # 02:00 當地（UTC 前一日 18:00）→ 仍靜默（跨午夜下半段）
    d = p.decide(ev(message_id="m2", created_at="2026-11-02T18:00:00Z"), SpyDrafter(), FakeStore())
    assert d.action == "escalate" and d.escalate_reason == "quiet_hours", d.to_dict()

    # 10:00 當地 → 可回
    d = p.decide(ev(message_id="m3", created_at="2026-11-03T02:00:00Z"), SpyDrafter(), FakeStore())
    assert d.action == "reply", d.to_dict()

    # 邊界：22:00 整 = start → 靜默；08:00 整 = end → 可回
    d = p.decide(ev(message_id="m4", created_at="2026-11-03T14:00:00Z"), SpyDrafter(), FakeStore())
    assert d.action == "escalate", f"22:00 應靜默：{d.to_dict()}"
    d = p.decide(ev(message_id="m5", created_at="2026-11-03T00:00:00Z"), SpyDrafter(), FakeStore())
    assert d.action == "reply", f"08:00 應可回：{d.to_dict()}"

    # 非跨午夜區間（09:00-18:00）
    g2 = {"quiet_hours": {"start": "09:00", "end": "18:00", "tz_offset_hours": 0}}
    p2 = Policy(cfg(guard=g2))
    d = p2.decide(ev(message_id="m6", created_at="2026-11-03T12:00:00Z"), SpyDrafter(), FakeStore())
    assert d.action == "escalate" and d.escalate_reason == "quiet_hours", d.to_dict()
    d = p2.decide(ev(message_id="m7", created_at="2026-11-03T20:00:00Z"), SpyDrafter(), FakeStore())
    assert d.action == "reply", d.to_dict()

    # created_at 壞掉不得 raise，且不當成靜默
    d = p2.decide(ev(message_id="m8", created_at="not-a-date"), SpyDrafter(), FakeStore())
    assert d.action == "reply", d.to_dict()
    assert "guardrail:quiet_hours:unparsable" in d.policy_hits, d.policy_hits


# --------------------------------------------------------------------------- #
# 3) 速率超限
# --------------------------------------------------------------------------- #
def t_rate_limited():
    g = {"max_replies_per_thread_per_hour": 3}
    store = FakeStore()
    p = Policy(cfg(guard=g))
    acts = []
    for i in range(1, 6):
        d = p.decide(ev(message_id=f"r{i}", created_at="2026-11-03T06:20:00Z"), SpyDrafter(), store)
        acts.append((d.action, d.escalate_reason))
    assert acts[0][0] == "reply", acts
    assert acts[1][0] == "reply", acts
    assert acts[2][0] == "reply", acts
    assert acts[3] == ("escalate", "rate_limited"), f"第 4 次應超限：{acts[3]}"
    assert acts[4] == ("escalate", "rate_limited"), f"第 5 次應超限：{acts[4]}"

    # 不同 thread 各自計數
    d = p.decide(ev(message_id="r9", thread_id="post_other"), SpyDrafter(), store)
    assert d.action == "reply", f"不同 thread 不應被同桶限制：{d.to_dict()}"

    # 明確回傳值優先於計數器（模擬視窗滑動後回 1）
    p2 = Policy(cfg(guard={"max_replies_per_thread_per_hour": 1}))
    d = p2.decide(ev(message_id="r10"), SpyDrafter(), FakeStore(rate_limit_hits=[1, 2]))
    assert d.action == "reply", d.to_dict()
    d = p2.decide(ev(message_id="r11"), SpyDrafter(), FakeStore(rate_limit_hits=[2]))
    assert d.action == "escalate" and d.escalate_reason == "rate_limited", d.to_dict()


# --------------------------------------------------------------------------- #
# 4) 入站護欄（敏感詞 / PII）
# --------------------------------------------------------------------------- #
def t_inbound_guardrail():
    g = {
        "blocked_patterns": [r"退款", r"(?i)refund"],
        "pii_patterns": [r"\b09\d{8}\b", r"[\w.+-]+@[\w-]+\.[\w.]+"],
    }
    p = Policy(cfg(guard=g))

    spy = SpyDrafter()
    d = p.decide(ev(text="我要退款！"), spy, FakeStore())
    assert d.action == "escalate", d.to_dict()
    assert d.escalate_reason == "guardrail:退款", d.escalate_reason
    assert spy.calls == 0, "入站命中護欄不得呼叫 drafter"
    assert "guardrail:blocked:退款" in d.policy_hits, d.policy_hits

    d = p.decide(ev(message_id="m2", text="Please REFUND now"), SpyDrafter(), FakeStore())
    assert d.action == "escalate" and d.escalate_reason == r"guardrail:(?i)refund", d.to_dict()

    d = p.decide(ev(message_id="m3", text="我的電話 0912345678"), SpyDrafter(), FakeStore())
    assert d.action == "escalate", d.to_dict()
    assert d.escalate_reason.startswith("guardrail:"), d.escalate_reason
    assert "09" in d.escalate_reason, d.escalate_reason

    # 壞 regex 不得讓 Policy 掛掉，且不影響其他 pattern
    p2 = Policy(cfg(guard={"blocked_patterns": ["(unclosed", "退款"]}))
    d = p2.decide(ev(text="我想退款"), SpyDrafter(), FakeStore())
    assert d.action == "escalate" and d.escalate_reason == "guardrail:退款", d.to_dict()


# --------------------------------------------------------------------------- #
# 5) canned 規則 + 變數替換
# --------------------------------------------------------------------------- #
def t_canned_rule():
    rules = [{
        "id": "greet",
        "when": {"keywords": ["還有貨", "現貨"], "platforms": ["meta_instagram"], "match": "any"},
        "action": "reply_canned",
        "reply": "嗨 {{author_name}}，有的！現貨可以直接下單～",
    }]
    p = Policy(cfg(rules=rules, persona={"signature": "— AIArchLab"}))
    d = p.decide(ev(), SpyDrafter(), FakeStore())
    assert d.action == "reply", d.to_dict()
    assert d.reply_text.startswith("嗨 小美，有的！"), d.reply_text
    assert d.reply_text == "嗨 小美，有的！現貨可以直接下單～\n— AIArchLab", d.reply_text
    assert "{{author_name}}" not in d.reply_text, d.reply_text
    assert d.confidence == 0.99, d.confidence
    assert d.model == "rule:greet", d.model
    assert "rule:greet" in d.policy_hits, d.policy_hits

    # platforms 是硬過濾：平台不符 → 規則不命中，走 drafter（避免誤放行）
    d = p.decide(ev(message_id="m2", platform="line"), SpyDrafter(), FakeStore())
    assert d.action == "reply" and d.model == "llm:test", d.to_dict()
    assert "rule:greet" not in d.policy_hits, d.policy_hits
    # 平台符合但關鍵字不符 → 也不命中
    d = p.decide(ev(message_id="m2b", text="請問營業時間"), SpyDrafter(), FakeStore())
    assert d.model == "llm:test", f"關鍵字不符應走 drafter：{d.to_dict()}"

    # match 語意：platforms/kinds 為硬過濾，match 只作用在 keywords
    rules_any = [{"id": "both", "when": {"keywords": ["貨", "庫存"], "platforms": ["meta_instagram"],
                                        "match": "any"},
                  "action": "reply_canned", "reply": "ANY"}]
    d = Policy(cfg(rules=rules_any)).decide(ev(), SpyDrafter(), FakeStore())
    assert d.reply_text.startswith("ANY"), f"any：任一關鍵字成立即命中 → {d.to_dict()}"
    d = Policy(cfg(rules=rules_any)).decide(
        ev(message_id="m3", platform="meta_instagram", text="無關內容"), SpyDrafter(), FakeStore())
    assert "rule:both" not in d.policy_hits, f"關鍵字全不符應不命中：{d.policy_hits}"
    # any：多關鍵字只中一個也成立
    d = Policy(cfg(rules=rules_any)).decide(
        ev(message_id="m3b", text="想問庫存"), SpyDrafter(), FakeStore())
    assert "rule:both" in d.policy_hits, f"any 應接受部分命中：{d.policy_hits}"
    # all：多關鍵字必須全部出現
    rules_all_kw = [{"id": "kw_all", "when": {"keywords": ["貨", "庫存"], "match": "all"},
                     "action": "reply_canned", "reply": "KWALL"}]
    d = Policy(cfg(rules=rules_all_kw)).decide(ev(text="想問庫存"), SpyDrafter(), FakeStore())
    assert "rule:kw_all" not in d.policy_hits, f"all 缺一不可：{d.policy_hits}"
    d = Policy(cfg(rules=rules_all_kw)).decide(ev(text="庫存與貨"), SpyDrafter(), FakeStore())
    assert d.reply_text.startswith("KWALL"), d.to_dict()
    # kinds 硬過濾
    rules_kind = [{"id": "dm_only", "when": {"kinds": ["dm"]}, "action": "reply_canned", "reply": "DM"}]
    d = Policy(cfg(rules=rules_kind)).decide(ev(), SpyDrafter(), FakeStore())
    assert "rule:dm_only" not in d.policy_hits, d.policy_hits
    d = Policy(cfg(rules=rules_kind)).decide(ev(message_id="m5", kind="dm"), SpyDrafter(), FakeStore())
    assert d.reply_text.startswith("DM"), d.to_dict()
    # match='all'：全部條件都要成立（平台符合才命中）
    rules_all = [{"id": "both_all", "when": {"keywords": ["貨"], "platforms": ["line"],
                                            "match": "all"},
                  "action": "reply_canned", "reply": "ALL"}]
    p3 = Policy(cfg(rules=rules_all))
    d = p3.decide(ev(), SpyDrafter(), FakeStore())
    assert d.reply_text != "ALL" and "rule:both_all" not in d.policy_hits, d.to_dict()
    d = p3.decide(ev(message_id="m4", platform="line"), SpyDrafter(), FakeStore())
    assert d.reply_text.startswith("ALL"), d.to_dict()

    # 第一條命中即採用（後面的規則不得覆蓋）
    rules2 = [
        {"id": "first", "when": {"keywords": ["貨"]}, "action": "reply_canned", "reply": "FIRST"},
        {"id": "second", "when": {"keywords": ["貨"]}, "action": "reply_canned", "reply": "SECOND"},
    ]
    d = Policy(cfg(rules=rules2)).decide(ev(), SpyDrafter(), FakeStore())
    assert d.reply_text == "FIRST" and d.model == "rule:first", d.to_dict()
    assert "rule:second" not in d.policy_hits, d.policy_hits

    # 規則 escalate 帶自訂原因
    rules3 = [{"id": "legal", "when": {"keywords": ["提告"]}, "action": "escalate",
               "escalate_reason": "legal_threat"}]
    d = Policy(cfg(rules=rules3)).decide(ev(text="我要提告"), SpyDrafter(), FakeStore())
    assert d.action == "escalate" and d.escalate_reason == "legal_threat", d.to_dict()

    # 未知 action → 保守升級，不得放行
    rules4 = [{"id": "weird", "when": {"keywords": ["貨"]}, "action": "auto_magic"}]
    d = Policy(cfg(rules=rules4)).decide(ev(), SpyDrafter(), FakeStore())
    assert d.action == "escalate", d.to_dict()

    # reply_canned 但 reply 空白 → 升級
    rules5 = [{"id": "empty", "when": {"keywords": ["貨"]}, "action": "reply_canned", "reply": ""}]
    d = Policy(cfg(rules=rules5)).decide(ev(), SpyDrafter(), FakeStore())
    assert d.action == "escalate", d.to_dict()


# --------------------------------------------------------------------------- #
# 6) 低信心升級 / 7) 高信心放行 / 8) 草稿命中敏感詞
# --------------------------------------------------------------------------- #
def t_low_confidence():
    p = Policy(cfg(guard={"min_confidence": 0.65}))
    d = p.decide(ev(), SpyDrafter(Draft(text="也許有吧", confidence=0.4, model="llm:x")), FakeStore())
    assert d.action == "escalate", d.to_dict()
    assert d.escalate_reason == "low_confidence:0.4", d.escalate_reason
    assert d.model == "llm:x", d.model
    assert d.confidence == 0.4, d.confidence

    # 預設 0.65 生效（配置未給 min_confidence）
    d = Policy({}).decide(ev(), SpyDrafter(Draft(text="x", confidence=0.64, model="llm:x")), FakeStore())
    assert d.action == "escalate" and d.escalate_reason == "low_confidence:0.64", d.to_dict()
    d = Policy({}).decide(ev(), SpyDrafter(Draft(text="x", confidence=0.65, model="llm:x")), FakeStore())
    assert d.action == "reply", f"0.65 應剛好放行：{d.to_dict()}"

    # 自訂門檻 0.9
    d = Policy(cfg(guard={"min_confidence": 0.9})).decide(
        ev(), SpyDrafter(Draft(text="x", confidence=0.8, model="llm:x")), FakeStore())
    assert d.action == "escalate", d.to_dict()


def t_high_confidence_pass():
    p = Policy(cfg(guard={"min_confidence": 0.65}, persona={"signature": "— ReplyBridge"}))
    spy = SpyDrafter(Draft(text="有的，現貨充足，可直接下單。", confidence=0.88,
                           model="kb:retrieval", sources=["kb1"]))
    d = p.decide(ev(), spy, FakeStore())
    assert spy.calls == 1
    assert d.action == "reply", d.to_dict()
    assert d.confidence == 0.88, d.confidence
    assert d.model == "kb:retrieval", d.model
    assert d.reason == "ok", d.reason
    assert d.escalate_reason == "", d.escalate_reason
    assert d.reply_text.startswith("有的，現貨充足"), d.reply_text
    assert d.reply_text.rstrip().endswith("— ReplyBridge"), d.reply_text

    # 已含簽名 → 不重複附加
    d = p.decide(ev(message_id="m2"), SpyDrafter(
        Draft(text="有的。\n— ReplyBridge", confidence=0.9, model="llm:x")), FakeStore())
    assert d.reply_text.count("— ReplyBridge") == 1, d.reply_text


def t_draft_blocked():
    g = {"blocked_patterns": [r"保證獲利"], "pii_patterns": [r"[\w.+-]+@[\w-]+\.[\w.]+"]}
    p = Policy(cfg(guard=g))
    d = p.decide(ev(), SpyDrafter(Draft(text="這檔保證獲利 300%", confidence=0.99, model="llm:x")),
                 FakeStore())
    assert d.action == "escalate", d.to_dict()
    assert d.escalate_reason == "draft_blocked", d.escalate_reason
    assert d.confidence == 0.99, "草稿護欄要保留原信心以便稽核"

    d = p.decide(ev(message_id="m2"), SpyDrafter(
        Draft(text="請寄到 a.b@example.com", confidence=0.9, model="llm:x")), FakeStore())
    assert d.action == "escalate" and d.escalate_reason == "draft_blocked", d.to_dict()

    # 草稿護欄先於信心閘門（低信心 + 命中 → draft_blocked，不是 low_confidence）
    d = p.decide(ev(message_id="m3"), SpyDrafter(
        Draft(text="保證獲利", confidence=0.1, model="llm:x")), FakeStore())
    assert d.escalate_reason == "draft_blocked", d.escalate_reason


# --------------------------------------------------------------------------- #
# 9) 過長截斷 + 簽名
# --------------------------------------------------------------------------- #
def t_truncate_and_signature():
    sig = "— ReplyBridge 客服"
    p = Policy(cfg(guard={"max_reply_chars": 60}, persona={"signature": sig}))
    long_text = "甲" * 200
    d = p.decide(ev(), SpyDrafter(Draft(text=long_text, confidence=0.95, model="llm:x")), FakeStore())
    assert d.action == "reply", d.to_dict()
    assert len(d.reply_text) <= 60, f"長度 {len(d.reply_text)} 超過上限：{d.reply_text!r}"
    assert d.reply_text.endswith(sig), d.reply_text
    assert "\u2026" in d.reply_text, f"截斷應補省略號：{d.reply_text!r}"
    assert "truncate:max_reply_chars" in d.policy_hits, d.policy_hits
    assert "persona:signature" in d.policy_hits, d.policy_hits

    # 預設 500：剛好 500 不截斷、501 截斷
    p2 = Policy({})
    d = p2.decide(ev(), SpyDrafter(Draft(text="乙" * 500, confidence=0.9, model="llm:x")), FakeStore())
    assert d.action == "reply" and len(d.reply_text) == 500 and "\u2026" not in d.reply_text, d.reply_text[:5]
    d = p2.decide(ev(message_id="m2"), SpyDrafter(
        Draft(text="乙" * 501, confidence=0.9, model="llm:x")), FakeStore())
    assert len(d.reply_text) == 500 and d.reply_text.endswith("\u2026"), d.reply_text[-3:]

    # 無簽名時不該出現 persona:signature
    d = Policy({}).decide(ev(), SpyDrafter(), FakeStore())
    assert "persona:signature" not in d.policy_hits, d.policy_hits


# --------------------------------------------------------------------------- #
# 10) drafter 拋例外 / 自我放棄 / 回 None
# --------------------------------------------------------------------------- #
def t_drafter_error():
    g = {"blocked_patterns": [r"退款"], "quiet_hours": {"start": 22, "end": 8, "tz_offset_hours": 8}}
    p = Policy(cfg(guard=g))
    spy = SpyDrafter(exc=RuntimeError("provider 503"))
    d = p.decide(ev(created_at="2026-11-03T02:00:00Z"), spy, FakeStore())
    assert spy.calls == 1
    assert d.action == "escalate", d.to_dict()
    assert d.escalate_reason == "drafter_error", d.escalate_reason
    assert "drafter_error" in d.policy_hits, d.policy_hits

    # 多種例外型別都不得外洩
    for exc in (ValueError("bad"), KeyError("k"), TimeoutError("t"), ZeroDivisionError("z")):
        d = p.decide(ev(), SpyDrafter(exc=exc), FakeStore())
        assert d.action == "escalate" and d.escalate_reason == "drafter_error", d.to_dict()

    # drafter 主動放棄
    d = p.decide(ev(), SpyDrafter(Draft(text="", confidence=0.0, model="llm:x", escalate=True,
                                        note="需要真人")), FakeStore())
    assert d.action == "escalate" and d.escalate_reason == "drafter_declined", d.to_dict()

    # drafter 回 None
    d = p.decide(ev(), lambda ev: None, FakeStore())
    assert d.action == "escalate" and d.escalate_reason == "drafter_error", d.to_dict()

    # 完全沒有 draft_fn
    d = p.decide(ev(), None, FakeStore())
    assert d.action == "escalate" and d.escalate_reason == "drafter_error", d.to_dict()


# --------------------------------------------------------------------------- #
# 11) 命中的 ignore 規則
# --------------------------------------------------------------------------- #
def t_ignore_rule():
    rules = [
        {"id": "bot_echo", "when": {"keywords": ["[bot]", "自動回覆"], "platforms": ["line"]},
         "action": "ignore"},
        {"id": "spam", "when": {"keywords": ["免費領取", "加賴"]}, "action": "ignore"},
        {"id": "fallback", "when": {"keywords": ["現貨"]}, "action": "reply_canned", "reply": "有貨"},
    ]
    p = Policy(cfg(rules=rules))
    spy = SpyDrafter()

    # 平台不符（關鍵字命中 line 但事件是 IG）→ 落到 spam 規則
    d = p.decide(ev(text="免費領取 好康"), spy, FakeStore())
    assert d.action == "ignore", d.to_dict()
    assert "rule:spam" in d.policy_hits, d.policy_hits
    assert spy.calls == 0, "ignore 規則不得呼叫 drafter"

    d = p.decide(ev(message_id="m2", platform="line", text="[bot]自動回覆"), FakeStore, FakeStore())
    assert d.action == "ignore", d.to_dict()
    assert "rule:bot_echo" in d.policy_hits, d.policy_hits

    # 沒有規則命中 → 走 drafter（不是 ignore）
    d = p.decide(ev(message_id="m3", text="請問尺寸"), spy, FakeStore())
    assert d.action == "reply" and d.model == "llm:test", d.to_dict()

    # 完全沒有 rules 也照樣走 drafter
    d = Policy({}).decide(ev(message_id="m4", text="請問尺寸"), spy, FakeStore())
    assert d.action == "reply", d.to_dict()


# --------------------------------------------------------------------------- #
# 12) policy_hits 內容正確
# --------------------------------------------------------------------------- #
def t_policy_hits():
    # 純放行（無簽名）：只有信心閘門通過的紀錄
    p = Policy({})
    d = p.decide(ev(), SpyDrafter(Draft(text="好", confidence=0.9, model="llm:x")), FakeStore())
    assert d.policy_hits == ["gate:min_confidence:passed"], d.policy_hits

    # 規則 + 簽名：順序為 rule → persona
    p2 = Policy(cfg(rules=[{"id": "greet", "when": {"keywords": ["貨"]},
                            "action": "reply_canned", "reply": "有的 {{author_name}}"}],
                    persona={"signature": "— RB"}))
    d = p2.decide(ev(), SpyDrafter(), FakeStore())
    assert d.policy_hits == ["rule:greet", "persona:signature"], d.policy_hits
    assert d.reply_text.endswith("— RB"), d.reply_text

    # 無 persona → 不得出現 persona 標記
    d = Policy(cfg(rules=[{"id": "greet", "when": {"keywords": ["貨"]},
                           "action": "reply_canned", "reply": "有的"}])).decide(
        ev(), SpyDrafter(), FakeStore())
    assert d.policy_hits == ["rule:greet"], d.policy_hits

    # 入站護欄：只記命中項
    p3 = Policy(cfg(guard={"blocked_patterns": ["退款"]}))
    d = p3.decide(ev(text="退款"), SpyDrafter(), FakeStore())
    assert d.policy_hits == ["guardrail:blocked:退款"], d.policy_hits

    # 靜默時段：有 quiet_hours 護欄紀錄
    p4 = Policy(cfg(guard={"quiet_hours": {"start": 0, "end": 24, "tz_offset_hours": 0}}))
    d = p4.decide(ev(created_at="2026-11-03T06:00:00Z"), SpyDrafter(), FakeStore())
    assert d.action == "escalate" and d.escalate_reason == "quiet_hours", d.to_dict()
    assert "guardrail:quiet_hours" in d.policy_hits, d.policy_hits

    # 低信心：含 gate 標記且保留 escalate_reason 精度
    d = Policy({}).decide(ev(), SpyDrafter(Draft(text="x", confidence=0.25, model="llm:x")), FakeStore())
    assert "gate:min_confidence" in d.policy_hits, d.policy_hits
    assert d.escalate_reason == "low_confidence:0.25", d.escalate_reason

    # policy_hits 不得重複
    p5 = Policy(cfg(rules=[{"id": "a", "when": {"keywords": ["退款"]},
                            "action": "reply_canned", "reply": "x"}],
                    guard={"blocked_patterns": ["退款"]}))
    d = p5.decide(ev(text="退款"), SpyDrafter(), FakeStore())
    assert len(d.policy_hits) == len(set(d.policy_hits)), d.policy_hits


# --------------------------------------------------------------------------- #
# 額外：整體不 raise（壞 config / 壞 store / 壞事件）
# --------------------------------------------------------------------------- #
def t_never_raises():
    class BoomStore:
        def seen(self, key):
            raise RuntimeError("db down")

        def mark_seen(self, key, meta):
            raise RuntimeError("db down")

        def incr_rate(self, bucket, window_s):
            raise RuntimeError("db down")

    d = Policy(cfg()).decide(ev(), SpyDrafter(), BoomStore())
    assert isinstance(d, Decision), d
    assert d.action in ("reply", "escalate", "ignore"), d.to_dict()
    assert "store:seen_error" in d.policy_hits, d.policy_hits

    # 亂七八糟的 config / 事件
    for conf in (None, {}, {"guardrails": "not-a-dict"}, {"rules": "not-a-list"},
                 {"guardrails": {"quiet_hours": {"start": "abc", "end": None}},
                  "persona": {"signature": 123}}, {"guardrails": {"max_reply_chars": -5}}):
        d = Policy(conf).decide(ev(), SpyDrafter(), FakeStore())
        assert isinstance(d, Decision) and d.action in ("reply", "escalate", "ignore"), \
            f"config={conf} → {d.to_dict()}"

    class WeirdEv:
        platform = "?"
        account_id = "?"
        message_id = "?"
        thread_id = "?"
        kind = "comment"
        author_name = None
        text = None
        created_at = 12345

        def dedupe_key(self):
            raise RuntimeError("bad ev")

        def rate_bucket(self):
            raise RuntimeError("bad ev")

        def to_dict(self):
            raise RuntimeError("bad ev")

    d = Policy(cfg()).decide(WeirdEv(), SpyDrafter(), FakeStore())
    assert isinstance(d, Decision), d

    # store=None 也要能跑
    d = Policy({}).decide(ev(), SpyDrafter(), None)
    assert d.action == "reply", d.to_dict()
    assert Policy({}).decide(None, None, None).action == "escalate"


# --------------------------------------------------------------------------- #
# 執行
# --------------------------------------------------------------------------- #
TESTS = [
    ("1  重複事件不重複回（不再呼叫 draft_fn / incr_rate）", t_dedupe),
    ("2  跨午夜靜默時段（含邊界、非跨午夜、壞時間戳）", t_quiet_cross_midnight),
    ("3  速率超限升級 + 分 thread 計數", t_rate_limited),
    ("4  入站命中敏感詞/PII（含壞 regex）", t_inbound_guardrail),
    ("5  canned 規則命中 + {{author_name}} 替換", t_canned_rule),
    ("6  低信心升級（門檻 0.65 邊界）", t_low_confidence),
    ("7  高信心放行 + 簽名不重複附加", t_high_confidence_pass),
    ("8  草稿命中敏感詞 draft_blocked", t_draft_blocked),
    ("9  答案過長截斷加簽名（長度上限）", t_truncate_and_signature),
    ("10 drafter 拋例外 / 自我放棄 / 回 None", t_drafter_error),
    ("11 命中的 ignore 規則（不呼叫 drafter）", t_ignore_rule),
    ("12 policy_hits 內容與順序正確", t_policy_hits),
    ("13 任何輸入都不 raise（壞 config/store/事件）", t_never_raises),
]


def main() -> int:
    print(f"policy.py = {policy_mod.__file__}")
    print(f"PIPELINE  = {', '.join(policy_mod.PIPELINE)}")
    print(f"contracts = {contracts.__file__}")
    print("-" * 78)
    for name, fn in TESTS:
        check(name, fn)
    failed = 0
    for name, ok, msg in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failed += 1
            print(f"      ↳ {msg}")
    total = len(RESULTS)
    print("-" * 78)
    print(f"{total - failed}/{total} PASS, {failed} FAIL")
    print("RESULT: ALL GREEN" if failed == 0 else "RESULT: FAILURES PRESENT")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
