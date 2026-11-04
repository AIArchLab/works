# AIArchLab works

Finished works from AIArchLab. One work per folder. Works, not articles.
Scenario and data in every work are fictional unless the work itself states otherwise.

| # | Work | What it shows | Published |
|---|------|---------------|-----------|
| 1 | [Taskloop](taskloop/) | Durable HTTP-check agent with signed delivery receipts | 2026-10-21 |
| 2 | [dokimasia](dokimasia/) | AI model vetting in three gates, priced from measured token load | 2026-10-22 |
| 3 | [notion-checkin](notion-checkin/) | Fail-closed agent check-in SDK with idempotency and local audit log | 2026-10-22 |
| 4 | [skytale](skytale/) | Fail-closed session handoff: generation ids, hash-bound artifacts, offline gate | 2026-10-22 |
| 5 | [grantkeeper](grantkeeper/) | Expiry-aware OAuth grant watch with append-only renewal ledger | 2026-10-24 |
| 6 | [claimcheck](claimcheck/) | Trust ledger for AI agent teams: member governance plus a per-claim evidence engine | 2026-10-24 |
| 8 | [ledger-pipe](ledger-pipe/) | Monthly reporting behind a source contract: bad sources stop the run and name the row and column | 2026-11-01 |
| 9 | [replybridge](replybridge/) | Channel-agnostic inbound reply router: fail-closed escalation and a hash-chained decision ledger | 2026-11-03 |
| 10 | [SocialReply](socialreply/) | Reusable social reply MVP: signed webhooks, durable outbox, review dashboard; local E2E verified | 2026-11-03 |
| 11 | [srg](srg/) | Social reply gateway MVP: approved-answer-only replies, human handoff, per-platform capability honesty | 2026-11-03 |

Renumbered 2026-11-03 to resolve a numbering conflict: ledger-pipe was listed as #7, replybridge as #7, SocialReply as #9.

Works that need their own repository (code with releases, issues, tests):
- [weirwright](https://github.com/AIArchLab/weirwright) — executable change-control gates.

## How a work lands here

1. Drafted and de-identified (see [CONTENT_POLICY.md](CONTENT_POLICY.md)).
2. Reviewed internally.
3. Approved by the Founder. Only then: folder published, this index updated.

New works start from [`_template/`](_template/).

## Peer coordination

Member-to-member tasks and receipts live in [inbox/](inbox/). The executable interface and polling contract are in [protocol/](protocol/COMM-PROTOCOL.md). Delivery, acceptance and verified completion are separate states; no member is assumed to be always online.
