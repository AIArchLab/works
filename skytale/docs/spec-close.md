# Close spec (v1.0)

Trigger: an explicit handoff command. Ordinary discussion does not close a
generation.

## 1. Generation

```text
YYYYMMDDTHHMMSSZ_<12 lowercase hex>
```

A technical retry of the same event keeps the same generation, file ids and
request ids. A content correction creates a new generation and records
`repair_of`.

## 2. Rebuild the record

Rebuild the whole conversation, not only the last turn.

```text
<agent>_handoff_context_<generation>.md
<agent>_handoff_summary_<generation>.md
<agent>_handoff_index_<generation>.json
```

Context must cover: goal and business background; latest decisions and reasons;
role, access and authorization boundary; last completed position and official
artifacts; verified results, failures and corrections; unresolved work, schedule
and next action; source coverage and unavailable scope.

Summary must cover: key timeline and outcomes; completed vs unfinished; official
artifacts and next action; coverage limitations.

## 3. Storage and hashes

Store the three files in the agent's memory store only after the content is
final. Read them back and verify name, parent, size and bytes. Compute SHA-256
with `LF_UTF8_v1`: remove a leading UTF-8 BOM, convert CRLF/CR to LF, do not
strip, do not append a trailing newline.

Fill the index with the real file ids, parent id, hash and check-out event id.
Initial state is `prepared`; it becomes `committed` only after storage and
check-out are verified.

## 4. Check-out event

Use the existing event store; do not create a new database. Record: name,
owner, state, actual event time, a note carrying `action: check_out`,
`handoff_id`, `request_id: <agent>_<generation>_check_out` and a trigger reason,
plus a source link to the committed index. Read back every column after writing.
Never prefill a time that has not occurred.

## 5. Committed pointer

Only after storage and check-out verification succeed, update the pointer
(`pointer.json`): generation, index/context/summary file ids, store id,
check-out event id, committed timestamp and verification method.

If a conditional write is unavailable, record the race window; do not claim
atomic CAS. If any step fails, keep the previous committed pointer and the
prepared state. Do not guess success.

## 6. Final reply

Include the committed index, the check-out event and the offline gate result,
plus the complete new-conversation prompt in the same reply. Remove all
placeholders. A gate PASS is an offline structure check only; remote read-back,
chat delivery and the new conversation's recovery/check-in are separate
acceptance items.

## 7. Boundaries

- The old conversation must not write the new conversation's check-in.
- Do not claim `resume_completed`, `handoff_completed` or `delivery_verified`
  without the corresponding evidence.
- Storage read-back, event-store direct API, dispatcher receipts, SDK wake and
  chat delivery are separate evidence routes; never substitute one for another.
