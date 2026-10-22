# Changelog

## 0.2.0 — 2026-10-22

- Storage contract with two hashes: raw-byte SHA-256 for what the store holds and
  `LF_UTF8_v1` for binding text to the index; independent read-back via
  `stat()` plus `get()`.
- Schema-first event adapter over six logical columns, with select-option
  validation and a retry rule that keeps the original event time.
- Dispatcher receipt verifier (`agent` / `request_id` / `source` /
  `PROCESSED`) as its own evidence route.
- `skytale verify`: an evidence file names a route per item; a claim passes only
  when every route it requires is present. Unknown routes, naive timestamps,
  index-hash mismatches and unknown claims fail closed.
- Example evidence file wired into CI.
- 64 standard-library unit tests.

## 0.1.0 — 2026-10-22

First public MVP.

- `core`: `LF_UTF8_v1` normalization and SHA-256, generation ids
  (`YYYYMMDDTHHMMSSZ_<12 hex>`), canonical artifact names.
- `gate`: 34 offline checks — config, index, identity, hash binding, committed
  state, pointer agreement.
- `cli`: `init`, `seal`, `check`, `prompt`, `hash`; exit code 1 on gate failure.
- Specs: `docs/spec-startup.md`, `docs/spec-close.md`.
- Docs: evidence routes and roadmap (core maintainer / storage maintainer).
- Example run with synthetic ids that passes the gate.
- 19 stdlib unit tests; GitHub Actions CI on Python 3.10 / 3.12.
