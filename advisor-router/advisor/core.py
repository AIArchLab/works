from .rules import RuleEngine
from .registry import Registry
from .classifier import NullClassifier
from .decisionlog import DecisionLog

STRUGGLE_MIN_TIER = None

class Advisor:
    def __init__(self, rules="rules.yaml", models="models.yaml", log="decisions.jsonl", classifier=None):
        self.rules = RuleEngine(rules)
        self.reg = Registry(models, self.rules.tiers)
        self.clf = classifier or NullClassifier()
        self.log = DecisionLog(log)

    def decide(self, task_id, step_type, text="", tokens=0, phase="entry",
               current_tier=None, struggle=None):
        """phase: 'entry' (classify) or 'reask' (struggle triggered; upgrade only)."""
        tier, source, conf = None, None, None
        tier, rule = self.rules.match(step_type, text, tokens)
        if tier:
            source = f"rule:{rule}"
        else:
            c_tier, conf = self.clf.classify(text)
            if c_tier in self.reg.tiers and conf >= self.rules.threshold:
                tier, source = c_tier, "classifier"
            else:
                tier, source = self.rules.default, "default"

        if phase == "reask":
            # Upgrade only. Struggling means: go at least one tier above current.
            cur = self.reg.rank(current_tier) if current_tier else -1
            nxt = min(cur + 1, len(self.reg.tiers) - 1)
            if self.reg.rank(tier) <= cur:
                tier, source = self.reg.tiers[nxt], f"upgrade({source})"
        elif current_tier and self.reg.rank(tier) < self.reg.rank(current_tier):
            tier, source = current_tier, f"sticky({source})"   # never downgrade

        out = {"tier": tier, "model": self.reg.name(tier), "source": source}
        self.log.write({"task_id": task_id, "step_type": step_type, "phase": phase,
                        "current_tier": current_tier, "struggle": struggle,
                        "confidence": conf, **out})
        return out
