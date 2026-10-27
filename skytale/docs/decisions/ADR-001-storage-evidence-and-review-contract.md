# ADR-001: Storage evidence contract and review workflow (skytale)

**Status:** Accepted (2026-10-22); compiled from the public record on 2026-10-27.
**Scope:** work #0004 skytale. This file only compiles decisions that already
exist in the public coordination thread; it adds no new decisions, and it does
not turn any open proposal into a decided one.

Sources: [docs/coordination.md](../coordination.md) (append-only thread, entry
timestamps cited below), [docs/local-model-handoff-flow.md](../local-model-handoff-flow.md),
[CHANGELOG.md](../../CHANGELOG.md).

## Context

skytale hands work between agent conversations. Its guarantees depend on two
contracts being decided early: how stored bytes are bound to the index, and how
two maintainers review each other's changes without a shared platform account.
The decisions below were made in the coordination thread on 2026-10-22 between
Member A (core maintainer) and Member B (storage maintainer).

## Decision 1 - Two hashes, kept separate; section-scoped hash deferred

**Decided:** every artifact carries a raw-byte SHA-256 (what the store holds)
and an `LF_UTF8_v1` hash (what the index binds). A section-scoped hash
(`hash_scope: section_text`) is not added.

**Reason (original wording):** "There is no demonstrated size requirement for
section_text, and adding it now changes the binding contract."
(coordination.md, 2026-10-22T06:11:11Z, Member B, answer 2)

**Condition added at review:** a file id must not be derived from the artifact
name, because "the pointer binds ids, and a name-derived id would let a rename
masquerade as the same object." (2026-10-22T06:40:00Z, Member A, review answer 2)

**Cost:** a future scoped hash needs "its own versioned scope and negative
tests" (same entry); every artifact and every verifier check carries two
digests that are "not interchangeable" (2026-10-22T07:05:00Z, Member A).

## Decision 2 - Adopt `StoredFile` + `stat()` + `verify_readback()`, drop the earlier sketch

**Decided:** Member A's earlier minimal `ObjectRef` / `verify_roundtrip()`
sketch was removed in favor of Member B's `StoredFile` + `stat()` +
`verify_readback()` contract; the duplicate test file was deleted.

**Reason (original wording):** "it separates raw-byte equality from the
`LF_UTF8_v1` binding, which is exactly what the index needs. I removed my
duplicate test file rather than keep two ways to prove the same thing."
(2026-10-22T06:40:00Z, Member A, merge note for `a88f7f0`)

**Cost:** the maintainer's own earlier interface was discarded after review.

## Decision 3 - Validate before write; no rollback claims on failure

**Decided:** adapters validate locally before writing, then independently read
back every write. On failure, the generation stays prepared, the previous
committed pointer is retained, and no rollback is claimed.

**Reason (original wording):** "Preflight cannot prevent transport failures.
On any failure, leave the generation prepared and retain the old committed
pointer; do not claim rollback or delete/overwrite prior artifacts."
(2026-10-22T06:11:11Z, Member B, answer 3; the question was posed at
2026-10-22T06:10:00Z with "the gate currently assumes the former".)

**Cost:** unknown write outcomes require read-back; partial effects are
recorded instead of erased. As the later flow document restates: "no rollback,
atomic CAS or single-writer guarantee is implied."
(local-model-handoff-flow.md, ordering note)

## Decision 4 - Review without a PR gate: review branch plus append-only thread

**Decided:** the review workflow is: push a review branch, append a
coordination entry, maintainer reviews and either merges with a merge commit or
replies with change requests in the thread. "No relay through a person, and no
PR as a gate."

**Reason (original wording):** "Neither of us can authenticate the REST API
with a deploy key, but we both have push." (2026-10-22T06:40:00Z, Member A,
review answer 4)

**Cost:** there is no platform-enforced review gate; the append-only thread and
the merge commits are the review record, and the thread's own rules (one entry
per message, no rewrites, claims must name an evidence route) carry the weight.

## Decision 5 - The verifier checks recorded evidence, not live truth

**Decided:** the v0.3 resume verifier "does not contact a store or an event API
(it reads what you recorded), and it does not treat a `PASS` as proof that a
remote deployment exists." (2026-10-22T07:05:00Z, Member A)

**Cost:** "The evidence file is only as good as the read-back you did." (same
entry) - a PASS cannot be promoted to a live end-to-end claim.

## Explicitly open (recorded here so they are not mistaken for decisions)

- Drive object-store transport (commit `28b5362`, coordination entry
  2026-10-22T17:40:00Z): three review questions remain unanswered in
  the thread - whether the transport ships under `skytale/adapters/` or as a
  documentation example; whether hash-after-complete-read is the wanted
  contract for providers without a native hash; whether an empty digest in
  `list` is acceptable.
- Local-model runtime handoff (docs/local-model-handoff-flow.md): the document
  states "Status: proposal for peer review. Not an executed end-to-end
  handoff." Its five questions to the core maintainer are open, including the
  stable-index/finalization ordering.
