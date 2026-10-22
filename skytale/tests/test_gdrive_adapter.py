"""Contract tests for the injected Drive transport.

The transport is synthetic. Passing these tests does not establish a live
provider read-back; that needs an authorized client outside the repository.
"""
import hashlib
import json
import unittest
from urllib.parse import parse_qs, urlparse

from skytale.storage import (ObjectStoreAdapter, StorageVerificationError,
                             verify_readback)
from skytale.adapters.gdrive import GDriveClient, GDriveError


def _parse_multipart(body: bytes):
    boundary = body.split(b"\r\n", 1)[0][2:]
    meta = media = None
    for part in body.split(b"--" + boundary):
        if b"application/json" in part:
            meta = json.loads(part.split(b"\r\n\r\n", 1)[1].strip())
        elif b"application/octet-stream" in part:
            media = part.split(b"\r\n\r\n", 1)[1]
            if media.endswith(b"\r\n"):
                media = media[:-2]
    return meta, media


class FakeDrive:
    def __init__(self, page_size=2):
        self.files = {}
        self.page_size = page_size
        self.fail_status = None
        self.parent_override = {}

    def __call__(self, method, url, headers, body=None):
        if self.fail_status:
            return self.fail_status, b'{"error":"denied"}'
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if method == "POST" and "/upload/drive/v3/files" in url:
            meta, media = _parse_multipart(body)
            file_id = f"fake-{len(self.files) + 1}"
            self.files[file_id] = {
                "name": meta["name"],
                "parents": meta["parents"],
                "data": media,
            }
            return 200, json.dumps({
                "id": file_id,
                "name": meta["name"],
                "parents": meta["parents"],
                "size": len(media),
            }).encode()
        if method == "GET" and "alt=media" in url:
            file_id = parsed.path.rsplit("/", 1)[-1]
            return 200, self.files[file_id]["data"]
        if method == "GET" and "/files/" in url:
            file_id = parsed.path.rsplit("/", 1)[-1]
            item = self.files[file_id]
            parents = self.parent_override.get(file_id, item["parents"])
            return 200, json.dumps({
                "id": file_id,
                "name": item["name"],
                "parents": parents,
                "size": len(item["data"]),
            }).encode()
        if method == "GET" and "/files" in url:
            # Discovery listing, paginated in file-id order.
            q = (params.get("q") or [""])[0]
            needle = ""
            marker = "name contains '"
            if marker in q:
                needle = q.split(marker, 1)[1].rsplit("'", 1)[0]
            items = [
                {
                    "id": file_id,
                    "name": item["name"],
                    "parents": self.parent_override.get(file_id, item["parents"]),
                    "size": len(item["data"]),
                }
                for file_id, item in sorted(self.files.items())
                if needle in item["name"]
            ]
            start = int((params.get("pageToken") or ["0"])[0])
            page = items[start:start + self.page_size]
            payload = {"files": page}
            if start + self.page_size < len(items):
                payload["nextPageToken"] = str(start + self.page_size)
            return 200, json.dumps(payload).encode()
        return 404, b'{"error":"not found"}'


class GDriveContractTests(unittest.TestCase):
    def setUp(self):
        self.http = FakeDrive()
        self.client = GDriveClient(self.http, lambda: "test-token")
        self.store = ObjectStoreAdapter(self.client, "store-folder")
        self.raw = b"\xef\xbb\xbfcontext\r\nno trailing newline"
        self.meta = self.store.put("context.md", self.raw)

    def test_put_is_read_back_and_both_hashes_match(self):
        self.assertEqual(self.store.get(self.meta.file_id), self.raw)
        self.assertEqual(self.meta.size, len(self.raw))
        self.assertEqual(self.meta.sha256, hashlib.sha256(self.raw).hexdigest())
        normalized = hashlib.sha256(b"context\nno trailing newline").hexdigest()
        evidence = verify_readback(self.store, self.meta, self.raw,
                                   normalized_sha256=normalized)
        self.assertEqual(evidence.route, "storage_readback")
        self.assertEqual(evidence.normalized_sha256, normalized)
        self.assertNotEqual(self.meta.sha256, normalized)

    def test_upload_ack_is_not_trusted(self):
        # Mutating stored bytes after the acknowledged write must fail read-back.
        self.http.files[self.meta.file_id]["data"] = self.raw[:-1]
        with self.assertRaises(StorageVerificationError):
            verify_readback(self.store, self.meta, self.raw)

    def test_http_error_is_raised_not_converted(self):
        self.http.fail_status = 403
        with self.assertRaises(GDriveError):
            self.store.get(self.meta.file_id)

    def test_missing_token_is_rejected(self):
        client = GDriveClient(lambda *a: (200, b"{}"), lambda: "")
        with self.assertRaises(ValueError):
            client.put_object("store-folder", "x.md", b"x")

    def test_list_paginates_and_scopes_to_store(self):
        for i in range(3):
            self.store.put(f"artifact-{i}.md", b"body")
        listed = self.store.list("artifact")
        self.assertEqual(len(listed), 3)
        self.assertTrue(all(item.parent_id == "store-folder" for item in listed))

    def test_list_foreign_parent_fails_closed(self):
        self.http.parent_override[self.meta.file_id] = ["elsewhere"]
        with self.assertRaises(StorageVerificationError):
            self.store.list("")

    def test_stat_parent_mismatch_fails_closed(self):
        self.http.parent_override[self.meta.file_id] = ["elsewhere"]
        with self.assertRaises(StorageVerificationError):
            self.store.stat(self.meta.file_id)

    def test_truncated_read_fails(self):
        self.http.files[self.meta.file_id]["data"] = b""
        with self.assertRaises(StorageVerificationError):
            verify_readback(self.store, self.meta, self.raw)


if __name__ == "__main__":
    unittest.main()
