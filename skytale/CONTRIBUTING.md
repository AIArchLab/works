# Contributing

This repo is maintained by two maintainers: the **core maintainer** (contract,
gate, CLI) and the **storage maintainer** (adapters, event store, dispatcher
receipts). Keep it small and verifiable.

## Ground rules

1. **No secrets, no internal ids.** No tokens, no organisation-specific folder
   ids, no member names in code or examples. Adapters take opaque store ids.
2. **Standard library only** for the core package. Adapters may add extras, but
   they must live behind an optional import.
3. **Tests before claims.** `python -m unittest discover -s tests` must pass.
   A change that only "looks right" is not done.
4. **The gate stays fail-closed.** New checks may be added; existing checks may
   not be relaxed to make a run pass. If a check is wrong, fix the rule and add a
   test that pins the new behaviour.
5. **Never claim remote evidence.** The gate is offline. Read-back of storage,
   event rows, dispatcher receipts and wakes are separate routes and must be
   recorded as such.

## Workflow

```bash
git switch -c feat/<short-topic>
python -m unittest discover -s tests
python -m skytale.cli check --dir examples/demo
git commit -m "feat: <topic>"
```

- Branch names: `feat/...`, `fix/...`, `docs/...`, `chore/...`.
- Commit author: the member's own identity. Do not commit under someone else's
  name.
- Versioning: `v0.x` is a draft, `v1.0` is a delivery. Never rewrite a published
  version; add a new one and note it in `CHANGELOG.md`.
- When a run needs a content correction, create a new generation and record
  `repair_of`; never edit a committed generation in place.

## Review

Changes to `skytale/gate.py` need a second pair of eyes from the other
maintainer, because that file defines what "verified" means.
