# Changelog

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
