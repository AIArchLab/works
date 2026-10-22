"""Schema-first event adapter. Read-back proves a row, not resumed work.

The operator maps provider columns to these six logical columns. Search must be
complete (including pagination); the store is an audit layer, not a lock.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol
from urllib.parse import urlparse

from .core import AGENT_RE, parse_generation

COLUMNS = {"name": "text", "owner": "select", "state": "select",
           "time": "timestamp", "note": "json", "source": "url"}


class EventVerificationError(ValueError):
    """Fail closed on ambiguous, incomplete or incompatible event evidence."""


@dataclass(frozen=True)
class EventSchema:
    columns: Mapping[str, str]
    owner_options: tuple[str, ...]
    state_options: tuple[str, ...]


@dataclass(frozen=True)
class EventIntent:
    agent: str
    generation: str
    action: str
    owner: str
    state: str
    occurred_at: str
    source: str
    reason: str

    @property
    def request_id(self) -> str:
        return f"{self.agent}_{self.generation}_{self.action}"

    def columns(self) -> dict[str, str]:
        return {"name": self.request_id, "owner": self.owner, "state": self.state,
                "time": self.occurred_at, "source": self.source,
                "note": json.dumps({"action": self.action, "handoff_id": self.generation,
                                    "request_id": self.request_id, "reason": self.reason},
                                   sort_keys=True, separators=(",", ":"))}


@dataclass(frozen=True)
class EventRow:
    event_id: str
    columns: Mapping[str, str]


class EventStoreClient(Protocol):
    def read_schema(self) -> EventSchema: ...
    def find_by_request_id(self, request_id: str) -> list[EventRow]: ...
    def create(self, columns: Mapping[str, str]) -> str: ...
    def read(self, event_id: str) -> EventRow: ...


@dataclass(frozen=True)
class EventReadback:
    row: EventRow
    request_id: str
    reused: bool
    route: str = "event_store_readback"
    atomic_claim: bool = False


def _timestamp(text: str) -> datetime:
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone is required")
        return value.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError) as exc:
        raise EventVerificationError("invalid timezone-aware event timestamp") from exc


def _note(text: str) -> dict:
    try:
        # Duplicate JSON keys must not silently override request identity.
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate note key")
                result[key] = value
            return result
        value = json.loads(text, object_pairs_hook=pairs)
        if not isinstance(value, dict):
            raise ValueError("note must be an object")
        return value
    except (ValueError, TypeError) as exc:
        raise EventVerificationError("invalid structured event note") from exc


class EventStoreAdapter:
    def __init__(self, client: EventStoreClient,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.client, self.clock = client, clock

    def _preflight(self, intent: EventIntent) -> None:
        schema = self.client.read_schema()
        if any(schema.columns.get(k) != v for k, v in COLUMNS.items()):
            raise EventVerificationError("required event column missing or incompatible")
        if intent.owner not in schema.owner_options or intent.state not in schema.state_options:
            raise EventVerificationError("owner/state is not an existing option")
        if not AGENT_RE.fullmatch(intent.agent) or intent.action not in ("check_in", "check_out"):
            raise EventVerificationError("invalid agent or action")
        try:
            generation_time = parse_generation(intent.generation)
        except ValueError as exc:
            raise EventVerificationError("invalid generation") from exc
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise EventVerificationError("clock must be timezone-aware")
        actual_time = _timestamp(intent.occurred_at)
        if not generation_time <= actual_time <= now:
            raise EventVerificationError("event time predates generation or is in the future")
        source = urlparse(intent.source)
        if (source.scheme not in ("https", "http") or not source.netloc
                or not isinstance(intent.reason, str) or not intent.reason.strip()):
            raise EventVerificationError("source link and trigger reason are required")

    def _verify(self, event_id: str, intent: EventIntent, reused: bool) -> EventReadback:
        row = self.client.read(event_id)
        expected = intent.columns()
        if not event_id or row.event_id != event_id or any(k not in row.columns for k in COLUMNS):
            raise EventVerificationError("event id or required read-back column missing")
        for key in COLUMNS:
            actual, wanted = row.columns[key], expected[key]
            if key == "note":
                equal = _note(actual) == _note(wanted)
            elif key == "time":
                equal = _timestamp(actual) == _timestamp(wanted)
            else:
                equal = actual == wanted
            if not equal:
                raise EventVerificationError(f"event read-back column mismatch: {key}")
        return EventReadback(row, intent.request_id, reused)

    def verify(self, event_id: str, intent: EventIntent) -> EventReadback:
        """Read-only verification, e.g. the previous generation's check-out."""
        self._preflight(intent)
        return self._verify(event_id, intent, True)

    def ensure(self, intent: EventIntent) -> EventReadback:
        """Reuse one exact match or create and re-read all six columns.

        Retrying must retain the complete original intent, including actual time.
        The caller, not this library, owns authority to check in or out. In
        particular the closing session must not create the next session's check-in.
        """
        self._preflight(intent)
        matches = self.client.find_by_request_id(intent.request_id)
        if len(matches) > 1:
            raise EventVerificationError("duplicate request_id; no arbitrary winner")
        if matches:
            return self._verify(matches[0].event_id, intent, True)
        event_id = self.client.create(intent.columns())
        evidence = self._verify(event_id, intent, False)
        matches = self.client.find_by_request_id(intent.request_id)
        if len(matches) != 1 or matches[0].event_id != event_id:
            raise EventVerificationError("ambiguous or missing event after create")
        return evidence
