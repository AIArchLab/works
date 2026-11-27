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
    assert up["tier"] == "mid" and up["clamp"] == "upgrade"
    top = a.decide("t", "extract", phase="reask", current_tier="strong", struggle="x")
    assert top["tier"] == "strong"

def test_never_downgrades_after_entry(tmp_path):
    out = make(tmp_path).decide("t", "extract", current_tier="strong")
    assert out["tier"] == "strong" and out["clamp"] == "sticky"

def test_response_carries_name_only_and_log_has_no_secrets(tmp_path):
    a = make(tmp_path)
    out = a.decide("t", "plan")
    assert set(out) == {"tier", "model", "source", "matched_rule", "clamp"}
    line = (tmp_path / "d.jsonl").read_text()
    assert "api_key" not in line and "endpoint" not in line
    assert json.loads(line.splitlines()[0])["task_id"] == "t"


# --- review fixes ---
import hashlib
import pytest
from fastapi.testclient import TestClient

def test_long_context_not_shadowed_by_step_type_rule(tmp_path):
    out = make(tmp_path).decide("t", "extract", tokens=100_000)
    assert out["tier"] == "strong" and out["matched_rule"] == "long-context"

def test_keyword_rule_not_shadowed_and_case_insensitive(tmp_path):
    out = make(tmp_path).decide("t", "extract", text="Please PROVE this")
    assert out["tier"] == "strong" and out["matched_rule"] == "keyword-hard"

def test_default_must_be_strongest(tmp_path):
    bad = tmp_path / "rules.yaml"
    bad.write_text("default_model: mid\ntiers: [cheap, mid, strong]\nrules: []\n")
    with pytest.raises(ValueError):
        Advisor(rules=str(bad), models=str(ROOT / "models.yaml"), log=str(tmp_path / "d"))

def test_rule_with_unknown_tier_rejected_at_load(tmp_path):
    bad = tmp_path / "rules.yaml"
    bad.write_text("default_model: strong\ntiers: [cheap, strong]\nrules:\n"
                   "  - {name: x, when: {step_type: [a]}, model: ghost}\n")
    with pytest.raises(ValueError):
        Advisor(rules=str(bad), models=str(ROOT / "models.yaml"), log=str(tmp_path / "d"))

def test_log_has_explainability_fields_and_no_raw_text(tmp_path):
    a = make(tmp_path)
    a.decide("t", "extract", text="secret words", tokens=100_000)
    a.decide("t", "unknown_step", text="hello")
    rows = [json.loads(l) for l in (tmp_path / "d.jsonl").read_text().splitlines()]
    r0, r1 = rows
    assert r0["tokens"] == 100_000 and r0["matched_rule"] == "long-context"
    assert r0["clamp"] == "none" and r0["confidence"] is None
    assert r0["text_sha256"] == hashlib.sha256(b"secret words").hexdigest()
    assert r0["rules_version"] == hashlib.sha256((ROOT / "rules.yaml").read_bytes()).hexdigest()
    assert "secret words" not in json.dumps(rows)
    assert r1["source"] == "default" and r1["matched_rule"] is None and r1["confidence"] == 0.0

def test_clamp_field_values(tmp_path):
    a = make(tmp_path)
    assert a.decide("t", "extract", current_tier="strong")["clamp"] == "sticky"
    assert a.decide("t", "extract", phase="reask", current_tier="cheap", struggle="x")["clamp"] == "upgrade"

@pytest.fixture
def client(tmp_path, monkeypatch):
    from advisor import main
    monkeypatch.setattr(main, "advisor", make(tmp_path))
    return TestClient(main.app)

def test_http_happy_path(client):
    r = client.post("/decide", json={"task_id": "t", "step_type": "plan"})
    assert r.status_code == 200 and r.json()["tier"] == "strong"

def test_http_rejects_bad_phase(client):
    assert client.post("/decide", json={"task_id": "t", "step_type": "plan", "phase": "x"}).status_code == 422

def test_http_rejects_unknown_current_tier(client):
    r = client.post("/decide", json={"task_id": "t", "step_type": "plan", "current_tier": "ghost"})
    assert r.status_code == 422

