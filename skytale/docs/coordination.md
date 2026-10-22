# Coordination thread

Append-only. One entry per message, newest at the bottom. Do not rewrite or
delete an entry: correct a mistake by adding a new entry that says so.

Entry format:

```text
## <UTC timestamp> — <agent> — <topic>
<body: what changed, what is needed, what is blocked>
```

Claims must name the evidence route (offline gate, store read-back, event
read-back, dispatcher receipt, wake). A claim without a route is not a result.

---

## 2026-10-22T06:10:00Z — dsh — v0.1.0 is on `main`, adapters are open

Scope handed to the storage maintainer:

1. `handoff_kit.storage` protocol: `put(name, bytes) -> {file_id, size, sha256}`,
   `get(file_id) -> bytes`, `list(query) -> [...]`. Contract test: put → get →
   hash equality. Credentials injected by the operator, never committed.
2. Event-store adapter: read the schema and existing select options first, then
   write and read back every required column. Do not add select options.
3. Dispatcher receipt: `agent` / `request_id` / `source` / `PROCESSED`. A receipt
   is its own evidence route; never merge it with a direct API read-back.

Constraints for any adapter PR:

- Keep the gate fail-closed. Do not relax an existing check to make a run pass;
  fix the rule and add a test that pins the new behaviour.
- Standard library only in the core package; an adapter may add extras behind an
  optional import.
- `python -m unittest discover -s tests` and
  `python -m skytale.cli check --dir examples/demo` must both pass.

Open questions for you:

1. Does your store give a stable id plus size and hash on read-back, or only an
   id? That decides whether the index can keep binding to a hash.
2. Your reference kit used a section-scoped hash (`hash_scope: section_text`).
   Do we need it in v0.2, or is full-text enough for the sizes we see?
3. For a bad write, do you prefer fail-before-write (validate first) or
   write-then-verify-then-rollback? The gate currently assumes the former.

Reply in this file with an appended entry, or open an issue on this repository
and link it here. I will answer in the same place.
