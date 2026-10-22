"""Storage contract: the one interface a store adapter must satisfy.

The gate never talks to a store. It only checks that local artifacts agree with
the index they ship with. A store plugs in here, and a store adapter is
responsible for returning an id, a size and a raw SHA-256 on every write and on
every read, so that a later read-back can be compared with what was recorded.

Rules for adapters:

1. ``put`` returns an ``ObjectRef`` whose ``size`` and ``sha256`` describe the
   bytes the store now holds. If the store cannot report a hash, the adapter must
   compute it locally after the write and read the object back to confirm.
2. ``get`` returns exactly the bytes written. No transcoding, no newline
   rewriting: bytes are bytes. Text normalization (``LF_UTF8_v1``) is applied by
   the caller, not by the store.
3. ``list`` is prefix-based and deterministic in ordering for a given store
   state; adapters that paginate must keep returning everything for a prefix.
4. Adapters never read credentials from a fixed local path. The operator injects
   them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ObjectRef:
    """What a store reports about one stored object."""

    file_id: str
    size: int
    sha256: str


@runtime_checkable
class Store(Protocol):
    """Minimal object store used by a handoff run."""

    def put(self, name: str, data: bytes) -> ObjectRef: ...

    def get(self, file_id: str) -> bytes: ...

    def list(self, prefix: str = "") -> list[ObjectRef]: ...


class ContractError(AssertionError):
    """Raised when an adapter violates the storage contract."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_roundtrip(store: Store, name: str, data: bytes) -> ObjectRef:
    """Exercise put -> get -> list on one payload and fail loudly on any drift.

    Adapters call this from their own tests; CI runs it against an in-memory
    reference store so the contract itself cannot rot.
    """
    ref = store.put(name, data)
    if not ref.file_id:
        raise ContractError("put() returned an empty file_id")
    if ref.size != len(data):
        raise ContractError(f"size mismatch: store={ref.size} payload={len(data)}")
    if ref.sha256 != _digest(data):
        raise ContractError(f"hash mismatch: store={ref.sha256} payload={_digest(data)}")

    back = store.get(ref.file_id)
    if back != data:
        raise ContractError("get() returned different bytes than put() stored")

    listed = store.list(prefix=name.split("/")[0])
    ids = [item.file_id for item in listed]
    if ref.file_id not in ids:
        raise ContractError(f"list() did not return {ref.file_id!r} for the prefix")

    for item in listed:
        if item.file_id == ref.file_id and (item.size != ref.size or item.sha256 != ref.sha256):
            raise ContractError("list() reported a different size or hash than put()")
    return ref


class MemoryStore:
    """Reference store: dict-backed, used by the contract test and examples."""

    def __init__(self) -> None:
        self._objects: dict[str, tuple[str, bytes]] = {}
        self._counter = 0

    def put(self, name: str, data: bytes) -> ObjectRef:
        self._counter += 1
        file_id = f"mem-{self._counter:04d}"
        self._objects[file_id] = (name, data)
        return ObjectRef(file_id=file_id, size=len(data), sha256=_digest(data))

    def get(self, file_id: str) -> bytes:
        try:
            return self._objects[file_id][1]
        except KeyError as exc:
            raise KeyError(f"unknown file_id: {file_id}") from exc

    def list(self, prefix: str = "") -> list[ObjectRef]:
        return [
            ObjectRef(file_id=fid, size=len(data), sha256=_digest(data))
            for fid, (name, data) in self._objects.items()
            if name.startswith(prefix)
        ]
