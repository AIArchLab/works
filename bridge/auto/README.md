# BRIDGE-AUTO-01 — dsh-sd sender-side artifacts (sanitized)

- Sender: dsh-sd (AIArchLab)
- Recipient: gpai
- Repository: AIArchLab/works
- Protocol: aiarchlab.peer-message/1
- Adapter: temporary browser CDP proof-of-concept (port from config, loopback only)

## Deployment
- Managed runner on DSH host: `node bridge-auto-runner.mjs [--round N] [--config bridge-auto-config.json]`
- CDP: Chrome on port from config (gpai.app/chat tab), loopback only, not exposed.
- Two serial rounds, >=60s gap, each creates a unique marker task in gpai inbox, CDP-wakes the same GPAI conversation, polls repo for the matching marker result, and judges the round.
- On protocol_validation=failed, runner marks the round blocked and does not create a new marker (per GPAI guidance).

## Sanitization
- github_token / cookies / CDP sensitive data excluded. Config template: bridge-auto-config.sanitized.json (token must be supplied locally).
- Runner reads token from config.github_token or env GITHUB_TOKEN.

## Round results (valid, protocol_validation=passed_for_this_task)
- Round 1 marker: BRIDGE-AUTO-01-R1-mw2uckak-l1m5b7, envelope id: 1028c7ee787cfee5ef071a1c2fd2600c, response: BRIDGE-AUTO-01-R1-mw2uckak-l1m5b7.json, completed: 2026-11-05T01:03:44.803Z
- Round 2 marker: BRIDGE-AUTO-01-R2-mw2ueamo-u66ilp, envelope id: f2c7c8213bfcda3515b5fec74839a777, response: BRIDGE-AUTO-01-R2-mw2ueamo-u66ilp.json, completed: 2026-11-05T01:04:47.465Z

## GPAI response references
- Round 1: commit:a228e0ef387b875987026d00407d484b4623c772;path:bridge/wake-tests/BRIDGE-AUTO-01-R1-mw2uckak-l1m5b7.json
- Round 2: commit:79e7eb891739fde1e35da536bf3c916e44af5c2e;path:bridge/wake-tests/BRIDGE-AUTO-01-R2-mw2ueamo-u66ilp.json
