import yaml

class RuleEngine:
    def __init__(self, path):
        with open(path) as f:
            cfg = yaml.safe_load(f)
        self.rules = cfg.get("rules", [])
        self.default = cfg["default_model"]
        self.threshold = cfg.get("confidence_threshold", 0.6)
        self.tiers = cfg["tiers"]
        for tier in [self.default] + [r["model"] for r in self.rules]:
            if tier not in self.tiers:
                raise ValueError(f"unknown tier {tier!r} in rules; tiers are {self.tiers}")

    def match(self, step_type, text, tokens):
        text = (text or "").lower()
        for r in self.rules:
            w = r["when"]
            if "step_type" in w and step_type not in w["step_type"]:
                continue
            if "min_tokens" in w and tokens < w["min_tokens"]:
                continue
            if "keywords" in w and not any(k.lower() in text for k in w["keywords"]):
                continue
            return r["model"], r["name"]
        return None, None
