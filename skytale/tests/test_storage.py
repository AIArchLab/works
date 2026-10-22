"""Storage contract tests: any adapter must keep these green."""

import unittest

from skytale.storage import ContractError, MemoryStore, ObjectRef, Store, verify_roundtrip


class ReferenceStoreTests(unittest.TestCase):
    def test_memory_store_satisfies_protocol(self):
        self.assertIsInstance(MemoryStore(), Store)

    def test_roundtrip_passes_for_reference_store(self):
        store = MemoryStore()
        ref = verify_roundtrip(store, "skytale/context.md", b"payload\n")
        self.assertTrue(ref.file_id)
        self.assertEqual(ref.size, 8)

    def test_get_returns_exact_bytes(self):
        store = MemoryStore()
        payload = b"a\r\nb\xef\xbb\xbf"
        ref = store.put("raw/bytes", payload)
        self.assertEqual(store.get(ref.file_id), payload)

    def test_list_filters_by_prefix(self):
        store = MemoryStore()
        store.put("skytale/one.md", b"1")
        store.put("other/two.md", b"2")
        ids = [item.file_id for item in store.list(prefix="skytale/")]
        self.assertEqual(len(ids), 1)

    def test_unknown_id_raises(self):
        with self.assertRaises(KeyError):
            MemoryStore().get("mem-9999")


class BrokenStore(MemoryStore):
    """Adapter bug: reports the wrong hash."""

    def put(self, name, data):
        ref = super().put(name, data)
        return ObjectRef(file_id=ref.file_id, size=ref.size, sha256="0" * 64)


class LossyStore(MemoryStore):
    """Adapter bug: transcode on read."""

    def get(self, file_id):
        return super().get(file_id).replace(b"\r\n", b"\n")


class ContractFailureTests(unittest.TestCase):
    def test_wrong_hash_is_rejected(self):
        with self.assertRaises(ContractError):
            verify_roundtrip(BrokenStore(), "skytale/context.md", b"x\r\n")

    def test_lossy_read_is_rejected(self):
        with self.assertRaises(ContractError):
            verify_roundtrip(LossyStore(), "skytale/context.md", b"x\r\n")

    def test_empty_id_is_rejected(self):
        class NoIdStore(MemoryStore):
            def put(self, name, data):
                ref = super().put(name, data)
                return ObjectRef(file_id="", size=ref.size, sha256=ref.sha256)

        with self.assertRaises(ContractError):
            verify_roundtrip(NoIdStore(), "x/y", b"z")


if __name__ == "__main__":
    unittest.main()
