"""Gate and CLI tests (stdlib unittest, no third-party dependencies)."""

import json
import tempfile
import unittest
from pathlib import Path

from skytale.cli import main
from skytale.gate import check_generation, render_prompt

GEN = "20261022T043928Z_c4fadc50311c"
AGENT = "demo"


def make_run(root: Path, commit: bool = True) -> Path:
    run = root / "run"
    assert main(["init", "--agent", AGENT, "--dir", str(run), "--generation", GEN,
                 "--store", "store-abc"]) == 0
    for kind in ("context", "summary"):
        path = run / f"{AGENT}_handoff_{kind}_{GEN}.md"
        body = path.read_text(encoding="utf-8").replace(
            "## Goal and background", "## Goal and background\n\nship the handoff kit MVP")
        path.write_text(body, encoding="utf-8")
    assert main(["seal", "--dir", str(run)] + (["--commit"] if commit else [])) == 0
    if commit:
        index = json.loads((run / "index.json").read_text(encoding="utf-8"))
        index["index_file_id"] = "file-index-1"
        index["context"]["file_id"] = "file-context-1"
        index["summary"]["file_id"] = "file-summary-1"
        index["checkout"]["verified"] = True
        index["checkout"]["event_page_id"] = "page-1"
        index["checkout"]["verification_method"] = "direct_api_readback"
        (run / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8")
    return run


class GateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_valid_generation_passes(self):
        report = check_generation(make_run(self.root))
        self.assertTrue(report.ok, report.summary())
        codes = {c.code for c in report.checks}
        self.assertTrue({"CFG-001", "IDX-003", "CONTEXT-005", "SUMMARY-005", "COM-IDX"} <= codes)

    def test_tampered_context_fails_hash(self):
        run = make_run(self.root)
        path = run / f"{AGENT}_handoff_context_{GEN}.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nlate edit\n", encoding="utf-8")
        report = check_generation(run)
        self.assertFalse(report.ok)
        self.assertTrue(any(c.code == "CONTEXT-005" and not c.ok for c in report.checks))

    def test_wrong_parent_fails(self):
        run = make_run(self.root)
        index = json.loads((run / "index.json").read_text(encoding="utf-8"))
        index["summary"]["parent_id"] = "store-other"
        (run / "index.json").write_text(json.dumps(index), encoding="utf-8")
        report = check_generation(run)
        self.assertTrue(any(c.code == "SUMMARY-003" and not c.ok for c in report.checks))

    def test_placeholder_body_fails(self):
        run = make_run(self.root, commit=False)
        path = run / f"{AGENT}_handoff_summary_{GEN}.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nTODO\n", encoding="utf-8")
        report = check_generation(run)
        self.assertTrue(any(c.code == "SUMMARY-006" and not c.ok for c in report.checks))

    def test_committed_requires_remote_ids(self):
        run = make_run(self.root)
        index = json.loads((run / "index.json").read_text(encoding="utf-8"))
        index["context"]["file_id"] = ""
        (run / "index.json").write_text(json.dumps(index), encoding="utf-8")
        report = check_generation(run)
        self.assertTrue(any(c.code == "COM-CON" and not c.ok for c in report.checks))

    def test_prepared_state_skips_remote_id_checks(self):
        report = check_generation(make_run(self.root, commit=False))
        self.assertFalse(any(c.code.startswith("COM-") for c in report.checks))

    def test_pointer_must_match(self):
        run = make_run(self.root)
        index = json.loads((run / "index.json").read_text(encoding="utf-8"))
        pointer = {
            "agent_name": AGENT,
            "generation_id": GEN,
            "index_file_id": index["index_file_id"],
            "store_id": "store-abc",
            "committed_at": "2026-10-22T12:41:45+08:00",
            "verification_method": "direct_api_readback",
        }
        (run / "pointer.json").write_text(json.dumps(pointer), encoding="utf-8")
        self.assertTrue(check_generation(run).ok)
        pointer["generation_id"] = "20261022T043928Z_000000000001"
        (run / "pointer.json").write_text(json.dumps(pointer), encoding="utf-8")
        report = check_generation(run)
        self.assertTrue(any(c.code == "PTR-001" and not c.ok for c in report.checks))

    def test_bad_generation_id_fails(self):
        run = make_run(self.root)
        index = json.loads((run / "index.json").read_text(encoding="utf-8"))
        index["generation_id"] = "not-a-generation"
        (run / "index.json").write_text(json.dumps(index), encoding="utf-8")
        report = check_generation(run)
        self.assertTrue(any(c.code == "IDX-003" and not c.ok for c in report.checks))


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_prompt_mentions_generation_and_store(self):
        run = make_run(self.root)
        cfg = json.loads((run / "agent_config.json").read_text(encoding="utf-8"))
        index = json.loads((run / "index.json").read_text(encoding="utf-8"))
        text = render_prompt(cfg, index)
        self.assertIn(GEN, text)
        self.assertIn("store-abc", text)
        self.assertIn(index["checkin_request_id"], text)

    def test_init_refuses_overwrite_without_force(self):
        run = self.root / "run"
        self.assertEqual(main(["init", "--agent", AGENT, "--dir", str(run), "--generation", GEN]), 0)
        with self.assertRaises(SystemExit):
            main(["init", "--agent", AGENT, "--dir", str(run), "--generation", GEN])
        self.assertEqual(
            main(["init", "--agent", AGENT, "--dir", str(run), "--generation", GEN, "--force"]), 0)

    def test_check_exit_codes(self):
        run = make_run(self.root)
        self.assertEqual(main(["check", "--dir", str(run)]), 0)
        path = run / f"{AGENT}_handoff_summary_{GEN}.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nextra\n", encoding="utf-8")
        self.assertEqual(main(["check", "--dir", str(run)]), 1)


if __name__ == "__main__":
    unittest.main()
