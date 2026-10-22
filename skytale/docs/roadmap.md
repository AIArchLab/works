# Roadmap

v0.1.0 ships the storage-agnostic core. Everything below is additive and must
keep the gate fail-closed.

## Division of labour

| Area | Owner |
|---|---|
| Core contract: generation, naming, `LF_UTF8_v1`, gate rules | core maintainer |
| Storage adapters (folder store / object store / opaque store id) | storage maintainer |
| Event-store adapter (generic event row: name/owner/state/time/note/source) | storage maintainer |
| Dispatcher receipts (`agent` / `request_id` / `source` / `PROCESSED`) | storage maintainer |
| Prompt renderer and recovery checklist | core maintainer |
| Resume verifier (recovery evidence against a committed generation) | core maintainer |
| CI and release packaging | core maintainer |

## v0.2 — adapters

- `skytale.storage` protocol: `put(name, bytes) -> {file_id, size, sha256}`,
  `get(file_id) -> bytes`, `list(query) -> [...]`.
- A reference adapter for an abstract object store. Credentials are always
  injected by the operator and never stored in the repo.
- Contract test every adapter must pass: put, get, hash equality.

## v0.3 — resume verifier

- `skytale resume-check --dir RUN --evidence evidence.json`
- The evidence file records: pointer re-read result, context/summary read-back
  hashes, previous check-out columns, new check-in columns, current time, and
  which route produced each item.
- Fails when a generation is mixed, an event is reused, or a claim has no route.

## v0.4 — multi-agent handoff

- Chain handoffs A to B to C with per-hop generations and a claim that is atomic
  outside the event store (the store stays the audit layer, not the lock).
- Explicit `repair_of` lineage for content corrections.

## Open questions

1. Should the pointer carry a monotonic version for compare-and-swap, or is a
   committed timestamp plus index id enough?
2. Section-scoped hashing (`hash_scope: section_text`) for very large contexts:
   worth the complexity?
3. Do we need signed envelopes (agent key), or is store-side permission enough?
