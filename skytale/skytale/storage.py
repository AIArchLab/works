"""Injected object-store adapter and independent, fail-closed read-back.

Transport implementations own authentication. No provider SDK or credentials are
bundled. SHA-256 in StoredFile is over raw bytes, never normalized text.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from .core import sha256_lf_utf8_v1


class StorageVerificationError(ValueError):
    """Missing or inconsistent storage evidence."""


@dataclass(frozen=True)
class StoredFile:
    file_id: str
    name: str
    parent_id: str
    size: int
    sha256: str


class Storage(Protocol):
    def put(self, name: str, data: bytes) -> StoredFile: ...
    def get(self, file_id: str) -> bytes: ...
    def stat(self, file_id: str) -> StoredFile: ...
    def list(self, query: str = "") -> list[StoredFile]: ...


class ObjectStoreClient(Protocol):
    """Operator-supplied transport; errors must propagate, not become success."""
    def put_object(self, store_id: str, name: str, data: bytes) -> StoredFile: ...
    def get_object(self, store_id: str, file_id: str) -> bytes: ...
    def stat_object(self, store_id: str, file_id: str) -> StoredFile: ...
    def list_objects(self, store_id: str, query: str) -> list[StoredFile]: ...


class ObjectStoreAdapter:
    def __init__(self, client: ObjectStoreClient, store_id: str):
        if not isinstance(store_id, str) or not store_id.strip():
            raise ValueError("store_id is required")
        self.client, self.store_id = client, store_id

    def put(self, name: str, data: bytes) -> StoredFile:
        if not isinstance(name, str) or not name.strip() or not isinstance(data, bytes):
            raise ValueError("put requires a nonempty name and bytes")
        result = self.client.put_object(self.store_id, name, data)
        _check_metadata(result, result.file_id, name, self.store_id, data)
        return result

    def get(self, file_id: str) -> bytes:
        if not isinstance(file_id, str) or not file_id.strip():
            raise ValueError("file_id is required")
        data = self.client.get_object(self.store_id, file_id)
        if not isinstance(data, bytes):
            raise StorageVerificationError("get must return complete bytes")
        return data

    def stat(self, file_id: str) -> StoredFile:
        result = self.client.stat_object(self.store_id, file_id)
        if result.file_id != file_id or result.parent_id != self.store_id:
            raise StorageVerificationError("stat identity or parent mismatch")
        return result

    def list(self, query: str = "") -> list[StoredFile]:
        results = self.client.list_objects(self.store_id, query)
        ids = set()
        for item in results:
            if not item.file_id or item.parent_id != self.store_id or item.file_id in ids:
                raise StorageVerificationError("list contains invalid, foreign or duplicate ids")
            ids.add(item.file_id)
        return results


def _check_metadata(meta: StoredFile, file_id: str, name: str,
                    parent_id: str, data: bytes) -> None:
    if (not file_id or meta.file_id != file_id or meta.name != name
            or meta.parent_id != parent_id or type(meta.size) is not int
            or meta.size != len(data)
            or meta.sha256 != hashlib.sha256(data).hexdigest()):
        raise StorageVerificationError("file id/name/parent/size/raw hash mismatch")


@dataclass(frozen=True)
class StorageReadback:
    file: StoredFile
    normalized_sha256: str | None
    route: str = "storage_readback"


def verify_readback(store: Storage, expected: StoredFile, original: bytes,
                    *, normalized_sha256: str | None = None) -> StorageReadback:
    """Read metadata and complete bytes independently of the write response.

    A normalization-only match is insufficient: byte equality is mandatory.
    Optional LF_UTF8_v1 verification binds a text artifact to its index hash.
    This function neither commits a pointer nor proves a remote deployment.
    """
    _check_metadata(expected, expected.file_id, expected.name, expected.parent_id, original)
    actual = store.stat(expected.file_id)
    data = store.get(expected.file_id)
    _check_metadata(actual, expected.file_id, expected.name, expected.parent_id, data)
    if actual != expected or data != original:
        raise StorageVerificationError("read-back differs from the submitted bytes or metadata")
    digest = None
    if normalized_sha256 is not None:
        try:
            digest = sha256_lf_utf8_v1(data)
        except UnicodeDecodeError as exc:
            raise StorageVerificationError("artifact is not UTF-8") from exc
        if digest != normalized_sha256:
            raise StorageVerificationError("LF_UTF8_v1 hash mismatch")
    return StorageReadback(actual, digest)
