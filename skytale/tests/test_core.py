"""Core primitive tests (stdlib unittest, no third-party dependencies)."""

import hashlib
import unittest
from datetime import datetime, timezone

from skytale.core import (
    GEN_RE,
    artifact_name,
    generation_id,
    lf_utf8_v1,
    parse_generation,
    sha256_lf_utf8_v1,
)


class NormalizationTests(unittest.TestCase):
    def test_bom_is_stripped_once(self):
        self.assertEqual(lf_utf8_v1(b"\xef\xbb\xbfhello"), "hello")

    def test_crlf_and_lone_cr_become_lf(self):
        self.assertEqual(lf_utf8_v1(b"a\r\nb\rc"), "a\nb\nc")

    def test_no_strip_and_no_trailing_newline_added(self):
        self.assertEqual(lf_utf8_v1(b"  a  "), "  a  ")
        self.assertEqual(lf_utf8_v1(b"a\n"), "a\n")

    def test_hash_matches_manual_normalization(self):
        raw = b"\xef\xbb\xbfline1\r\nline2\r\n"
        expected = hashlib.sha256("line1\nline2\n".encode("utf-8")).hexdigest()
        self.assertEqual(sha256_lf_utf8_v1(raw), expected)


class GenerationTests(unittest.TestCase):
    def test_deterministic_with_entropy(self):
        when = datetime(2026, 10, 22, 4, 39, 28, tzinfo=timezone.utc)
        gen = generation_id(when, bytes.fromhex("c4fadc50311c"))
        self.assertEqual(gen, "20261022T043928Z_c4fadc50311c")
        self.assertTrue(GEN_RE.match(gen))

    def test_rejects_bad_values(self):
        for bad in ["", "20261022T043928Z", "20261022T043928Z_C4FADC50311C", "x_123456789012"]:
            with self.assertRaises(ValueError):
                parse_generation(bad)

    def test_entropy_too_short(self):
        with self.assertRaises(ValueError):
            generation_id(datetime.now(timezone.utc), b"\x00\x01")


class NamingTests(unittest.TestCase):
    def test_artifact_names(self):
        gen = "20261022T043928Z_c4fadc50311c"
        self.assertEqual(artifact_name("demo", "context", gen), f"demo_handoff_context_{gen}.md")
        self.assertEqual(artifact_name("demo", "summary", gen), f"demo_handoff_summary_{gen}.md")
        self.assertEqual(artifact_name("demo", "index", gen), f"demo_handoff_index_{gen}.json")
        with self.assertRaises(ValueError):
            artifact_name("demo", "pointer", gen)


if __name__ == "__main__":
    unittest.main()
