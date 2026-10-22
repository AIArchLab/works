#!/usr/bin/env python3
"""Unit tests for the generic check-in SDK. No network calls, no writes."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import checkin  # noqa: E402


SCHEMA = {
    "properties": {
        "Name": {"type": "title"},
        "Agent": {"type": "select", "select": {"options": [{"name": "alice"}, {"name": "bob"}]}},
        "Status": {"type": "select", "select": {"options": [{"name": "Active"}]}},
        "Date": {"type": "date"},
        "Notes": {"type": "rich_text"},
        "Source": {"type": "url"},
    }
}


class UsageTests(unittest.TestCase):
    def test_unknown_argument_rejected(self):
        with self.assertRaises(checkin.UsageError):
            checkin.parse_args(["--bogus"])

    def test_missing_value_rejected(self):
        with self.assertRaises(checkin.UsageError):
            checkin.parse_args(["--agent"])

    def test_help_and_version(self):
        self.assertTrue(checkin.parse_args(["--help"])["help"])
        self.assertTrue(checkin.parse_args(["--version"])["version"])

    def test_equals_form(self):
        args = checkin.parse_args(["--agent=alice", "--reason=test"])
        self.assertEqual(args["agent"], "alice")
        self.assertEqual(args["reason"], "test")


class ResolveTests(unittest.TestCase):
    def test_agent_required(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(checkin.UsageError):
                checkin.resolve_agent({})

    def test_agent_unknown_rejected(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(checkin.UsageError):
                checkin.resolve_agent({"agent": "unknown"})

    def test_agent_valid(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(checkin.resolve_agent({"agent": "alice"}), "alice")

    def test_reason_required(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(checkin.UsageError):
                checkin.resolve_reason({})

    def test_reason_empty_rejected(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(checkin.UsageError):
                checkin.resolve_reason({"reason": "   "})

    def test_offset_default_utc(self):
        with patch.dict(os.environ, {}, clear=True):
            tz, text = checkin.resolve_offset()
            self.assertEqual(text, "+00:00")
            self.assertEqual(tz.utcoffset(None).total_seconds(), 0)

    def test_offset_plus8(self):
        with patch.dict(os.environ, {"CHECKIN_TZ_OFFSET": "+08:00"}, clear=True):
            tz, text = checkin.resolve_offset()
            self.assertEqual(text, "+08:00")
            self.assertEqual(tz.utcoffset(None).total_seconds(), 8 * 3600)

    def test_offset_invalid(self):
        with patch.dict(os.environ, {"CHECKIN_TZ_OFFSET": "CST"}, clear=True):
            with self.assertRaises(checkin.UsageError):
                checkin.resolve_offset()


class SchemaTests(unittest.TestCase):
    def test_resolve_props_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            props = checkin.resolve_props(SCHEMA)
        self.assertEqual(props["title"], "Name")
        self.assertEqual(props["agent"], "Agent")
        self.assertEqual(props["status"], "Status")
        self.assertEqual(props["date"], "Date")
        self.assertEqual(props["notes"], "Notes")
        self.assertEqual(props["source"], "Source")

    def test_resolve_props_missing(self):
        with patch.dict(os.environ, {"CHECKIN_PROP_TITLE": "Missing"}, clear=True):
            with self.assertRaises(checkin.UsageError):
                checkin.resolve_props(SCHEMA)

    def test_resolve_props_custom_names(self):
        schema = {
            "properties": {
                "Title": {"type": "title"},
                "Owner": {"type": "select", "select": {"options": [{"name": "alice"}]}},
                "State": {"type": "select", "select": {"options": [{"name": "Active"}]}},
                "When": {"type": "date"},
                "Memo": {"type": "rich_text"},
            }
        }
        env = {
            "CHECKIN_PROP_TITLE": "Title",
            "CHECKIN_PROP_AGENT": "Owner",
            "CHECKIN_PROP_STATUS": "State",
            "CHECKIN_PROP_DATE": "When",
            "CHECKIN_PROP_NOTES": "Memo",
            "CHECKIN_PROP_SOURCE": "",
        }
        with patch.dict(os.environ, env, clear=True):
            props = checkin.resolve_props(schema)
        self.assertEqual(props["title"], "Title")
        self.assertEqual(props["agent"], "Owner")
        self.assertEqual(props["status"], "State")
        self.assertEqual(props["date"], "When")
        self.assertEqual(props["notes"], "Memo")
        self.assertIsNone(props["source"])

    def test_ensure_agent_select(self):
        checkin.ensure_agent(SCHEMA, "Agent", "alice")
        with self.assertRaises(checkin.UsageError):
            checkin.ensure_agent(SCHEMA, "Agent", "carol")

    def test_build_properties_select(self):
        with patch.dict(os.environ, {"CHECKIN_STATUS_VALUE": "Active"}, clear=True):
            props = checkin.resolve_props(SCHEMA)
            out = checkin.build_page_properties(
                "alice", "2026-10-22T00:00:00.000+00:00", "test", props, SCHEMA, None
            )
        self.assertEqual(out["Name"]["title"][0]["text"]["content"], "alice")
        self.assertEqual(out["Agent"]["select"]["name"], "alice")
        self.assertEqual(out["Status"]["select"]["name"], "Active")
        self.assertIn("occurred_at=", out["Notes"]["rich_text"][0]["text"]["content"])

    def test_build_properties_rich_text_agent(self):
        schema = {
            "properties": {
                "Name": {"type": "title"},
                "Agent": {"type": "rich_text"},
                "Status": {"type": "status"},
                "Date": {"type": "date"},
                "Notes": {"type": "rich_text"},
            }
        }
        with patch.dict(os.environ, {"CHECKIN_STATUS_VALUE": "Active"}, clear=True):
            props = checkin.resolve_props(schema)
            out = checkin.build_page_properties(
                "alice", "2026-10-22T00:00:00.000+00:00", "test", props, schema, None
            )
        self.assertEqual(out["Agent"]["rich_text"][0]["text"]["content"], "alice")
        self.assertEqual(out["Status"]["status"]["name"], "Active")


if __name__ == "__main__":
    unittest.main()
