# Startup spec (v1.0)

Scope: a new conversation of an agent resuming a committed handoff.

## 1. Access boundary

Use only your own credentials. Never print, copy or borrow another agent's
secrets. Do not ask a human to resend data that is already committed.

## 2. Locate the generation

1. Read the close spec named by the handoff config.
2. Read the pointer in the store (`pointer.json` or the store's pointer object).
3. Accept only a committed generation whose agent, generation, index, context,
   summary and check-out event agree.
4. Never guess the latest generation from file names or modified time.

## 3. Read the generation

1. Read context in full, then summary in full. If truncated, fetch the rest in
   segments.
2. Verify file id, file name, parent (store id) and `LF_UTF8_v1` SHA-256 against
   the index.
3. Re-read the pointer after reading. If it changed, restart from the new
   generation.
4. Recover semantics — goal, last completed position, decisions, authorization,
   verified results, failures, unresolved work, next action. A hash match is not
   a semantic recovery.

## 4. Check-in

1. Read the event store schema and the agent's existing options first.
2. Read back the previous generation's check-out event.
3. Search for an existing check-in with `request_id = <agent>_<generation>_check_in`.
4. If absent, create the check-in yourself. If present, verify it; never create
   a duplicate, and never reuse another generation's event.
5. Read back every required column.

## 5. Resume work

Check the current time, today's check-in state and any pending acceptance item,
then resume the actual work from the recovered context. A scheduled job is not
an executed job; a pre-filled timestamp is not a delivery.

## 6. Evidence

Store the verified results and the read-back evidence in the agent's own memory
store. Report only verified results and genuinely unresolved items. Do not
report a handoff as complete merely because the documents were readable.
