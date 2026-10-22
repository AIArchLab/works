"""Resume verifier: check a claim against the evidence route that supports it.

A handoff is not complete because the documents were readable. Each claim must
name the route that produced it, and the verifier refuses a claim whose route is
missing, malformed, or a different route wearing the same word.

Routes are not interchangeable:

    offline_gate      local artifacts are self-consistent
    storage_readback  the bytes exist in a store and hash as recorded
    event_readback    a check-out / check-in row was read back with its columns
    dispatcher_receipt a dispatcher accepted and processed the request
    wake              a new conversation was actually handed the prompt

A direct API write never counts as a dispatcher receipt; a receipt never counts
as a wake; a wake never counts as a check-in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROUTES = ("offline_gate", "storage_readback", "event_readback",
          "dispatcher_receipt", "wake")

#: What each claim requires. A claim passes only when every listed route is
#: present with satisfied fields.
CLAIM_ROUTES: dict[str, tuple[str, ...]] = {
    "handoff_completed": ("offline_gate", "storage_readback", "event_readback"),
    "resume_completed": ("wake", "event_readback"),
    "delivery_verified": ("dispatcher_receipt",),
}

REQUIRED_FIELDS = {
    "offline_gate": ("checks_passed",),
    "storage_readback": ("file_id", "size", "sha256", "normalized_sha256", "artifact"),
    "event_readback": ("event_id", "role", "columns"),
    "dispatcher_receipt": ("request_id", "agent", "source", "status"),
    "wake": ("session_id", "delivered_at"),
}

EVENT_ROLES = ("check_out", "check_in")


@dataclass
class Finding:
    code: str
    ok: bool
    detail: str = ""


@dataclass
class VerifyReport:
    findings: list[Finding] = field(default_factory=list)

    def add(self, code: str, ok: bool, detail: str = "") -> None:
        self.findings.append(Finding(code, bool(ok), detail))

    @property
    def ok(self) -> bool:
        return all(f.ok for f in self.findings)

    @property
    def failures(self) -> list[Finding]:
        return [f for f in self.findings if not f.ok]

    def summary(self) -> str:
        if self.ok:
            return (f"PASS: {len(self.findings)} evidence checks passed for the claims "
                    f"that were made; nothing outside those claims is implied.")
        lines = [f"FAIL: {len(self.failures)}/{len(self.findings)} evidence checks failed"]
        lines += [f"- {f.code}: {f.detail}" for f in self.failures]
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "findings": [f.__dict__ for f in self.findings]}


def _iso_with_tz(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _index_hashes(run_dir: Path) -> dict[str, str]:
    """Map artifact kind ('context'/'summary') to the index's LF_UTF8_v1 hash."""
    try:
        index = json.loads((run_dir / "index.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    for kind in ("context", "summary"):
        digest = (index.get(kind) or {}).get("sha256")
        if digest:
            out[kind] = digest
    return out


def verify_evidence(run_dir: str | Path, evidence_path: str | Path) -> VerifyReport:
    run_dir = Path(run_dir)
    report = VerifyReport()

    try:
        evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        report.add("EVD-000", False, f"cannot read evidence file: {exc}")
        return report
    except json.JSONDecodeError as exc:
        report.add("EVD-000", False, f"evidence is not valid JSON: {exc}")
        return report

    index = {}
    try:
        index = json.loads((run_dir / "index.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        report.add("EVD-001", False, "index.json unreadable; cannot bind evidence to a generation")
    else:
        report.add("EVD-001", evidence.get("generation_id") == index.get("generation_id"),
                   f"generation mismatch: evidence={evidence.get('generation_id')!r} "
                   f"index={index.get('generation_id')!r}")
        report.add("EVD-002", evidence.get("agent_name") == index.get("agent_name"),
                   "agent mismatch between evidence and index")

    items = evidence.get("items")
    if not isinstance(items, list) or not items:
        report.add("EVD-003", False, "evidence.items must be a non-empty list")
        return report

    by_route: dict[str, list[dict[str, Any]]] = {}
    index_hashes = _index_hashes(run_dir)

    for position, item in enumerate(items, 1):
        tag = f"item {position}"
        if not isinstance(item, dict):
            report.add(f"EVD-010-{position}", False, f"{tag} is not an object")
            continue
        route = item.get("route")
        report.add(f"EVD-011-{position}", route in ROUTES,
                   f"{tag} has unknown route {route!r}; allowed={ROUTES}")
        if route not in ROUTES:
            continue
        by_route.setdefault(route, []).append(item)

        report.add(f"EVD-012-{position}", _iso_with_tz(item.get("recorded_at")),
                   f"{tag} recorded_at must be ISO 8601 with a timezone")
        missing = [f for f in REQUIRED_FIELDS[route] if item.get(f) in (None, "", [])]
        report.add(f"EVD-013-{position}", not missing,
                   f"{tag} ({route}) missing fields: {missing}")

        if route == "storage_readback":
            artifact = item.get("artifact")
            expected = index_hashes.get(str(artifact))
            report.add(f"EVD-014-{position}", expected is not None,
                       f"{tag} names an artifact not bound by the index: {artifact!r}")
            if expected is not None:
                report.add(f"EVD-015-{position}", item.get("normalized_sha256") == expected,
                           f"{tag} normalized hash does not match the index for {artifact}")
            raw = item.get("sha256")
            report.add(f"EVD-016-{position}", isinstance(raw, str) and len(raw) == 64,
                       f"{tag} sha256 must be a 64-char raw-byte digest")
            report.add(f"EVD-017-{position}", isinstance(item.get("size"), int)
                       and item["size"] >= 0, f"{tag} size must be a non-negative integer")

        if route == "event_readback":
            report.add(f"EVD-018-{position}", item.get("role") in EVENT_ROLES,
                       f"{tag} role must be one of {EVENT_ROLES}, got {item.get('role')!r}")
            columns = item.get("columns")
            report.add(f"EVD-019-{position}", isinstance(columns, dict) and len(columns) >= 5,
                       f"{tag} columns must be an object with the read-back values")

        if route == "dispatcher_receipt":
            report.add(f"EVD-020-{position}", item.get("status") == "PROCESSED",
                       f"{tag} dispatcher receipt must be PROCESSED, got {item.get('status')!r}")
            request_id = str(item.get("request_id", ""))
            report.add(f"EVD-021-{position}",
                       request_id.endswith("_check_out") or request_id.endswith("_check_in"),
                       f"{tag} request_id must name a check_out or check_in event")

        if route == "wake":
            report.add(f"EVD-022-{position}", _iso_with_tz(item.get("delivered_at")),
                       f"{tag} delivered_at must be ISO 8601 with a timezone")

    # A handoff needs two independent events, read back on their own route.
    roles = {str(item.get("role")) for item in by_route.get("event_readback", [])}
    for role in EVENT_ROLES:
        report.add(f"EVD-030-{role}", role in roles,
                   f"no event_readback item with role={role}")

    for route, group in by_route.items():
        identities = {(item.get("file_id") or item.get("event_id") or
                       item.get("request_id") or item.get("session_id")) for item in group}
        report.add(f"EVD-040-{route}", len(identities) == len(group),
                   f"route {route} has conflicting items for the same identity: {identities}")

    claims = evidence.get("claims") or []
    report.add("EVD-050", isinstance(claims, list), "claims must be a list when present")
    if isinstance(claims, list):
        for claim in claims:
            name = claim.get("name") if isinstance(claim, dict) else claim
            required = CLAIM_ROUTES.get(str(name))
            report.add(f"EVD-051-{name}", required is not None,
                       f"unknown claim {name!r}; allowed={tuple(CLAIM_ROUTES)}")
            if required is None:
                continue
            present = [route for route in required if by_route.get(route)]
            report.add(f"EVD-052-{name}", len(present) == len(required),
                       f"claim {name!r} needs routes {required}, present={present}")

    return report