def test_http_reask_requires_struggle(client):
    r = client.post("/decide", json={"task_id": "t", "step_type": "plan", "phase": "reask", "current_tier": "cheap"})
    assert r.status_code == 422

def test_http_rejects_negative_tokens(client):
    assert client.post("/decide", json={"task_id": "t", "step_type": "plan", "tokens": -1}).status_code == 422

def test_runtime_retry_appends_user_message_once_and_counts_fails(monkeypatch):
    import runtime_client as rc
    monkeypatch.chdir(ROOT)
    seen, struggles = [], []
    def fake_call(tier, messages):
        seen.append(len(messages)); return {"text": "x", "ok": False}
    def fake_decide(**kw):
        struggles.append(kw["struggle"])
        order = ["cheap", "mid", "strong"]
        return {"tier": order[min(order.index(kw["current_tier"]) + 1, 2)]}
    monkeypatch.setattr(rc, "call_model", fake_call)
    monkeypatch.setattr(rc, "decide", lambda **kw: {"tier": "cheap"} if kw.get("phase") is None else fake_decide(**kw))
    rc.run_task("t", [("extract", "hi")])
    assert set(seen) == {1}
    assert "tool_error_x3" in struggles


# --- rule schema validation (fail closed) ---
import pytest, yaml
from fastapi.testclient import TestClient

def _rules_file(tmp_path, rule):
    cfg = {"default_model": "strong", "tiers": ["cheap", "mid", "strong"], "rules": [rule]}
    p = tmp_path / "r.yaml"; p.write_text(yaml.safe_dump(cfg)); return str(p)

def _load(tmp_path, when):
    from advisor.rules import RuleEngine
    return RuleEngine(_rules_file(tmp_path, {"name": "x", "when": when, "model": "cheap"}))

def test_typo_key_rejected(tmp_path):
    with pytest.raises(ValueError):
        _load(tmp_path, {"keyword": ["prove"]})

def test_empty_when_rejected(tmp_path):
    with pytest.raises(ValueError):
        _load(tmp_path, {})

def test_string_min_tokens_rejected(tmp_path):
    with pytest.raises(ValueError):
        _load(tmp_path, {"min_tokens": "60000"})

def test_rules_version_matches_applied_bytes(tmp_path):
    import hashlib
    eng = _load(tmp_path, {"step_type": ["extract"]})
    assert eng.version == hashlib.sha256((tmp_path / "r.yaml").read_bytes()).hexdigest()

# --- clamp contract ---
def test_reask_at_top_logs_ceiling_not_upgrade(tmp_path):
    out = make(tmp_path).decide("t", "extract", phase="reask", current_tier="strong", struggle="x")
    assert out["tier"] == "strong" and out["clamp"] == "ceiling"

def test_entry_result_above_current_tier_logs_upgrade(tmp_path):
    out = make(tmp_path).decide("t", "plan", current_tier="cheap")
    assert out["tier"] == "strong" and out["clamp"] == "upgrade"
    rec = json.loads((tmp_path / "d.jsonl").read_text().splitlines()[-1])
    assert rec["current_tier"] == "cheap" and rec["clamp"] == "upgrade"

# --- HTTP ---
def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("RULES", str(ROOT / "rules.yaml"))
    monkeypatch.setenv("MODELS", str(ROOT / "models.yaml"))
    monkeypatch.setenv("DECISION_LOG", str(tmp_path / "h.jsonl"))
    import importlib, advisor.main as m
    importlib.reload(m)
    return TestClient(m.app)

def test_http_reask_without_current_tier_is_422(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/decide", json={"task_id": "t", "step_type": "extract", "phase": "reask", "struggle": "x"})
    assert r.status_code == 422
    assert not (tmp_path / "h.jsonl").exists()

def test_http_reask_at_top_reports_ceiling(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/decide", json={"task_id": "t", "step_type": "extract", "phase": "reask",
                                "current_tier": "strong", "struggle": "x"})
    assert r.status_code == 200 and r.json()["clamp"] == "ceiling"
