import json, time, threading

class DecisionLog:
    """Append-only JSONL. Lives with the router. No costs and no raw text here.
    Fields: task_id, step_type, phase, current_tier, struggle, tokens,
    text_sha256 (hash only, content is never stored), rules_version (sha256 of
    the rules file), confidence (null when a rule decided), tier, model,
    source (rule|classifier|default), matched_rule, clamp.
    clamp contract: sticky = result raised to current_tier (never downgrade);
    upgrade = returned tier is above current_tier (reask moved up, or an entry
    call with current_tier got a higher tier; the caller is still responsible
    for that input); ceiling = reask at the top tier, nothing higher exists,
    tier is unchanged; none = no current_tier adjustment applied."""
    def __init__(self, path="decisions.jsonl"):
        self.path, self.lock = path, threading.Lock()

    def write(self, rec: dict):
        rec = {"ts": time.time(), **rec}
        with self.lock, open(self.path, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
