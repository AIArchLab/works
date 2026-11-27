import hashlib
import yaml

ALLOWED_WHEN = {"step_type", "min_tokens", "keywords"}

class RuleEngine:
    def __init__(self, path):
        # Read the bytes once: the parsed config and the version hash come from
        # the same bytes, so the hash always names the rules actually applied.
        with open(path, "rb") as f:
            raw = f.read()
        self.version = hashlib.sha256(raw).hexdigest()
        cfg = yaml.safe_load(raw)
        self.rules = cfg.get("rules", [])
        self.default = cfg["default_model"]
        self.threshold = cfg.get("confidence_threshold", 0.6)
        self.tiers = cfg["tiers"]
        for tier in [self.default] + [r["model"] for r in self.rules]:
            if tier not in self.tiers:
                raise ValueError(f"unknown tier {tier!r} in rules; tiers are {self.tiers}")
        for r in self.rules:
            self._validate_when(r)

    @staticmethod
    def _validate_when(r):
        """Fail closed at load time: a malformed rule must never become a catch-all."""
        name = r.get("name", "<unnamed>")
        w = r.get("when")
        if not isinstance(w, dict) or not w:
            raise ValueError(f"rule {name!r}: 'when' must be a non-empty mapping")
        unknown = set(w) - ALLOWED_WHEN
        if unknown:
            raise ValueError(f"rule {name!r}: unknown 'when' keys {sorted(unknown)}; "
                             f"allowed keys are {sorted(ALLOWED_WHEN)}")
        mt = w.get("min_tokens")
        if "min_tokens" in w and (isinstance(mt, bool) or not isinstance(mt, int)):
            raise ValueError(f"rule {name!r}: min_tokens must be an int, got {mt!r}")
        for k in ("step_type", "keywords"):
            if k in w and (not isinstance(w[k], list) or not w[k]
                           or not all(isinstance(x, str) for x in w[k])):
                raise ValueError(f"rule {name!r}: {k} must be a non-empty list of strings")

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
