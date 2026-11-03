#!/usr/bin/env python3
"""ReplyBridge 草稿層測試（W3）。直接執行：python3 tests/test_ai.py

全部離線：provider 一律用假物件，不碰網路。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_RB = os.path.join(_ROOT, "rb")
for p in (_ROOT, _RB):
    if p not in sys.path:
        sys.path.insert(0, p)

import contracts  # noqa: E402
import ai as ai_mod  # noqa: E402
from ai import Drafter, EnvLLMProvider, score, tokenize  # noqa: E402

_PASS = 0
_FAIL = 0
_FAILED_NAMES = []


def check(name, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"PASS  {name}")
    else:
        _FAIL += 1
        _FAILED_NAMES.append(name)
        print(f"FAIL  {name}  {detail}")


def make_ev(text, author_name="Alice", lang=""):
    return contracts.InboundEvent(
        platform="meta_instagram",
        tenant_id="t1",
        account_id="acct",
        kind=contracts.KIND_COMMENT,
        message_id="m1",
        thread_id="th1",
        parent_id="",
        author_id="u1",
        author_name=author_name,
        text=text,
        created_at="2026-11-03T06:20:00Z",
        lang=lang,
    )


KB = [
    {
        "id": "kb-zh-refund",
        "question": "我要怎麼申請退款",
        "answer": "你好 {{author_name}}，請私訊訂單編號，我們會在 3 個工作天內處理退款。",
        "tags": ["退款", "退貨", "refund"],
        "lang": "zh",
    },
    {
        "id": "kb-en-shipping",
        "question": "How long does shipping take?",
        "answer": "Hi {{author_name}}, orders ship within 2 business days and arrive in 3-5 days.",
        "tags": ["shipping", "delivery"],
        "lang": "en",
    },
    {
        "id": "kb-zh-hours",
        "question": "你們的營業時間是幾點",
        "answer": "我們週一到週五 09:00-18:00 營業。",
        "tags": ["營業時間", "客服"],
        "lang": "zh",
    },
]


class FakeProvider:
    """成功 provider。"""

    name = "fake"

    def __init__(self, reply="您好，這是 LLM 產生的回覆。"):
        self.reply = reply
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return self.reply


class BoomProvider:
    """拋例外的 provider。"""

    name = "boom"

    def complete(self, prompt):
        raise RuntimeError("upstream 503")


class EmptyProvider:
    name = "empty"

    def complete(self, prompt):
        return "   "


class NoneProvider:
    name = "nonstr"

    def complete(self, prompt):
        return None


class NoNameProvider:
    def complete(self, prompt):
        return "回覆"


# --------------------------------------------------------------------------- #
# 1. 中文問句命中中文 KB
# --------------------------------------------------------------------------- #
d = Drafter(KB)
draft = d.draft(make_ev("我要怎麼申請退款", author_name="小明"))
check("zh_hit_text", draft.text.startswith("你好 小明，請私訊訂單編號"),
      f"got={draft.text!r}")
check("zh_hit_sources", draft.sources == ["kb-zh-refund"], f"got={draft.sources!r}")
check("zh_hit_model", draft.model == "kb:retrieval", f"got={draft.model}")
check("zh_hit_no_escalate", draft.escalate is False, f"got={draft.escalate}")
check("zh_hit_placeholder_gone", "{{author_name}}" not in draft.text, f"got={draft.text!r}")

# 中文另一次命中（營業時間），確認不是只命中第一筆
draft_h = d.draft(make_ev("請問你們的營業時間是幾點呢"))
check("zh_hit_second_entry", draft_h.sources == ["kb-zh-hours"], f"got={draft_h.sources!r}")

# --------------------------------------------------------------------------- #
# 2. 英文問句命中英文 KB，且不誤命中中文條目
# --------------------------------------------------------------------------- #
draft_e = d.draft(make_ev("How long does shipping take?", author_name="Bob"))
check("en_hit_sources", draft_e.sources == ["kb-en-shipping"], f"got={draft_e.sources!r}")
check("en_hit_text", draft_e.text.startswith("Hi Bob, orders ship within 2 business days"),
      f"got={draft_e.text!r}")
check("en_hit_no_escalate", draft_e.escalate is False, f"got={draft_e.escalate}")

# 大小寫/標點不影響
draft_e2 = d.draft(make_ev("HOW LONG DOES SHIPPING TAKE???"))
check("en_case_punct_insensitive", draft_e2.sources == ["kb-en-shipping"],
      f"got={draft_e2.sources!r}")

# --------------------------------------------------------------------------- #
# 3. 無關問句 → escalate、text 空、note='no_match'
# --------------------------------------------------------------------------- #
draft_u = d.draft(make_ev("比特幣今天的價格走勢如何"))
check("unrelated_escalate", draft_u.escalate is True, f"got={draft_u.escalate}")
check("unrelated_empty_text", draft_u.text == "", f"got={draft_u.text!r}")
check("unrelated_note", draft_u.note == "no_match", f"got={draft_u.note!r}")
check("unrelated_model", draft_u.model == "kb:retrieval", f"got={draft_u.model}")
check("unrelated_confidence_is_score",
      0.0 <= draft_u.confidence < 0.30, f"got={draft_u.confidence}")

# 空字串 / 純標點 / 空 KB 也不得炸
draft_empty = Drafter(KB).draft(make_ev(""))
check("empty_text_escalate", draft_empty.escalate is True and draft_empty.confidence == 0.0,
      f"got={draft_empty.escalate},{draft_empty.confidence}")
draft_nokb = Drafter([]).draft(make_ev("我要怎麼申請退款"))
check("empty_kb_escalate", draft_nokb.escalate is True and draft_nokb.text == "",
      f"got={draft_nokb.escalate},{draft_nokb.text!r}")

# --------------------------------------------------------------------------- #
# 4. min_score 邊界：score == min_score 要命中；score 略高於 min_score 要退回
# --------------------------------------------------------------------------- #
probe = Drafter(KB)
s0, entry0 = probe.best_match("我要怎麼申請退款")
check("boundary_probe_score", entry0 is not None and s0 > 0.0, f"score={s0}")
exact = Drafter(KB, min_score=s0).draft(make_ev("我要怎麼申請退款"))
check("boundary_exact_score_hits", exact.sources == ["kb-zh-refund"] and not exact.escalate,
      f"got={exact.sources!r},{exact.escalate}")
above = Drafter(KB, min_score=s0 + 1e-6).draft(make_ev("我要怎麼申請退款"))
check("boundary_above_score_escalates", above.escalate is True and above.text == "",
      f"got={above.escalate}")
# 高門檻：把 min_score 拉到 1.0 以上效果等同全數退回
strict = Drafter(KB, min_score=0.99).draft(make_ev("How long does shipping take?"))
check("boundary_strict_threshold", strict.escalate is True, f"got={strict.escalate}")
# 預設門檻就是 0.30
check("default_min_score", Drafter(KB).min_score == 0.30 and ai_mod.DEFAULT_MIN_SCORE == 0.30,
      f"got={Drafter(KB).min_score}")

# --------------------------------------------------------------------------- #
# 5. provider 成功路徑
# --------------------------------------------------------------------------- #
fp = FakeProvider("您好，我是 AI 客服，馬上為您處理。")
dp = Drafter(KB, provider=fp)
draft_p = dp.draft(make_ev("我要怎麼申請退款", author_name="小美"))
check("provider_model", draft_p.model == "llm:fake", f"got={draft_p.model}")
check("provider_confidence_080", draft_p.confidence == 0.80, f"got={draft_p.confidence}")
check("provider_text_used", draft_p.text == "您好，我是 AI 客服，馬上為您處理。",
      f"got={draft_p.text!r}")
check("provider_not_escalated", draft_p.escalate is False, f"got={draft_p.escalate}")
check("provider_prompt_has_ev_text", len(fp.prompts) == 1 and "我要怎麼申請退款" in fp.prompts[0],
      f"got={fp.prompts!r}")
check("provider_prompt_has_kb_answer", "請私訊訂單編號" in fp.prompts[0],
      f"got={fp.prompts[:1]!r}")
# provider 未提供 name → model 應為 llm:provider
draft_nn = Drafter(KB, provider=NoNameProvider()).draft(make_ev("How long does shipping take?"))
check("provider_default_name", draft_nn.model == "llm:provider", f"got={draft_nn.model}")

# provider 也用在「KB 無匹配」的情境（此時仍需提供 prompt，且 sources 為空）
fp2 = FakeProvider("我們已收到您的問題，稍後回覆。")
draft_p2 = Drafter(KB, provider=fp2).draft(make_ev("我想問股票的事情"))
check("provider_without_kb_hit", draft_p2.model == "llm:fake" and draft_p2.confidence == 0.80
      and draft_p2.sources == [], f"got={draft_p2.model},{draft_p2.confidence},{draft_p2.sources!r}")

# --------------------------------------------------------------------------- #
# 6. provider 拋例外 → 安靜退回檢索（不得 raise）
# --------------------------------------------------------------------------- #
try:
    draft_b = Drafter(KB, provider=BoomProvider()).draft(make_ev("我要怎麼申請退款"))
    raised = None
except Exception as exc:  # noqa: BLE001
    raised = exc
    draft_b = None
check("provider_exception_not_raised", raised is None, f"raised={raised!r}")
if draft_b is not None:
    baseline = Drafter(KB).draft(make_ev("我要怎麼申請退款"))
    check("provider_exception_falls_back", draft_b.model == "kb:retrieval",
          f"got={draft_b.model}")
    check("provider_exception_same_as_retrieval",
          (draft_b.text, draft_b.confidence, draft_b.sources, draft_b.escalate, draft_b.note)
          == (baseline.text, baseline.confidence, baseline.sources, baseline.escalate, baseline.note),
          f"got={(draft_b.text, draft_b.confidence, draft_b.sources)}")
    check("provider_exception_confidence_not_080", draft_b.confidence != 0.80,
          f"got={draft_b.confidence}")

# 例外且 KB 無匹配 → 應 escalate，confidence 用檢索分數
try:
    draft_b2 = Drafter(KB, provider=BoomProvider()).draft(make_ev("比特幣今天的價格走勢如何"))
    check("provider_exception_nomatch_escalate", draft_b2.escalate is True
          and draft_b2.note == "no_match", f"got={draft_b2.escalate},{draft_b2.note}")
except Exception as exc:  # noqa: BLE001
    check("provider_exception_nomatch_escalate", False, f"raised={exc!r}")

# --------------------------------------------------------------------------- #
# 7. provider 回空字串 / 非字串 → 也退回
# --------------------------------------------------------------------------- #
try:
    draft_e3 = Drafter(KB, provider=EmptyProvider()).draft(make_ev("我要怎麼申請退款"))
    check("provider_empty_falls_back", draft_e3.model == "kb:retrieval"
          and draft_e3.text.startswith("你好 Alice"), f"got={draft_e3.model},{draft_e3.text!r}")
    check("provider_empty_confidence_not_080", draft_e3.confidence != 0.80,
          f"got={draft_e3.confidence}")
except Exception as exc:  # noqa: BLE001
    check("provider_empty_falls_back", False, f"raised={exc!r}")

try:
    draft_n = Drafter(KB, provider=NoneProvider()).draft(make_ev("我要怎麼申請退款"))
    check("provider_nonstring_falls_back", draft_n.model == "kb:retrieval",
          f"got={draft_n.model}")
except Exception as exc:  # noqa: BLE001
    check("provider_nonstring_falls_back", False, f"raised={exc!r}")

# --------------------------------------------------------------------------- #
# 8. confidence 一律落在 0..0.95
# --------------------------------------------------------------------------- #
cases = [
    ("我要怎麼申請退款", Drafter(KB)),
    ("How long does shipping take?", Drafter(KB)),
    ("比特幣今天的價格走勢如何", Drafter(KB)),
    ("我要怎麼申請退款", Drafter(KB, provider=FakeProvider())),
    ("我要怎麼申請退款", Drafter(KB, provider=BoomProvider())),
    ("我要怎麼申請退款", Drafter(KB, min_score=0.0)),
    ("營業時間", Drafter(KB, min_score=0.0)),
    ("", Drafter(KB, min_score=0.0)),
]
ok_range = True
detail = []
for text, dr in cases:
    dk = dr.draft(make_ev(text))
    detail.append(f"{text[:8]!r}={dk.confidence:.4f}")
    if not (0.0 <= dk.confidence <= 0.95):
        ok_range = False
check("confidence_in_range", ok_range, " ".join(detail))

# 完整命中時 confidence 不超過 0.95（min(0.95, 0.55+s*0.5) 的上界）
full = Drafter([{"id": "x", "question": "退款", "answer": "ok", "tags": [], "lang": "zh"}],
               min_score=0.0).draft(make_ev("退款"))
check("confidence_cap_095", full.confidence <= 0.95 and full.confidence > 0.55,
      f"got={full.confidence}")

# --------------------------------------------------------------------------- #
# 9. EnvLLMProvider 行為（不連網）
# --------------------------------------------------------------------------- #
try:
    EnvLLMProvider(env={})
    check("env_provider_unconfigured_raises", False, "no RuntimeError")
except RuntimeError as exc:
    check("env_provider_unconfigured_raises", str(exc) == "provider not configured",
          f"got={exc!r}")
except Exception as exc:  # noqa: BLE001
    check("env_provider_unconfigured_raises", False, f"wrong exc={exc!r}")

prov = EnvLLMProvider(env={"REPLYBRIDGE_LLM_URL": "http://127.0.0.1:1/v1/complete"},
                      transport=lambda prompt: '{"choices": [{"text": "OK 由假 transport 產生"}]}')
check("env_provider_name_default", prov.name == "envllm", f"got={prov.name}")
check("env_provider_complete", prov.complete("hi") == "OK 由假 transport 產生",
      f"got={prov.complete('hi')!r}")

# EnvLLMProvider 經 Drafter 走成功路徑（transport 注入，離線）
draft_env = Drafter(KB, provider=prov).draft(make_ev("我要怎麼申請退款"))
check("env_provider_via_drafter", draft_env.model == "llm:envllm"
      and draft_env.confidence == 0.80 and draft_env.text == "OK 由假 transport 產生",
      f"got={draft_env.model},{draft_env.confidence},{draft_env.text!r}")

# transport 拋錯 → Drafter 仍退回（不 raise）
prov_boom = EnvLLMProvider(env={"REPLYBRIDGE_LLM_URL": "http://127.0.0.1:1/x"},
                           transport=lambda prompt: (_ for _ in ()).throw(OSError("down")))
draft_eb = Drafter(KB, provider=prov_boom).draft(make_ev("我要怎麼申請退款"))
check("env_provider_transport_error_falls_back", draft_eb.model == "kb:retrieval",
      f"got={draft_eb.model}")

# --------------------------------------------------------------------------- #
# 10. 計分/斷詞基本性質
# --------------------------------------------------------------------------- #
check("tokenize_zh_bigram", tokenize("我要退款") == ["我要", "要退", "退款"],
      f"got={tokenize('我要退款')!r}")
check("tokenize_en_lower_split", tokenize("How do I RESET?") == ["how", "do", "i", "reset"],
      f"got={tokenize('How do I RESET?')!r}")
check("tokenize_mixed", tokenize("退款 refund") == ["退款", "refund"],
      f"got={tokenize('退款 refund')!r}")
check("score_self_is_one", abs(score(tokenize("退款"), tokenize("退款")) - 1.0) < 1e-12,
      f"got={score(tokenize('退款'), tokenize('退款'))}")
check("score_disjoint_zero", score(tokenize("退款"), tokenize("營業時間")) == 0.0,
      f"got={score(tokenize('退款'), tokenize('營業時間'))}")

# --------------------------------------------------------------------------- #
print()
print(f"{_PASS} passed, {_FAIL} failed")
if _FAIL:
    print("failed: " + ", ".join(_FAILED_NAMES))
    print("RESULT: FAIL")
    sys.exit(1)
print("RESULT: PASS")
