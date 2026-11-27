import hashlib
from .rules import RuleEngine
from .registry import Registry
from .classifier import NullClassifier
from .decisionlog import DecisionLog

class Advisor:
    def __init__(self, rules="rules.yaml", models="models.yaml", log="decisions.jsonl", classifier=None):
        self.rules = RuleEngine(rules)
        self.reg = Registry(models, self.rules.tiers)
        # The "below threshold -> strongest model" guarantee is enforced here.
        if self.rules.default != self.reg.strongest():
            raise ValueError("default_model must be the strongest tier "
                             f"({self.reg.strongest()!r}), got {self.rules.default!r}")
        self.rules_version = self.rules.version   # same bytes that were parsed
        self.clf = classifier or NullClassifier()
        self.log = DecisionLog(log)

    def decide(self, task_id, step_type, text="", tokens=0, phase="entry",
               current_tier=None, struggle=None):
        """phase: 'entry' (classify) or 'reask' (struggle triggered; upgrade only).
        The caller classifies once; the advisor only clamps upward."""
        if current_tier is not None and current_tier not in self.reg.tiers:
            raise ValueError(f"unknown current_tier {current_tier!r}")
        conf, matched = None, None
        tier, rule = self.rules.match(step_type, text, tokens)
        if tier:
            source, matched = "rule", rule
        else:
            c_tier, conf = self.clf.classify(text)
            if c_tier in self.reg.tiers and conf >= self.rules.threshold:
                tier, source = c_tier, "classifier"
            else:
                tier, source = self.reg.strongest(), "default"

        clamp = "none"
        if phase == "reask":
            # Upgrade only. Struggling means: go at least one tier above current.
            cur = self.reg.rank(current_tier) if current_tier else -1
            nxt = min(cur + 1, len(self.reg.tiers) - 1)
            if self.reg.rank(tier) <= cur:
                tier = self.reg.tiers[nxt]
                # At the top tier there is nowhere to go: say so instead of "upgrade".
                clamp = "ceiling" if nxt == cur else "upgrade"
        elif current_tier:
            if self.reg.rank(tier) < self.reg.rank(current_tier):
                tier, clamp = current_tier, "sticky"   # never downgrade
            elif self.reg.rank(tier) > self.reg.rank(current_tier):
                clamp = "upgrade"   # result is above the caller's tier; the log says so

        out = {"tier": tier, "model": self.reg.name(tier), "source": source,
               "matched_rule": matched, "clamp": clamp}
        self.log.write({"task_id": task_id, "step_type": step_type, "phase": phase,
                        "current_tier": current_tier, "struggle": struggle,
                        "tokens": tokens,
                        "text_sha256": hashlib.sha256((text or "").encode()).hexdigest(),
                        "rules_version": self.rules_version,
                        "confidence": conf, **out})
        return out
