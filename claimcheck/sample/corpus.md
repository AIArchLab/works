<!-- Sample corpus for offline/demo runs (see README) -->
# grantkeeper — expiry-aware OAuth grant watch and renewal ledger

Stdlib-only CLI that keeps OAuth grants from dying quietly: statuses are
recomputed from dates on every scan, expiring grants surface with their
recorded renewal method, and every renewal lands in an append-only ledger.

**Status:** Sample (runnable MVP)
**Evidence state:** 13 unit tests PASS (author run, output in `evidence/unit_tests.txt`);
sample scan in `evidence/sample_scan.txt`; no third-party dependencies.
Scenario and data: fictional (see `examples/credentials.sample.json`). Any
resemblance to real organizations is coincidental.

## What it shows

The failure mode this work frames: an OAuth grant is usually discovered dead
at the worst possible moment — when the call it authorizes returns an error.
Post-mortems then rely on memory ("when did we last renew that?"), which is
not evidence.

The mechanism instead makes three things cheap and honest:

- **Status is derived, never stored as truth.** Every scan recomputes
  `valid / expiring / expired / revoked / unknown` from the grant's dates.
  A stale or hand-edited status in the file cannot survive a scan.
- **Renewal is an event, not an overwrite.** Running `renew` appends a ledger
  entry (who, when, result) and refreshes the grant in place. The ledger is
  append-only, so "when did we renew, and who did it" has an answer.
- **Attention is explicit.** `scan` returns exactly the grants inside the
  reminder window or past expiry, each with its recorded renewal method —
  a report ready to act on, not a dashboard to babysit.

Fail-closed throughout: corrupt JSON, duplicate names, renewals of
unknown grants, and malformed dates (message + no write) abort the command
instead of guessing.

## How to use / run

```bash
python3 grantkeeper.py add "grant name" --provider git-host \
  --owner "owner label" --expires-at 2026-12-31 \

# dokimasia — AI model vetting in three gates

dokimasia puts any LLM through three automated real-world trials and estimates
its monthly cost, so AI procurement stops running on faith. It is a single-file
Python CLI. It was published on 2026-10-22. It supports a Minimal evaluation
mode. It prices a model from measured token load, not from list prices.
