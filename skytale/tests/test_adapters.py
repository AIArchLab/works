"""Synthetic adapter contract tests; not remote acceptance evidence."""
import hashlib
import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock

from skytale.core import sha256_lf_utf8_v1
from skytale.storage import (ObjectStoreAdapter, StoredFile,
                             StorageVerificationError, verify_readback)
from skytale.events import (COLUMNS, EventIntent, EventRow, EventSchema,
                            EventStoreAdapter, EventVerificationError)
from skytale.dispatcher import (DispatchRequest, DispatcherAdapter,
                                ReceiptVerificationError, verify_receipt)


class MemoryObjects:
    def __init__(self):
        self.objects = {}
        self.data = {}

    def put_object(self, store_id, name, data):
        file_id = f"synthetic-file-{len(self.objects) + 1}"
        info = StoredFile(file_id, name, store_id, len(data), hashlib.sha256(data).hexdigest())
        self.objects[file_id], self.data[file_id] = info, data
        return info

    def get_object(self, store_id, file_id):
        return self.data[file_id]

    def stat_object(self, store_id, file_id):
        return self.objects[file_id]

    def list_objects(self, store_id, query):
        return [v for v in self.objects.values() if query in v.name]


class StorageContractTests(unittest.TestCase):
    def setUp(self):
        self.client = MemoryObjects()
        self.store = ObjectStoreAdapter(self.client, "synthetic-store")
        self.raw = b"\xef\xbb\xbfcontext\r\nno trailing newline"
        self.meta = self.store.put("context.md", self.raw)

    def test_put_get_list_and_two_hashes(self):
        self.assertEqual(self.store.get(self.meta.file_id), self.raw)
        self.assertEqual(self.store.list("context"), [self.meta])
        self.assertEqual(self.store.list("missing"), [])
        digest = sha256_lf_utf8_v1(self.raw)
        evidence = verify_readback(self.store, self.meta, self.raw, normalized_sha256=digest)
        self.assertEqual(evidence.normalized_sha256, digest)
        self.assertNotEqual(self.meta.sha256, digest)
        self.assertEqual(evidence.route, "storage_readback")

    def test_normalization_only_match_is_not_byte_equality(self):
        changed = b"context\nno trailing newline"
        self.client.data[self.meta.file_id] = changed
        self.client.objects[self.meta.file_id] = replace(
            self.meta, size=len(changed), sha256=hashlib.sha256(changed).hexdigest())
        self.assertEqual(sha256_lf_utf8_v1(changed), sha256_lf_utf8_v1(self.raw))
        with self.assertRaises(StorageVerificationError):
            verify_readback(self.store, self.meta, self.raw)

    def test_every_metadata_field_is_checked(self):
        for field, bad in [("file_id", "foreign"), ("parent_id", "foreign"),
                           ("name", "other.md"), ("size", 999), ("sha256", "0" * 64)]:
            with self.subTest(field=field):
                self.client.objects[self.meta.file_id] = replace(self.meta, **{field: bad})
                with self.assertRaises(StorageVerificationError):
                    verify_readback(self.store, self.meta, self.raw)

    def test_truncated_read_fails(self):
        self.client.data[self.meta.file_id] = self.raw[:-1]
        with self.assertRaises(StorageVerificationError):
            verify_readback(self.store, self.meta, self.raw)

    def test_wrong_normalized_hash_fails(self):
        with self.assertRaises(StorageVerificationError):
            verify_readback(self.store, self.meta, self.raw, normalized_sha256="0" * 64)

    def test_non_utf8_only_fails_when_text_hash_is_requested(self):
        meta = self.store.put("binary", b"\xff")
        verify_readback(self.store, meta, b"\xff")
        with self.assertRaises(StorageVerificationError):
            verify_readback(self.store, meta, b"\xff", normalized_sha256="0" * 64)

    def test_write_ack_is_not_readback(self):
        del self.client.data[self.meta.file_id]
        with self.assertRaises(KeyError):
            verify_readback(self.store, self.meta, self.raw)

    def test_foreign_list_fails(self):
        self.client.objects[self.meta.file_id] = replace(self.meta, parent_id="foreign")
        with self.assertRaises(StorageVerificationError):
            self.store.list()

    def test_bad_put_ack_fails(self):
        self.client.put_object = Mock(return_value=replace(self.meta, size=-1))
        with self.assertRaises(StorageVerificationError):
            self.store.put("context.md", self.raw)

    def test_transport_failure_propagates(self):
        self.client.get_object = Mock(side_effect=TimeoutError)
        with self.assertRaises(TimeoutError):
            verify_readback(self.store, self.meta, self.raw)

    def test_invalid_put_arguments_fail(self):
        for name, data in [("", b"x"), ("x", "not bytes")]:
            with self.assertRaises(ValueError):
                self.store.put(name, data)


