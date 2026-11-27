import yaml

class Registry:
    """Advisor-side view: tiers and names only. Credentials are stripped."""
    def __init__(self, models_path, tiers):
        with open(models_path) as f:
            raw = yaml.safe_load(f)["models"]
        missing = [t for t in tiers if t not in raw]
        if missing:
            raise ValueError(f"tiers missing from models file: {missing}")
        self.tiers = tiers
        self.names = {t: raw[t]["name"] for t in tiers}

    def name(self, tier): return self.names[tier]
    def rank(self, tier): return self.tiers.index(tier)
    def strongest(self): return self.tiers[-1]
