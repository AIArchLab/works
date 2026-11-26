"""Pluggable classifier. Phase 1: no-op (rules + default only).
Phase 2: an embedding-based classifier can be dropped in here."""
from typing import Optional, Tuple

class Classifier:
    def classify(self, text: str) -> Tuple[Optional[str], float]:
        return None, 0.0          # (tier, confidence)

class NullClassifier(Classifier):
    pass

# Sketch for phase 2 (not implemented): encode the text locally, compare it with
# example utterances per tier, and return (tier, confidence). Confidence must come
# from real similarity scores. Anything below the threshold in rules.yaml falls
# back to the strongest tier.