class MemoryEvents:
    def __init__(self):
        self.schema = EventSchema(dict(COLUMNS), ("demo",), ("done",))
        self.rows, self.calls = {}, []
        self.mutate = lambda cols: cols

    def read_schema(self):
        self.calls.append("schema")
        return self.schema

    def find_by_request_id(self, request_id):
        self.calls.append("find")
        return [r for r in self.rows.values()
                if json.loads(r.columns["note"])["request_id"] == request_id]

    def create(self, columns):
        self.calls.append("create")
        event_id = f"synthetic-event-{len(self.rows) + 1}"
        self.rows[event_id] = EventRow(event_id, self.mutate(dict(columns)))
        return event_id

    def read(self, event_id):
        self.calls.append("read")
        return self.rows[event_id]


class EventContractTests(unittest.TestCase):
    def setUp(self):
        self.client = MemoryEvents()
        self.clock = lambda: datetime(2026, 1, 2, tzinfo=timezone.utc)
        self.adapter = EventStoreAdapter(self.client, self.clock)
        self.intent = EventIntent("demo", "20260101T000000Z_0123456789ab", "check_out",
                                  "demo", "done", "2026-01-01T00:01:00Z",
                                  "https://example.invalid/index", "explicit handoff")

    def test_schema_first_create_readback_and_retry(self):
        first = self.adapter.ensure(self.intent)
        again = self.adapter.ensure(self.intent)
        self.assertEqual(self.client.calls[:4], ["schema", "find", "create", "read"])
        self.assertFalse(first.reused)
        self.assertTrue(again.reused)
        self.assertEqual(first.row.event_id, again.row.event_id)
        self.assertEqual(self.client.calls.count("create"), 1)
        self.assertEqual(first.route, "event_store_readback")
        self.assertFalse(first.atomic_claim)

    def test_verify_previous_checkout_is_read_only(self):
        first = self.adapter.ensure(self.intent)
        self.client.calls.clear()
        self.adapter.verify(first.row.event_id, self.intent)
        self.assertEqual(self.client.calls, ["schema", "read"])

    def test_schema_missing_or_wrong_type_stops_before_write(self):
        for key in COLUMNS:
            columns = dict(COLUMNS)
            columns[key] = "incompatible"
            self.client.schema = replace(self.client.schema, columns=columns)
            with self.assertRaises(EventVerificationError):
                self.adapter.ensure(self.intent)
        self.assertNotIn("create", self.client.calls)

    def test_existing_owner_and_state_options_required(self):
        for field in ("owner", "state"):
            with self.assertRaises(EventVerificationError):
                self.adapter.ensure(replace(self.intent, **{field: "new-option"}))
        self.assertNotIn("create", self.client.calls)

    def test_future_past_naive_or_invalid_timestamp_fails(self):
        for stamp in ["2026-01-03T00:00:00Z", "2025-12-31T23:59:00Z",
                      "2026-01-01T00:01:00", "nonsense"]:
            with self.subTest(stamp=stamp), self.assertRaises(EventVerificationError):
                self.adapter.ensure(replace(self.intent, occurred_at=stamp))
        self.assertNotIn("create", self.client.calls)

    def test_bad_identity_action_source_reason_fails(self):
        for field, bad in [("agent", "bad agent"), ("generation", "bad"),
                           ("action", "resume_completed"), ("source", "not-a-link"),
                           ("reason", " ")]:
            with self.subTest(field=field), self.assertRaises(EventVerificationError):
                self.adapter.ensure(replace(self.intent, **{field: bad}))
        self.assertNotIn("create", self.client.calls)

    def test_every_column_readback_is_compared(self):
        for key in COLUMNS:
            self.client = MemoryEvents()
            self.adapter = EventStoreAdapter(self.client, self.clock)
            self.client.mutate = lambda cols, k=key: {**cols, k: "mismatch"}
            with self.subTest(key=key), self.assertRaises(EventVerificationError):
                self.adapter.ensure(self.intent)

    def test_missing_readback_column_fails(self):
        for key in COLUMNS:
            self.client = MemoryEvents()
            self.adapter = EventStoreAdapter(self.client, self.clock)
            self.client.mutate = lambda cols, k=key: {x: v for x, v in cols.items() if x != k}
            with self.subTest(key=key), self.assertRaises(EventVerificationError):
                self.adapter.ensure(self.intent)

    def test_prior_generation_cannot_be_reused(self):
        first = self.adapter.ensure(self.intent)
        other = replace(self.intent, generation="20260101T000000Z_aaaaaaaaaaaa")
        with self.assertRaises(EventVerificationError):
            self.adapter.verify(first.row.event_id, other)

    def test_retry_with_changed_content_fails(self):
        self.adapter.ensure(self.intent)
        with self.assertRaises(EventVerificationError):
            self.adapter.ensure(replace(self.intent, reason="content correction"))
        self.assertEqual(len(self.client.rows), 1)

    def test_duplicate_search_fails_without_create(self):
        first = self.adapter.ensure(self.intent)
        self.client.rows["duplicate"] = replace(first.row, event_id="duplicate")
        with self.assertRaises(EventVerificationError):
            self.adapter.ensure(self.intent)
        self.assertEqual(self.client.calls.count("create"), 1)

    def test_race_duplicate_detected_after_create(self):
        original = self.client.create
        def raced(columns):
            event_id = original(columns)
            self.client.rows["racer"] = EventRow("racer", dict(columns))
            return event_id
        self.client.create = raced
        with self.assertRaises(EventVerificationError):
            self.adapter.ensure(self.intent)

    def test_json_order_and_equivalent_timezone_are_semantic(self):
        first = self.adapter.ensure(self.intent)
        columns = dict(first.row.columns)
        columns["note"] = json.dumps(json.loads(columns["note"]), indent=2)
        columns["time"] = "2026-01-01T08:01:00+08:00"
        self.client.rows[first.row.event_id] = EventRow(first.row.event_id, columns)
        self.adapter.verify(first.row.event_id, self.intent)

    def test_duplicate_json_keys_fail(self):
        first = self.adapter.ensure(self.intent)
        columns = dict(first.row.columns)
        columns["note"] = columns["note"][:-1] + ',"action":"check_out"}'
        self.client.rows[first.row.event_id] = EventRow(first.row.event_id, columns)
        with self.assertRaises(EventVerificationError):
            self.adapter.verify(first.row.event_id, self.intent)

    def test_checkin_supported_without_automatic_cross_session_creation(self):
        self.adapter.ensure(replace(self.intent, action="check_in"))
        self.assertEqual(len(self.client.rows), 1)
        self.assertIn("_check_in", next(iter(self.client.rows.values())).columns["name"])

    def test_read_failure_does_not_return_evidence(self):
        self.client.read = Mock(side_effect=TimeoutError)
        with self.assertRaises(TimeoutError):
            self.adapter.ensure(self.intent)


