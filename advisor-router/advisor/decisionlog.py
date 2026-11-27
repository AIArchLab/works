import json, time, threading

class DecisionLog:
    """Append-only JSONL. Lives with the router. No costs and no raw text here.
    Fields: task_id, step_type, phase, current_tier, struggle, tokens,
    text_sha256 (hash only, content is never stored), rules_version (sha256 of
    the rules file), confidence (null when a rule decided), tier, model,
    source (rule|classifier|default), matched_rule, clamp (sticky|upgrade|none)."""
    def __init__(self, path="decisions.jsonl"):
        self.path, self.lock = path, threading.Lock()

    def write(self, rec: dict):
        rec = {"ts": time.time(), **rec}
        with self.lock, open(self.path, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
