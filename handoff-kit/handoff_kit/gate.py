"""Offline gate: verify one handoff generation without touching the network.

The gate is deliberately conservative. It proves only that the local artifacts
are self-consistent: names, parent ids, LF_UTF8_v1 hashes, identity lines and
committed-state fields. It never proves that the same bytes exist remotely, that
a check-out event was written, or that a new conversation actually recovered.
Those are separate acceptance items and must be read back separately.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import AGENT_RE, GEN_RE, artifact_name, parse_generation, sha256_lf_utf8_v1

PLACEHOLDERS = ("{{", "TODO", "TBD", "<fill", "REPLACE_ME")
COMMIT_STATES = ("prepared", "committed")


@dataclass
class Check:
    code: str
    ok: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "ok": self.ok, "detail": self.detail}


@dataclass
class GateReport:
    checks: list[Check] = field(default_factory=list)

    def add(self, code: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(code, bool(ok), detail))

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def summary(self) -> str:
        total = len(self.checks)
        bad = len(self.failures)
        if not bad:
            return (f"PASS: {total} offline checks passed. Remote evidence (storage read-back, "
                    f"event read-back, new-conversation recovery) is still required and is not "
                    f"proven here.")
        lines = [f"FAIL: {bad}/{total} checks failed"]
        lines += [f"- {c.code}: {c.detail}" for c in self.failures]
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "checks": [c.as_dict() for c in self.checks]}


def _load_json(path: Path, report: GateReport, code: str) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        report.add(code, False, f"missing file: {path.name}")
    except json.JSONDecodeError as exc:
        report.add(code, False, f"{path.name} is not valid JSON: {exc}")
    return None


def _check_artifact(report: GateReport, run_dir: Path, cfg: dict[str, Any],
                    index: dict[str, Any], kind: str) -> None:
    prefix = kind.upper()
    agent = cfg["agent_name"]
    gen = index["generation_id"]
    meta = index.get(kind) or {}
    expected = artifact_name(agent, kind, gen)
    name = meta.get("file_name", "")
    report.add(f"{prefix}-001", name == expected, f"expected file name {expected}, got {name!r}")

    path = run_dir / name
    if not name or not path.is_file():
        report.add(f"{prefix}-002", False, f"{name!r} not found or not a file")
        return
    report.add(f"{prefix}-002", True, f"{name} present")

    raw = path.read_bytes()
    report.add(f"{prefix}-003", meta.get("parent_id") == cfg["store_id"],
               f"parent should be store_id={cfg['store_id']}, got {meta.get('parent_id')!r}")
    report.add(f"{prefix}-004", meta.get("normalization") == "LF_UTF8_v1",
               f"normalization should be LF_UTF8_v1, got {meta.get('normalization')!r}")
    digest = sha256_lf_utf8_v1(raw)
    report.add(f"{prefix}-005", meta.get("sha256") == digest,
               f"hash mismatch: index={meta.get('sha256')} computed={digest}")

    text = raw.decode("utf-8-sig") if raw.startswith(b"\xef\xbb\xbf") else raw.decode("utf-8")
    hits = [p for p in PLACEHOLDERS if p in text]
    report.add(f"{prefix}-006", not hits, f"body still contains placeholders: {hits}")

    identity_ok = f"agent_name: {agent}" in text and f"generation_id: {gen}" in text
    report.add(f"{prefix}-007", identity_ok,
               "body is missing the agent_name / generation_id identity lines")


def check_generation(run_dir: str | Path, config_path: str | Path | None = None) -> GateReport:
    """Verify a run directory. Returns a report; never raises for content errors."""
    run_dir = Path(run_dir)
    report = GateReport()

    cfg_path = Path(config_path) if config_path else run_dir / "agent_config.json"
    cfg = _load_json(cfg_path, report, "CFG-000")
    if cfg is None:
        return report

    agent = str(cfg.get("agent_name", ""))
    report.add("CFG-001", bool(AGENT_RE.match(agent)), f"invalid agent_name: {agent!r}")
    report.add("CFG-002", bool(str(cfg.get("store_id", "")).strip()), "store_id must not be empty")
    auth = str(cfg.get("authorization_reference", ""))
    report.add("CFG-003", bool(auth.strip()) and not any(p in auth for p in PLACEHOLDERS),
               "authorization_reference must not be empty or contain placeholders")

    index = _load_json(run_dir / "index.json", report, "IDX-001")
    if index is None:
        return report

    gen = str(index.get("generation_id", ""))
    report.add("IDX-002", index.get("agent_name") == agent,
               f"agent mismatch: index={index.get('agent_name')!r} config={agent!r}")
    ok_gen = bool(GEN_RE.match(gen))
    report.add("IDX-003", ok_gen, f"invalid generation id: {gen!r}")
    if ok_gen:
        try:
            parse_generation(gen)
        except ValueError as exc:
            report.add("IDX-003b", False, str(exc))
    report.add("IDX-004", index.get("handoff_id") == gen,
               f"handoff_id should equal generation_id, got {index.get('handoff_id')!r}")
    report.add("IDX-005", index.get("store_id") == cfg.get("store_id"),
               f"store mismatch: index={index.get('store_id')!r} config={cfg.get('store_id')!r}")
    state = index.get("commit_state")
    report.add("IDX-006", state in COMMIT_STATES,
               f"commit_state must be one of {COMMIT_STATES}, got {state!r}")
    report.add("IDX-007", index.get("checkin_request_id") == f"{agent}_{gen}_check_in",
               f"checkin_request_id should be {agent}_{gen}_check_in")

    checkout = index.get("checkout") or {}
    report.add("IDX-008", checkout.get("request_id") == f"{agent}_{gen}_check_out",
               "checkout.request_id mismatch")
    report.add("IDX-009", checkout.get("action") == "check_out", "checkout.action should be check_out")
    report.add("IDX-010", bool(str(checkout.get("verification_method", "")).strip()),
               "checkout.verification_method must not be empty")

    _check_artifact(report, run_dir, cfg, index, "context")
    _check_artifact(report, run_dir, cfg, index, "summary")

    if state == "committed":
        for kind in ("context", "summary"):
            meta = index.get(kind) or {}
            report.add(f"COM-{kind[:3].upper()}", bool(str(meta.get("file_id", "")).strip()),
                       f"{kind}.file_id must not be empty when committed")
        report.add("COM-IDX", bool(str(index.get("index_file_id", "")).strip()),
                   "index_file_id must not be empty when committed")

    pointer_path = run_dir / "pointer.json"
    if pointer_path.is_file():
        ptr = _load_json(pointer_path, report, "PTR-000") or {}
        report.add("PTR-001", ptr.get("generation_id") == gen,
                   f"pointer generation mismatch: {ptr.get('generation_id')!r}")
        report.add("PTR-002", ptr.get("index_file_id") == index.get("index_file_id"),
                   "pointer.index_file_id does not match the index")
        report.add("PTR-003", ptr.get("agent_name") == agent,
                   "pointer.agent_name does not match the config")
        stamp = str(ptr.get("committed_at", ""))
        try:
            datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            stamp_ok = True
        except ValueError:
            stamp_ok = False
        report.add("PTR-004", stamp_ok, f"pointer.committed_at is not ISO 8601: {stamp!r}")
        report.add("PTR-005", bool(str(ptr.get("verification_method", "")).strip()),
                   "pointer.verification_method must not be empty")

    return report


def render_prompt(cfg: dict[str, Any], index: dict[str, Any]) -> str:
    """Render the new-conversation prompt for one committed generation."""
    agent = cfg["agent_name"]
    gen = index["generation_id"]
    store = cfg["store_id"]
    auth = cfg["authorization_reference"]
    pointer_hint = cfg.get("pointer_hint", "the pointer file named by the handoff config")
    lines = [
        f"Resume the {agent} handoff. Start immediately; do not ask whether to begin.",
        f"1. Use only your own credentials: {auth}. Never print, copy or borrow another agent's secrets.",
        f"2. Read the startup spec ({cfg.get('startup_spec_ref', 'startup spec')}) and then the close "
        f"spec ({cfg.get('close_spec_ref', 'close spec')}) in full.",
        f"3. Read {pointer_hint}. Accept only a committed generation; the expected generation is {gen}. "
        f"Do not guess the latest by file name or modified time.",
        f"4. Read context first, then summary, both in full; fetch segments if truncated. Verify file id, "
        f"file name, parent (store {store}) and LF_UTF8_v1 SHA-256 against the index.",
        "5. Re-read the pointer after reading. If it changed, restart from the new generation.",
        f"6. Read back the previous check_out event, then search for an existing "
        f"{index.get('checkin_request_id')}; create your own check_in only if absent, and read back all "
        f"required columns. Do not reuse another generation's event.",
        "7. Check the current time, today's check-in state and pending acceptance items, then resume the "
        "actual work from the recovered context. A scheduled job is not an executed job.",
        f"8. Store the verified results and the read-back evidence in {store}. Report only verified results "
        f"and genuinely unresolved items. Dispatcher receipts, direct API read-back, SDK wake and chat "
        f"delivery are separate evidence routes; never let one stand in for another.",
    ]
    return "\n".join(lines) + "\n"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
