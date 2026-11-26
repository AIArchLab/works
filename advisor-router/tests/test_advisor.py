import json, pathlib
from advisor.core import Advisor
from advisor.classifier import Classifier

ROOT = pathlib.Path(__file__).resolve().parent.parent

def make(tmp_path, clf=None):
    return Advisor(rules=str(ROOT / "rules.yaml"), models=str(ROOT / "models.yaml"),
                   log=str(tmp_path / "d.jsonl"), classifier=clf)

def test_first_match_wins(tmp_path):
    a = make(tmp_path)
    assert a.decide("t", "extract")["tier"] == "cheap"
    assert a.decide("t", "plan")["tier"] == "strong"

def test_default_is_strongest_when_nothing_matches(tmp_path):
    out = make(tmp_path).decide("t", "unknown_step", text="hello")
    assert out["tier"] == "strong" and out["source"] == "default"

def test_low_confidence_classifier_falls_back_to_default(tmp_path):
    class Low(Classifier):
        def classify(self, text): return "cheap", 0.3
    assert make(tmp_path, Low()).decide("t", "unknown_step")["tier"] == "strong"

def test_confident_classifier_is_used(tmp_path):
    class High(Classifier):
        def classify(self, text): return "cheap", 0.9
    out = make(tmp_path, High()).decide("t", "unknown_step")
    assert out["tier"] == "cheap" and out["source"] == "classifier"

def test_reask_upgrades_only(tmp_path):
    a = make(tmp_path)
    up = a.decide("t", "extract", phase="reask", current_tier="cheap", struggle="x")
    assert up["tier"] == "mid" and up["source"].startswith("upgrade")
    top = a.decide("t", "extract", phase="reask", current_tier="strong", struggle="x")
    assert top["tier"] == "strong"

def test_never_downgrades_after_entry(tmp_path):
    out = make(tmp_path).decide("t", "extract", current_tier="strong")
    assert out["tier"] == "strong" and out["source"].startswith("sticky")

def test_response_carries_name_only_and_log_has_no_secrets(tmp_path):
    a = make(tmp_path)
    out = a.decide("t", "plan")
    assert set(out) == {"tier", "model", "source"}
    line = (tmp_path / "d.jsonl").read_text()
    assert "api_key" not in line and "endpoint" not in line
    assert json.loads(line.splitlines()[0])["task_id"] == "t"
