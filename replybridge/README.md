# replybridge — channel-agnostic inbound reply router

**Sample work.** Scenario and data are illustrative. No client, employer or marketplace is named.

Inbound comments and direct messages from several social channels enter one pipeline. A policy layer decides **reply, escalate to a human, or ignore**, and every decision is written to a hash-chained ledger that a third party can recompute.

## What it demonstrates

Most "auto-reply" builds stop at wiring vendor APIs. The part that decides whether such a system can be shown to anyone sits in four places, and those are what this work is about:

1. **What happens when it should not answer.** Sensitive content, low confidence, quiet hours, per-thread rate limits and an explicit human request all route to a human queue instead of guessing.
2. **Failure is never recorded as success.** A failed outbound call re-classifies the decision as escalation and stores the vendor status code.
3. **Duplicates stay single.** The same inbound message id is handled once, even if the vendor retries the delivery.
4. **Every reply is traceable.** Which rule, which knowledge entry, what confidence, what latency, and the ledger detects any edit to a stored decision.

Adding another channel or another brand is configuration, not code: one JSON file for tenants and policy, one for the knowledge base, plus a validator that refuses a config without guardrails.

## Architecture

```
vendor webhooks (several channels)
      |  signature verification per vendor format
      v
  parse()  ->  one normalized inbound event
      v
  policy.decide()  ->  reply | escalate | ignore
      |                 rules, guardrails, quiet hours, rate limit, confidence gate
      v
  build_request()  ->  vendor API
      v
  ledger: hash chain + human queue + stats + single-page console
```

## Layout

| Path | Contents |
|---|---|
| `rb/contracts.py` | Frozen type contracts (event, draft, decision, outbound request, store protocol) |
| `rb/channels.py` | Per-vendor signature verification, payload normalization, outbound request building |
| `rb/policy.py` | Rule engine, guardrails, confidence gate, escalation |
| `rb/ai.py` | Retrieval-based drafting over a knowledge base, pluggable provider, confidence scoring |
| `rb/ledger.py` | sqlite hash chain, dedupe, rate windows, queue, statistics |
| `rb/core.py` | Orchestration with an injectable transport |
| `rb/server.py` | HTTP entry, built-in console page, demo mode |
| `config/` | Tenant policy and knowledge base (illustrative) |
| `tools/validate_tenant.py` | Config validator for onboarding |

## Measured

- 195 unit checks green across channel parsing and signatures, policy scenarios, knowledge retrieval, ledger concurrency and tamper detection.
- 33 end-to-end checks green against a real HTTP server receiving signed webhook deliveries: signature rejection, idempotency, five escalation paths, outbound failure handling, human approval, ledger integrity.
- 50 concurrent deliveries at 48.2 messages per second, p95 43.5 ms on the reference sandbox.
- Raw run log: [`evidence/run.txt`](evidence/run.txt).

The test suite itself is not published here. The log above is the run output of the same code with the same configuration.

## Not claimed

No live vendor calls, no webhook registration or app review, no cross-host deployment or TLS. One vendor endpoint is marked `unverified` in code because no official document was located; that channel is not claimed as working. An independent crosscheck by another reviewer has **not** been done on this work.

## Run it

```bash
python3 tools/validate_tenant.py config/tenants.json
python3 -m rb.server --port 8080 --demo     # console at /, APIs at /stats and /queue
docker build -t replybridge . && docker run -p 8080:8080 -e RB_SECRETS_JSON=... replybridge
```

Secrets are injected through the environment only; nothing is read from disk.