class DispatcherContractTests(unittest.TestCase):
    def setUp(self):
        self.expected = DispatchRequest("demo", "synthetic-request", "https://example.invalid/index")
        self.payload = {**vars(self.expected), "status": "PROCESSED"}

    def test_processed_receipt_requires_all_identity_fields(self):
        receipt = verify_receipt(self.payload, self.expected)
        self.assertEqual(receipt.route, "dispatcher_receipt")
        self.assertEqual(receipt.status, "PROCESSED")

    def test_mismatched_or_missing_fields_fail(self):
        for key in ("agent", "request_id", "source", "status"):
            for payload in [{k: v for k, v in self.payload.items() if k != key},
                            {**self.payload, key: "wrong"}]:
                with self.subTest(key=key), self.assertRaises(ReceiptVerificationError):
                    verify_receipt(payload, self.expected)

    def test_pending_or_lowercase_is_not_processed(self):
        for status in ("PENDING", "ACCEPTED", "processed", "FAILED"):
            with self.assertRaises(ReceiptVerificationError):
                verify_receipt({**self.payload, "status": status}, self.expected)

    def test_empty_expected_identity_is_rejected(self):
        for key in ("agent", "request_id", "source"):
            with self.assertRaises(ReceiptVerificationError):
                verify_receipt({**self.payload, key: ""}, replace(self.expected, **{key: ""}))

    def test_adapter_fetches_receipt(self):
        client = Mock()
        client.read_receipt.return_value = self.payload
        DispatcherAdapter(client).readback(self.expected)
        client.read_receipt.assert_called_once_with(self.expected.request_id)

    def test_missing_receipt_propagates(self):
        client = Mock()
        client.read_receipt.side_effect = LookupError
        with self.assertRaises(LookupError):
            DispatcherAdapter(client).readback(self.expected)


class OfflineWorkflowTests(unittest.TestCase):
    def test_demo_gate_storage_event_and_receipt_keep_routes_separate(self):
        from pathlib import Path
        from skytale.gate import check_generation, render_prompt
        run = Path(__file__).resolve().parents[1] / "examples" / "demo"
        before = {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()}
        self.assertTrue(check_generation(run).ok)
        index = json.loads((run / "index.json").read_text())
        store = ObjectStoreAdapter(MemoryObjects(), index["store_id"])
        for kind in ("context", "summary"):
            artifact = index[kind]
            raw = (run / artifact["file_name"]).read_bytes()
            uploaded = store.put(artifact["file_name"], raw)
            result = verify_readback(store, uploaded, raw,
                                     normalized_sha256=artifact["sha256"])
            self.assertEqual(result.route, "storage_readback")
        source = "https://example.invalid/synthetic-index"
        intent = EventIntent(index["agent_name"], index["generation_id"], "check_out",
                             "demo", "done", "2026-01-01T00:01:00Z", source,
                             "synthetic integration test")
        client = MemoryEvents()
        event = EventStoreAdapter(client, lambda: datetime(2026, 1, 2, tzinfo=timezone.utc))
        evidence = event.ensure(intent)
        self.assertEqual(evidence.request_id, index["checkout"]["request_id"])
        expected = DispatchRequest(intent.agent, intent.request_id, source)
        dispatcher = Mock()
        dispatcher.read_receipt.return_value = {**vars(expected), "status": "PROCESSED"}
        receipt = DispatcherAdapter(dispatcher).readback(expected)
        self.assertNotEqual(receipt.route, evidence.route)
        self.assertIn(index["generation_id"], render_prompt(json.loads((run / "agent_config.json").read_text()), index))
        self.assertEqual(before, {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()})


if __name__ == "__main__":
    unittest.main()
