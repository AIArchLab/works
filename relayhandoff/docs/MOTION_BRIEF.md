# RelayHandoff Motion Graphic Collaboration Brief

Status: waiting for a peer to pick it up and submit; no one is pre-marked as committed to deliver.

## The point to make clear

**Not moving a summary from A to B, but letting task state, submission rights, and acceptance evidence continue across runtimes.**

This is a technical narrative proposal; brand and selling-point wording is to be finalized by peers. Finished assets go straight to this repo and are not relayed by the Founder.

## Suggested storyboard (about 25-35 seconds, loopable)

| Segment | On-screen action | What the viewer must understand |
|---|---|---|
| 1. Task still alive | The same task card holds goal, checkpoint, artifact; Source is Python | A task is not a chat log |
| 2. Submit and archive | state, revision, artifact digest enter the Broker; show PREPARED | Recoverable state and deliverables are preserved |
| 3. Writes paused | Write arrows from both Source and Target to the Broker are blocked | No competing writes during handoff; it does not force-stop an OS process |
| 4. New runtime verifies | Node reads the bundle and checks the digest; show CLAIMED, but write stays closed | Claim does not equal write permission |
| 5. Confirm takeover | After ACK, Node shows epoch 2 and write opens | Submission continues only after confirmation |
| 6. Old owner expires | Python writes at epoch 1 and is rejected by the Broker | Prevents stale writes inside the Broker |
| 7. Continuing with evidence | Node submits results and a receipt; the audit ties the flow together | Takeover and results can be audited |

An optional independent recovery branch: failure or timeout before ACK, then a new epoch and a resume. It must not be drawn as cancel-after-ACK over the same path, and not as permanently stuck.

## Spatial and visual grammar

- Fixed three zones: Source runtime / RelayHandoff Broker / Target runtime.
- The task card keeps the same task id; a runtime change does not mean a different piece of work.
- Show state, artifact, ownership, and receipt separately; do not blur them into one blob called "memory".
- Keep a clear Broker boundary; the write-rejection capability must not be drawn extending to unintegrated Git, DB, or social APIs.
- Label only Python and Node as reference runtimes actually tested; other products' logos must not be shown as integration evidence.
- Do not show real API keys, lease secrets, customer data, or raw credentials.
- Provide pause/replay, avoid rapid flashing; must stay readable when scaled down to README width.

## Delivery locations

- `media/task-continuity.*`: finished assets, e.g. GIF, MP4, WebM; SVG containing script cannot be guaranteed to animate inline on GitHub.
- `media/poster.png` or `.svg`: static poster when animation is unsupported.
- `media/source/`: editable sources; list sources and licenses for any external material.
- `media/PROVENANCE.md`: author, date, content baseline commit, whether frames are conceptual animation or real recording, tools/versions, reproduction commands, SHA-256 of each asset.
- Pickup records and review results for this brief: commit/PR directly; no external progress board.

Suggested GIF under 8 MiB, MP4 as H.264/yuv420p. Keep high-resolution masters as needed; the GitHub README preview is governed by actual render verification.

## Acceptance

1. Every frame maps to real semantics in the README or `PROTOCOL.md`.
2. Preservation, takeover ACK, and task completion are clearly separated, not drawn as one step.
3. Assets decode and play, are readable at size, and include sources and reproduction steps.
4. Previewed on GitHub for real; "the file exists" does not count as a successful render.
5. Conceptual animation is labeled conceptual visualization; real operation recordings are labeled with version and recording environment.
6. The README preview updates only after assets are in place and accepted. No fake assets or dead placeholders now.

## Pickup and submission record

No peer pickup or assets received yet. The taker adds their own author, division of work, commit, and blockers here; do not confirm pickup on anyone else's behalf.
