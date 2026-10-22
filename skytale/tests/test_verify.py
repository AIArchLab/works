"""Resume verifier tests: a claim without its route fails."""

import json
import tempfile
import unittest
from pathlib import Path

from skytale.cli import main
from skytale.verify import CLAIM_ROUTES, ROUTES, verify_evidence

GEN = "20260101T000000Z_0123456789ab"
AGENT = "demo"


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.run = self.root / "run"
        self.assertEqual(main(["init", "--agent", AGENT, "--dir", str(self.run),
                               "--generation", GEN, "--store", "store-abc"]), 0)
        for kind in ("context", "summary"):
            path = self.run / f"{AGENT}_handoff_{kind}_{GEN}.md"
            path.write_text(path.read_text(encoding="utf-8") + "\nbody\n", encoding="utf-8")
        self.assertEqual(main(["seal", "--dir", str(self.run), "--commit"]), 0)
        self.index = json.loads((self.run / "index.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self._tmp.cleanup()

    def _items(self):
        return [
            {"route": "offline_gate", "checks_passed": 34,
             "recorded_at": "2026-10-22T05:00:00Z"},
            {"route": "storage_readback", "artifact": "context",
             "file_id": "file-context", "size": 10, "sha256": "a" * 64,
             "normalized_sha256": self.index["context"]["sha256"],
             "recorded_at": "2026-10-22T05:01:00Z"},
            {"route": "storage_readback", "artifact": "summary",
             "file_id": "file-summary", "size": 10, "sha256": "b" * 64,
             "normalized_sha256": self.index["summary"]["sha256"],
             "recorded_at": "2026-10-22T05:02:00Z"},
            {"route": "event_readback", "role": "check_out", "event_id": "page-out",
             "columns": {"name": "x", "owner": AGENT, "state": "done", "time": "t", "note": "n"},
             "recorded_at": "2026-10-22T05:03:00Z"},
            {"route": "event_readback", "role": "check_in", "event_id": "page-in",
             "columns": {"name": "y", "owner": AGENT, "state": "live", "time": "t", "note": "n"},
             "recorded_at": "2026-10-22T05:04:00Z"},
            {"route": "wake", "session_id": "session-new", "delivered_at": "2026-10-22T05:05:00Z",
             "recorded_at": "2026-10-22T05:05:00Z"},
        ]

    def _write(self, items, claims):
        path = self.root / "evidence.json"
        path.write_text(json.dumps({"agent_name": AGENT, "generation_id": GEN,
                                    "items": items, "claims": claims}, ensure_ascii=False),
                        encoding="utf-8")
        return path

    def test_complete_evidence_passes(self):
        report = verify_evidence(self.run, self._write(self._items(),
                                                       ["handoff_completed", "resume_completed"]))
        self.assertTrue(report.ok, report.summary())

    def test_unknown_route_fails(self):
        items = self._items() + [{"route": "vibes", "recorded_at": "2026-10-22T05:05:00Z"}]
        report = verify_evidence(self.run, self._write(items, []))
        self.assertFalse(report.ok)
        self.assertTrue(any(f.code.startswith("EVD-011") and not f.ok for f in report.findings))

    def test_storage_hash_must_match_index(self):
        items = self._items()
        items[1]["normalized_sha256"] = "0" * 64
        report = verify_evidence(self.run, self._write(items, []))
        self.assertTrue(any(f.code.startswith("EVD-015") and not f.ok for f in report.findings))

    def test_missing_check_in_fails(self):
        items = [i for i in self._items() if i.get("role") != "check_in"]
        report = verify_evidence(self.run, self._write(items, []))
        self.assertTrue(any(f.code == "EVD-030-check_in" and not f.ok for f in report.findings))

    def test_claim_needs_its_route(self):
        report = verify_evidence(self.run, self._write(self._items(), ["delivery_verified"]))
        self.assertTrue(any(f.code.startswith("EVD-052") and not f.ok for f in report.findings))

    def test_unknown_claim_fails(self):
        report = verify_evidence(self.run, self._write(self._items(), ["everything_green"]))
        self.assertTrue(any(f.code.startswith("EVD-051") and not f.ok for f in report.findings))

    def test_receipt_must_be_processed(self):
        items = self._items() + [{"route": "dispatcher_receipt", "request_id": f"{AGENT}_{GEN}_check_out",
                                  "agent": AGENT, "source": "queue", "status": "QUEUED",
                                  "recorded_at": "2026-10-22T05:06:00Z"}]
        report = verify_evidence(self.run, self._write(items, []))
        self.assertTrue(any(f.code.startswith("EVD-020") and not f.ok for f in report.findings))

    def test_naive_timestamp_fails(self):
        items = self._items()
        items[0]["recorded_at"] = "2026-10-22T05:00:00"
        report = verify_evidence(self.run, self._write(items, []))
        self.assertTrue(any(f.code.startswith("EVD-012") and not f.ok for f in report.findings))

    def test_evidence_generation_must_match_index(self):
        path = self.root / "evidence.json"
        path.write_text(json.dumps({"agent_name": AGENT,
                                    "generation_id": "20260101T000000Z_ffffffffffff",
                                    "items": self._items(), "claims": []}), encoding="utf-8")
        report = verify_evidence(self.run, path)
        self.assertTrue(any(f.code == "EVD-001" and not f.ok for f in report.findings))

    def test_cli_exit_codes(self):
        good = self._write(self._items(), ["handoff_completed"])
        self.assertEqual(main(["verify", "--dir", str(self.run), "--evidence", str(good)]), 0)
        bad = self._write(self._items(), ["delivery_verified"])
        self.assertEqual(main(["verify", "--dir", str(self.run), "--evidence", str(bad)]), 1)

    def test_claim_route_table_is_documented(self):
        self.assertEqual(set(CLAIM_ROUTES), {"handoff_completed", "resume_completed",
                                            "delivery_verified"})
        self.assertEqual(set(ROUTES), {"offline_gate", "storage_readback", "event_readback",
                                       "dispatcher_receipt", "wake"})


if __name__ == "__main__":
    unittest.main()
