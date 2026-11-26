import yaml

class Registry:
    """Advisor-side view: tiers and names only. Credentials are stripped."""
    def __init__(self, models_path, tiers):
        raw = yaml.safe_load(open(models_path))["models"]
        self.tiers = tiers
        self.names = {t: raw[t]["name"] for t in tiers}

    def name(self, tier): return self.names[tier]
    def rank(self, tier): return self.tiers.index(tier)
    def strongest(self): return self.tiers[-1]
