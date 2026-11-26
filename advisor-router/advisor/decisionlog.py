import json, time, threading

class DecisionLog:
    """Append-only JSONL. Lives with the router. No tokens or costs here."""
    def __init__(self, path="decisions.jsonl"):
        self.path, self.lock = path, threading.Lock()

    def write(self, rec: dict):
        rec = {"ts": time.time(), **rec}
        with self.lock, open(self.path, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
