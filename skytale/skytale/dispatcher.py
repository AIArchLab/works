"""Dispatcher receipts are not direct-API, delivery or recovery evidence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


class ReceiptVerificationError(ValueError):
    """Absent or mismatched dispatcher receipt."""


@dataclass(frozen=True)
class DispatchRequest:
    agent: str
    request_id: str
    source: str


@dataclass(frozen=True)
class DispatcherReceipt:
    agent: str
    request_id: str
    source: str
    status: str
    route: str = "dispatcher_receipt"


def verify_receipt(payload: Mapping[str, str], expected: DispatchRequest) -> DispatcherReceipt:
    for field in ("agent", "request_id", "source"):
        wanted = getattr(expected, field)
        if not isinstance(wanted, str) or not wanted.strip() or payload.get(field) != wanted:
            raise ReceiptVerificationError(f"missing or mismatched receipt {field}")
    if payload.get("status") != "PROCESSED":
        raise ReceiptVerificationError("dispatcher has not returned PROCESSED")
    return DispatcherReceipt(expected.agent, expected.request_id, expected.source, "PROCESSED")


class DispatcherClient(Protocol):
    def read_receipt(self, request_id: str) -> Mapping[str, str]: ...


class DispatcherAdapter:
    def __init__(self, client: DispatcherClient):
        self.client = client

    def readback(self, expected: DispatchRequest) -> DispatcherReceipt:
        """Fetch the actual dispatcher response; caller cannot substitute a write ack."""
        return verify_receipt(self.client.read_receipt(expected.request_id), expected)
