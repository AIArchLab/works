# Suggested README placement (review before merging)

AIArchLab | RelayHandoff v0.1.0

**New runtime. Same task.**

![Concept visualization: saved state, controlled handoff and stale-write rejection](media/task-continuity-concept.png)

Concept visualization. Broker-scoped fencing; ACK is not task completion. The reference flow uses Python and Node; it does not claim all-runtime adapters.

[Watch the actual UI excerpts](media/task-continuity-ui-excerpts.mp4)

![Actual UI excerpt: old-lease write rejected](media/poster.png)

Actual UI excerpts, edited by step rather than a continuous recording. The receiver here is Python. Stop/restart actions occur off screen. The UI combines claim, verify and ACK. Protection is limited to Broker-mediated state and artifacts.

See [visual provenance](media/PROVENANCE-AIARCHLAB-20261104.md).
