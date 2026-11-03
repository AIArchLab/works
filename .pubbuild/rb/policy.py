"""ReplyBridge 政策層（W2）。

唯一職責：把一個入站事件 + 草稿函式 + 儲存層，變成一個 `contracts.Decision`。
不碰網路、不寫 DB（只透過注入的 store 做去重/速率）、不做平台差異。

`Policy(config).decide(ev, draft_fn, store) -> Decision`
判定的順序即規格（見 module 常數 `PIPELINE`），順序錯就是 bug：

    1 dedupe       store.seen() 為真 → ignore('duplicate')，且不再呼叫 draft_fn / incr_rate
    2 quiet_hours  靜默時段（支援跨午夜）→ escalate('quiet_hours')
    3 rate         同 thread 每小時回覆數超限 → escalate('rate_limited')
    4 inbound      入站文字命中 blocked_patterns / pii_patterns → escalate('guardrail:<pattern>')
    5 rules        第一條命中的規則決定（reply_canned / escalate / ignore）
    6 drafter      draft_fn(ev)；draft.escalate → escalate('drafter_declined')
    7 draft_guard  草稿文字命中 blocked/pii → escalate('draft_blocked')
    8 confidence   draft.confidence < min_confidence → escalate('low_confidence:<conf>')
    9 pass         截斷 + 簽名 → reply

本模組保證 `decide()` 在任何輸入下都不 raise（含 draft_fn 例外、store 例外、壞 config），
最壞情況回傳 escalate('internal_error') 交人工處理。

只依賴 stdlib：re / dataclasses / json / string（因此時間解析用 re，不用 datetime）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

try:                                  # 套件內（python3 -m rb.server / e2e）
    from . import contracts
except ImportError:                   # 直接執行 / 測試把 rb/ 放進 sys.path 時
    import contracts

__all__ = ["Policy", "PIPELINE", "DEFAULT_MIN_CONFIDENCE", "DEFAULT_MAX_REPLY_CHARS",
           "DEFAULT_RATE_LIMIT", "RATE_WINDOW_S", "ELLIPSIS"]

# 判定順序（稽核/文件用；也是實作順序的宣告）
PIPELINE = (
    "dedupe", "quiet_hours", "rate", "inbound_guardrails", "rules",
    "drafter", "draft_guardrails", "confidence_gate", "pass",
)

DEFAULT_MIN_CONFIDENCE = 0.65
DEFAULT_MAX_REPLY_CHARS = 500
DEFAULT_RATE_LIMIT = 6          # 每 thread 每小時最多自動回覆數
RATE_WINDOW_S = 3600
ELLIPSIS = "\u2026"             # '…'

# ISO8601：2026-11-03T06:20:00Z / 2026-11-03T14:20:00+08:00 / 空格分隔
_TS_RE = re.compile(
    r"^\s*(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s*"
    r"(Z|z|[+-]\d{2}:?\d{2})?\s*$"
)


# --------------------------------------------------------------------------- #
# 小工具（純函式，全部不得 raise）
# --------------------------------------------------------------------------- #
def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _to_float(value, default: float) -> float:
    try:
        if isinstance(value, bool):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _hours_to_minutes(value):
    """把 22 / 22.5 / "22:30" / "8" 轉成當日分鐘數；無法解析回 None。"""
    try:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            if ":" in raw:
                hh, _, mm = raw.partition(":")
                hh_f, mm_f = float(hh), float(mm)
                if not (0 <= hh_f < 24 and 0 <= mm_f < 60):
                    return None
                return int(round(hh_f * 60 + mm_f)) % 1440
            value = float(raw)
        num = float(value)
        if num != num:          # NaN
            return None
        return int(round(num * 60)) % 1440
    except (TypeError, ValueError):
        return None


def _endpoint_minutes(value):
    """靜默時段端點解析：允許 24 / "24:00" 代表當日結束（=1440）。其餘同 _hours_to_minutes。"""
    try:
        if isinstance(value, str) and value.strip() in ("24", "24:00", "24.0"):
            return 1440
        if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) == 24.0:
            return 1440
    except (TypeError, ValueError):
        pass
    return _hours_to_minutes(value)


def _utc_minutes_of_day(ts) -> "int | None":
    """ISO8601 → UTC 當日分鐘數（0..1439）。只算時分，不做曆日運算。"""
    if not isinstance(ts, str):
        return None
    m = _TS_RE.match(ts)
    if not m:
        return None
    try:
        hh = int(m.group(4))
        mm = int(m.group(5))
        off = m.group(7)
        tz_min = 0
        if off and off.upper() != "Z":
            sign = 1 if off[0] == "+" else -1
            body = off[1:].replace(":", "")
            tz_min = sign * (int(body[0:2]) * 60 + int(body[2:4] or "0"))
        if not (0 <= hh < 24 and 0 <= mm < 60):
            return None
        return int(hh * 60 + mm - tz_min) % 1440
    except (TypeError, ValueError, IndexError):
        return None


def _compile_patterns(raw) -> list:
    """[(原文, 已編譯 regex)]；壞 regex 跳過但不 raise。"""
    out = []
    for item in _as_list(raw):
        if not isinstance(item, str) or not item:
            continue
        try:
            out.append((item, re.compile(item, re.IGNORECASE | re.UNICODE)))
        except re.error:
            continue
    return out


def _first_match(patterns, text) -> "str | None":
    if not text:
        return None
    for raw, rx in patterns:
        try:
            if rx.search(text):
                return raw
        except Exception:               # 防禦性：regex 引擎異常不得外洩
            continue
    return None


def _dedupe(items) -> list:
    seen, out = set(), []
    for it in items:
        key = it if isinstance(it, str) else repr(it)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


# --------------------------------------------------------------------------- #
# 決策輔助：可攜帶部分狀態的建構器
# --------------------------------------------------------------------------- #
@dataclass
class _Trace:
    """累積 policy_hits，避免每個 return 點重複貼清單。"""
    hits: list = field(default_factory=list)

    def add(self, *items) -> "_Trace":
        for it in items:
            if it:
                self.hits.append(it)
        return self

    def freeze(self) -> list:
        return _dedupe(self.hits)


class Policy:
    """政策性決策引擎。執行緒安全（decide 內無共享可變狀態）。"""

    def __init__(self, config: "dict | None" = None):
        self.config = _as_dict(config)
        self.guard = _as_dict(self.config.get("guardrails"))
        self.persona = _as_dict(self.config.get("persona"))
        self.rules = [r for r in _as_list(self.config.get("rules")) if isinstance(r, dict)]
        self.blocked_patterns = _compile_patterns(self.guard.get("blocked_patterns"))
        self.pii_patterns = _compile_patterns(self.guard.get("pii_patterns"))
        self._min_confidence = _to_float(
            self.guard.get("min_confidence"), DEFAULT_MIN_CONFIDENCE)
        self._max_reply_chars = _to_int(
            self.guard.get("max_reply_chars"), DEFAULT_MAX_REPLY_CHARS)
        if self._max_reply_chars < 1:
            self._max_reply_chars = 1
        self._rate_limit = _to_int(
            self.guard.get("max_replies_per_thread_per_hour"), DEFAULT_RATE_LIMIT)
        self._signature = self.persona.get("signature")
        if not isinstance(self._signature, str):
            self._signature = ""

    # ------------------------------------------------------------------ #
    # 對外唯一入口
    # ------------------------------------------------------------------ #
    def decide(self, ev, draft_fn=None, store=None) -> contracts.Decision:
        trace = _Trace()
        try:
            return self._decide(ev, draft_fn, store, trace)
        except Exception as exc:                       # 任何情況都不得 raise
            trace.add("internal_error")
            return self._escalate("internal_error", trace,
                                  model=f"error:{type(exc).__name__}")

    # ------------------------------------------------------------------ #
    # 主流程（順序即規格）
    # ------------------------------------------------------------------ #
    def _decide(self, ev, draft_fn, store, trace: _Trace) -> contracts.Decision:
        # ---- 1) 去重 -----------------------------------------------------
        key = self._dedupe_key(ev)
        if self._store_seen(store, key, trace):
            trace.add("dedupe")
            return contracts.Decision(action="ignore", reason="duplicate",
                                      policy_hits=trace.freeze())
        self._store_mark_seen(store, key, ev, trace)

        # ---- 2) 靜默時段 -------------------------------------------------
        quiet, quiet_note = self._in_quiet_hours(ev)
        if quiet_note:
            trace.add(quiet_note)
        if quiet:
            trace.add("guardrail:quiet_hours")
            return self._escalate("quiet_hours", trace)

        # ---- 3) 速率 -----------------------------------------------------
        used = self._incr_rate(store, ev, trace)
        if used is not None and used > self._rate_limit:
            trace.add("guardrail:rate_limited")
            return self._escalate("rate_limited", trace)

        # ---- 4) 入站護欄 -------------------------------------------------
        text = self._ev_text(ev)
        hit = _first_match(self.blocked_patterns, text)
        if hit is not None:
            trace.add(f"guardrail:blocked:{hit}")
            return self._escalate(f"guardrail:{hit}", trace)
        hit = _first_match(self.pii_patterns, text)
        if hit is not None:
            trace.add(f"guardrail:pii:{hit}")
            return self._escalate(f"guardrail:{hit}", trace)

        # ---- 5) 規則 -----------------------------------------------------
        for rule in self.rules:
            try:
                matched = self._rule_matches(rule, ev)
            except Exception:
                matched = False
            if not matched:
                continue
            rid = str(rule.get("id") or "unnamed")
            trace.add(f"rule:{rid}")
            action = str(rule.get("action") or "escalate").strip().lower()
            if action == "ignore":
                return contracts.Decision(
                    action="ignore", policy_hits=trace.freeze(),
                    reason=str(rule.get("reason") or f"rule:{rid}"), model=f"rule:{rid}")
            if action == "escalate":
                er = str(rule.get("escalate_reason") or f"rule:{rid}")
                return self._escalate(er, trace, model=f"rule:{rid}")
            if action == "reply_canned":
                canned = rule.get("reply")
                if not isinstance(canned, str) or not canned.strip():
                    trace.add("rule:empty_reply")
                    return self._escalate(f"rule:{rid}:empty_reply", trace, model=f"rule:{rid}")
                body = self._render_vars(canned, ev)
                final, _ = self._render_output(body, trace)
                return contracts.Decision(
                    action="reply", reply_text=final, confidence=0.99,
                    model=f"rule:{rid}", policy_hits=trace.freeze(), reason="ok")
            # 未知 action：保守升級，不得靜默放行
            trace.add(f"rule:{rid}:unknown_action")
            return self._escalate(f"rule:{rid}:unknown_action", trace, model=f"rule:{rid}")

        # ---- 6) 呼叫 drafter --------------------------------------------
        draft = None
        if draft_fn is not None:
            try:
                draft = draft_fn(ev)
            except Exception as exc:
                trace.add("drafter_error")
                return self._escalate("drafter_error", trace,
                                      model=f"error:{type(exc).__name__}")
        if draft is None:
            trace.add("drafter_error")
            return self._escalate("drafter_error", trace)
        draft_text = getattr(draft, "text", "")
        if not isinstance(draft_text, str):
            draft_text = "" if draft_text is None else str(draft_text)
        draft_conf = _to_float(getattr(draft, "confidence", 0.0), 0.0)
        draft_model = getattr(draft, "model", "")
        draft_model = draft_model if isinstance(draft_model, str) else str(draft_model)

        if bool(getattr(draft, "escalate", False)):
            trace.add("drafter_declined")
            return self._escalate("drafter_declined", trace,
                                  confidence=draft_conf, model=draft_model)

        # ---- 7) 草稿護欄 -------------------------------------------------
        hit = _first_match(self.blocked_patterns, draft_text)
        if hit is not None:
            trace.add(f"guardrail:draft_blocked:{hit}")
            return self._escalate("draft_blocked", trace,
                                  confidence=draft_conf, model=draft_model)
        hit = _first_match(self.pii_patterns, draft_text)
        if hit is not None:
            trace.add(f"guardrail:draft_pii:{hit}")
            return self._escalate("draft_blocked", trace,
                                  confidence=draft_conf, model=draft_model)

        # ---- 8) 信心閘門 -------------------------------------------------
        if draft_conf < self._min_confidence:
            trace.add("gate:min_confidence")
            return self._escalate(f"low_confidence:{draft_conf}", trace,
                                  confidence=draft_conf, model=draft_model)
        trace.add("gate:min_confidence:passed")

        # ---- 9) 放行：截斷 + 簽名 ----------------------------------------
        final, _ = self._render_output(draft_text, trace)
        if not final.strip():
            trace.add("gate:empty_reply")
            return self._escalate("empty_reply", trace,
                                  confidence=draft_conf, model=draft_model)
        return contracts.Decision(
            action="reply", reply_text=final, confidence=draft_conf,
            model=draft_model, policy_hits=trace.freeze(), reason="ok")

    # ------------------------------------------------------------------ #
    # 步驟實作
    # ------------------------------------------------------------------ #
    @staticmethod
    def _escalate(reason: str, trace: _Trace, confidence: float = 0.0,
                  model: str = "") -> contracts.Decision:
        return contracts.Decision(action="escalate", escalate_reason=str(reason),
                                  confidence=confidence, model=model,
                                  policy_hits=trace.freeze(), reason="escalate")

    @staticmethod
    def _dedupe_key(ev) -> str:
        try:
            return str(ev.dedupe_key())
        except Exception:
            return "{}:{}:{}".format(getattr(ev, "platform", ""),
                                     getattr(ev, "account_id", ""),
                                     getattr(ev, "message_id", ""))

    def _store_seen(self, store, key: str, trace: _Trace) -> bool:
        if store is None:
            return False
        try:
            return bool(store.seen(key))
        except Exception:
            # 去重查詢失敗：不得因此 raise；記錄並繼續（由下游速率/閘門兜底）
            trace.add("store:seen_error")
            return False

    def _store_mark_seen(self, store, key: str, ev, trace: _Trace) -> None:
        if store is None:
            return
        try:
            meta = ev.to_dict() if hasattr(ev, "to_dict") else {"key": key}
            store.mark_seen(key, meta)
        except Exception:
            trace.add("store:mark_seen_error")

    def _incr_rate(self, store, ev, trace: _Trace):
        if store is None:
            return None
        try:
            bucket = str(ev.rate_bucket())
        except Exception:
            bucket = "{}:{}:{}".format(getattr(ev, "platform", ""),
                                       getattr(ev, "account_id", ""),
                                       getattr(ev, "thread_id", ""))
        try:
            return _to_int(store.incr_rate(bucket, RATE_WINDOW_S), 0)
        except Exception:
            trace.add("store:rate_error")
            return None

    def _in_quiet_hours(self, ev):
        """回傳 (是否靜默, 稽核備註或 None)。"""
        qh = self.guard.get("quiet_hours")
        if not isinstance(qh, dict) or not qh:
            return False, None
        start = _endpoint_minutes(qh.get("start"))
        end = _endpoint_minutes(qh.get("end"))
        if start is None or end is None:
            return False, "guardrail:quiet_hours:malformed"
        if start >= 1440:
            start = 0                         # start=24 等同 00:00
        offset_min = int(round(_to_float(qh.get("tz_offset_hours"), 0.0) * 60))
        tod = _utc_minutes_of_day(getattr(ev, "created_at", ""))
        if tod is None:
            return False, "guardrail:quiet_hours:unparsable"
        local = (tod + offset_min) % 1440
        if end >= 1440:                       # 例 00:00–24:00 全天
            inside = local >= start
        elif start < end:
            inside = start <= local < end
        elif start > end:                     # 跨午夜，例 22:00 → 08:00
            inside = local >= start or local < end
        else:                                 # start == end：空區間
            inside = False
        return inside, None

    @staticmethod
    def _ev_text(ev) -> str:
        text = getattr(ev, "text", "")
        if isinstance(text, str):
            return text
        return "" if text is None else str(text)

    def _rule_matches(self, rule: dict, ev) -> bool:
        """規則比對：platforms / kinds 是「硬過濾」，keywords 由 match 決定 any|all。

        為什麼 platforms/kinds 不參與 match：事件只有一個平台、一種 kind，
        若讓它們參與 'any'，任何列了 platforms 的規則都會對該平台所有事件成立，
        platforms 就失去意義（也等於放行未預期的自動回覆）。因此：
          * 有列 platforms → 事件平台必須在其中，否則規則不成立；
          * 有列 kinds    → 事件 kind 必須在其中，否則不成立；
          * keywords：match='any'（預設）任一關鍵字出現即成立；'all' 全部出現才成立；
          * 三者皆未列 → 視為 catch-all，成立。
        關鍵字比對為 case-insensitive 子字串比對。
        """
        when = rule.get("when")
        if when is None:
            return True
        when = _as_dict(when)
        mode = str(when.get("match") or "any").strip().lower()

        platforms = [str(p) for p in _as_list(when.get("platforms")) if p]
        if platforms and str(getattr(ev, "platform", "")) not in platforms:
            return False

        kinds = [str(k) for k in _as_list(when.get("kinds")) if k]
        if kinds and str(getattr(ev, "kind", "")) not in kinds:
            return False

        keywords = [k for k in _as_list(when.get("keywords")) if isinstance(k, str) and k]
        if not keywords:
            return True
        text = self._ev_text(ev).lower()
        if mode == "all":
            return all(k.lower() in text for k in keywords)
        return any(k.lower() in text for k in keywords)

    @staticmethod
    def _render_vars(template: str, ev) -> str:
        """規則模板變數替換（目前規格：{{author_name}}）。未知變數原樣保留。"""
        author = getattr(ev, "author_name", "") or ""
        author = author if isinstance(author, str) else str(author)
        out = template
        try:
            out = out.replace("{{author_name}}", author)
            out = out.replace("{{ author_name }}", author)
        except Exception:
            return template
        return out

    def _ends_with_signature(self, text: str, sig: str) -> bool:
        if not sig:
            return True
        return text.rstrip().endswith(sig.rstrip())

    def _render_output(self, text: str, trace: _Trace):
        """截斷到 max_reply_chars（截斷時補 '…'）並在文末附上 persona 簽名。

        簽名佔用的字數會先從預算中扣除，確保最終回覆長度不超過上限。
        回傳 (最終文字, 是否截斷)。
        """
        limit = self._max_reply_chars
        sig = (self._signature or "").strip()
        truncated = False

        if not sig or self._ends_with_signature(text, sig):
            if len(text) > limit:
                text = self._cut(text, limit)
                truncated = True
            if truncated:
                trace.add("truncate:max_reply_chars")
            return text, truncated

        sep = "" if (not text or text.endswith("\n")) else "\n"
        budget = limit - len(sep) - len(sig)
        if budget < 1:
            budget = 1                      # 上限過小：至少保留 '…'
        body = text
        if len(body) > budget:
            body = self._cut(body, budget)
            truncated = True
            trace.add("truncate:max_reply_chars")
        combined = (body + sep + sig) if body else sig
        trace.add("persona:signature")
        return combined, truncated

    @staticmethod
    def _cut(text: str, budget: int) -> str:
        if budget <= 0:
            return ""
        if budget == 1:
            return ELLIPSIS
        return text[: budget - 1].rstrip() + ELLIPSIS


# --------------------------------------------------------------------------- #
# 便利函式（非契約；讓 core/E2E 可以一行呼叫）
# --------------------------------------------------------------------------- #
def decide(config: dict, ev, draft_fn=None, store=None) -> contracts.Decision:
    return Policy(config).decide(ev, draft_fn, store)
