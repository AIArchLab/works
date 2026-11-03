# Product Positioning and Selling-Point Collaboration Draft

Status: working draft; market selling points are finalized by peers convened by the Founder. This file records the technical positioning and evidence first, and **does not announce a slogan, target customers, or market leadership on anyone's behalf**.

## The technical architect's positioning proposal

Looking up from a "session handoff plugin", it now carries three distinct responsibilities:

1. **State continuity**: task checkpoints, revisions, and deliverables do not depend on a single conversation.
2. **Execution ownership**: who submits inside the Broker, when they hand over, and who continues after expiry are decided by executable adjudication.
3. **Evidence continuity**: handoff content, verification, ACK, and subsequent submissions leave checkable records.

Working description: **a cross-runtime task continuity control layer**. It is an architectural judgment, not a validated market category. Handoff is one of its operations, not the whole product value.

## Peer finalization area

Update this file directly via commit/PR, leaving author, date, basis, and status. No one has been marked as picking up this section on their behalf.

| Item | Content to fill in |
|---|---|
| First-priority buyer | Whose cost or failure is most worth solving first? |
| One public sentence | The outcome a buyer immediately understands, without internal jargon |
| Three main selling points | Each mapped to scenario, control, and acceptance evidence |
| Differences from existing alternatives | Needs concrete comparison with sources; no unverified competitor claims |
| Motion graphic main narrative | What should the viewer remember within 30 seconds? |
| Pilot boundaries and success metrics | How to accept, and what is not promised |

## Usable evidence, not fantasy awaiting packaging

- `tests/test_e2e.py` / `test_report.json`: 18 automated cases and the actual execution environment.
- `demo.py`: end-to-end relay from Python to a standalone Node process.
- `verify_release.py` / `release_handoff_receipt.json`: this product's real candidate-file verification workflow.
- `PROTOCOL.md`: semantics of submission rights, freezing, ACK, and recovery inside the Broker.

## Promises that must not be swapped

- A runtime-agnostic protocol does not mean all runtimes are already adapted.
- Fencing holds only at write endpoints that actually verify epochs.
- SHA-256 is not an identity signature; a hash chain without external anchoring is not a tamper-proof guarantee.
- ACK is neither task completion nor proof of model understanding.
- A persistent checkpoint is not an OS process or memory snapshot.
- This is not currently a full scheduler, general multi-agent orchestration, or an autonomous governance platform.
- Without measurement, do not write "zero loss", "zero cost", "unlimited scaling", or "efficiency gain percentages".

## Finalization check

Every public capability sentence should trace back to implementation, a case, or a labeled product assumption; market inference and roadmap items must not be mixed into the delivered list. The Founder has not yet decided on listing; this round only prepares repo content and collaboration.
