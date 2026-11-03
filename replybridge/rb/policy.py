"""ReplyBridge W2

 +  +  `contracts.Decision`
 DB store /

`Policy(config).decide(ev, draft_fn, store) -> Decision`
 module  `PIPELINE` bug

    1 dedupe       store.seen()  → ignore('duplicate') draft_fn / incr_rate
    2 quiet_hours  → escalate('quiet_hours')
    3 rate          thread  → escalate('rate_limited')
    4 inbound       blocked_patterns / pii_patterns → escalate('guardrail:<pattern>')
    5 rules        reply_canned / escalate / ignore
    6 drafter      draft_fn(ev)draft.escalate → escalate('drafter_declined')
    7 draft_guard   blocked/pii → escalate('draft_blocked')
    8 confidence   draft.confidence < min_confidence → escalate('low_confidence:<conf>')
    9 pass          +  → reply

 `decide()`  raise draft_fn store  config
 escalate('internal_error') 

 stdlibre / dataclasses / json / string re datetime
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

try:
    from . import contracts
except ImportError:
    import contracts

__all__ = ["Policy", "PIPELINE", "DEFAULT_MIN_CONFIDENCE", "DEFAULT_MAX_REPLY_CHARS",
           "DEFAULT_RATE_LIMIT", "RATE_WINDOW_S", "ELLIPSIS"]

PIPELINE = (
    "dedupe", "quiet_hours", "rate", "inbound_guardrails", "rules",
    "drafter", "draft_guardrails", "confidence_gate", "pass",
)

DEFAULT_MIN_CONFIDENCE = 0.65
DEFAULT_MAX_REPLY_CHARS = 500
DEFAULT_RATE_LIMIT = 6
RATE_WINDOW_S = 3600
ELLIPSIS = "\u2026"             # '…'

_TS_RE = re.compile(
    r"^\s*(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s*"
    r"(Z|z|[+-]\d{2}:?\d{2})?\s*$"
)


# --------------------------------------------------------------------------- #
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
    """ 22 / 22.5 / "22:30" / "8"  None"""
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
    """ 24 / "24:00" =1440 _hours_to_minutes"""
    try:
        if isinstance(value, str) and value.strip() in ("24", "24:00", "24.0"):
            return 1440
        if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) == 24.0:
            return 1440
    except (TypeError, ValueError):
        pass
    return _hours_to_minutes(value)


def _utc_minutes_of_day(ts) -> "int | None":
    """ISO8601 → UTC 0..1439"""
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
    """[(,  regex)] regex  raise"""
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
        except Exception:
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
# --------------------------------------------------------------------------- #
@dataclass
class _Trace:
    """ policy_hits return """
    hits: list = field(default_factory=list)

    def add(self, *items) -> "_Trace":
        for it in items:
            if it:
                self.hits.append(it)
        return self

    def freeze(self) -> list:
        return _dedupe(self.hits)


class Policy:
    """decide """

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
    # ------------------------------------------------------------------ #
    def decide(self, ev, draft_fn=None, store=None) -> contracts.Decision:
        trace = _Trace()
        try:
            return self._decide(ev, draft_fn, store, trace)
        except Exception as exc:
            trace.add("internal_error")
            return self._escalate("internal_error", trace,
                                  model=f"error:{type(exc).__name__}")

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    def _decide(self, ev, draft_fn, store, trace: _Trace) -> contracts.Decision:
        key = self._dedupe_key(ev)
        if self._store_seen(store, key, trace):
            trace.add("dedupe")
            return contracts.Decision(action="ignore", reason="duplicate",
                                      policy_hits=trace.freeze())
        self._store_mark_seen(store, key, ev, trace)

        quiet, quiet_note = self._in_quiet_hours(ev)
        if quiet_note:
            trace.add(quiet_note)
        if quiet:
            trace.add("guardrail:quiet_hours")
            return self._escalate("quiet_hours", trace)

        used = self._incr_rate(store, ev, trace)
        if used is not None and used > self._rate_limit:
            trace.add("guardrail:rate_limited")
            return self._escalate("rate_limited", trace)

        text = self._ev_text(ev)
        hit = _first_match(self.blocked_patterns, text)
        if hit is not None:
            trace.add(f"guardrail:blocked:{hit}")
            return self._escalate(f"guardrail:{hit}", trace)
        hit = _first_match(self.pii_patterns, text)
        if hit is not None:
            trace.add(f"guardrail:pii:{hit}")
            return self._escalate(f"guardrail:{hit}", trace)

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
            trace.add(f"rule:{rid}:unknown_action")
            return self._escalate(f"rule:{rid}:unknown_action", trace, model=f"rule:{rid}")

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

        if draft_conf < self._min_confidence:
            trace.add("gate:min_confidence")
            return self._escalate(f"low_confidence:{draft_conf}", trace,
                                  confidence=draft_conf, model=draft_model)
        trace.add("gate:min_confidence:passed")

        final, _ = self._render_output(draft_text, trace)
        if not final.strip():
            trace.add("gate:empty_reply")
            return self._escalate("empty_reply", trace,
                                  confidence=draft_conf, model=draft_model)
        return contracts.Decision(
            action="reply", reply_text=final, confidence=draft_conf,
            model=draft_model, policy_hits=trace.freeze(), reason="ok")

    # ------------------------------------------------------------------ #
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
        """ (,  None)"""
        qh = self.guard.get("quiet_hours")
        if not isinstance(qh, dict) or not qh:
            return False, None
        start = _endpoint_minutes(qh.get("start"))
        end = _endpoint_minutes(qh.get("end"))
        if start is None or end is None:
            return False, "guardrail:quiet_hours:malformed"
        if start >= 1440:
            start = 0
        offset_min = int(round(_to_float(qh.get("tz_offset_hours"), 0.0) * 60))
        tod = _utc_minutes_of_day(getattr(ev, "created_at", ""))
        if tod is None:
            return False, "guardrail:quiet_hours:unparsable"
        local = (tod + offset_min) % 1440
        if end >= 1440:
            inside = local >= start
        elif start < end:
            inside = start <= local < end
        elif start > end:
            inside = local >= start or local < end
        else:
            inside = False
        return inside, None

    @staticmethod
    def _ev_text(ev) -> str:
        text = getattr(ev, "text", "")
        if isinstance(text, str):
            return text
        return "" if text is None else str(text)

    def _rule_matches(self, rule: dict, ev) -> bool:
        """platforms / kinds keywords  match  any|all

         platforms/kinds  match kind
         'any' platforms 
        platforms 
          *  platforms → 
          *  kinds    →  kind 
          * keywordsmatch='any''all' 
          *  →  catch-all
         case-insensitive 
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
        """{{author_name}}"""
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
        """ max_reply_chars '…' persona 

        
         (, )
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
            budget = 1
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
# --------------------------------------------------------------------------- #
def decide(config: dict, ev, draft_fn=None, store=None) -> contracts.Decision:
    return Policy(config).decide(ev, draft_fn, store)
