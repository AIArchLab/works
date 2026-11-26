# advisor-router

**Status:** Sample / Concept (research skeleton, not a product)
**Evidence state:** Verified locally: rule matching, default-to-strongest, upgrade-only re-ask, decision log (7 unit tests pass; the demo loop runs against a fake model reply). Not verified: any real provider call, any embedding classifier. Model names are placeholders.
**Scenario and data:** fictional. No real models, prices or users are involved.

## What it shows

Anyone who uses more than one model, a hobbyist, a developer, a small team or a large organization, hits the same question: who decides which model handles this step?

The common answer is a proxy that sits in the traffic path and holds keys. This sample takes the other route: an **advisor**. It answers one question, "which model for this step?", and returns only a model name. The caller keeps its own keys, state and usage accounting and makes the API call itself. Judgment is local and cheap; the workers are remote.

Design choices:
- Rules first. A YAML file, first match wins, readable and reviewable.
- Low confidence goes to the strongest model. Uncertainty never silently downgrades.
- Classify once at entry, then stay put (sticky). Re-ask only when the caller reports struggle, and only move up, never down.
- The advisor sees tier names and model names only. No credentials, no prices.
- Every decision is appended to a JSONL log kept with the advisor. Usage accounting stays with the caller.
- The classifier slot is pluggable. The first version has none.

## How to run

    pip install -r requirements.txt
    python -m uvicorn advisor.main:app --port 8099
    python runtime_client.py          # in a second shell: the sticky loop demo
    python -m pytest -q               # tests

## Contents

- `rules.yaml`: rules, default tier, confidence threshold (0.6), tier order
- `models.yaml`: illustrative registry (placeholder names; endpoint and key variable names are for the caller only)
- `advisor/`: rule engine, registry, pluggable classifier, decision log, FastAPI app (`POST /decide`)
- `runtime_client.py`: caller-side example of the sticky loop with a fake model reply
- `tests/`: unit tests

## Limits

- Skeleton only. Provider calls and message normalization in `runtime_client.py` are stubs.
- No classifier is implemented; rules plus default-to-strongest is the whole first version.
- No measurements of routing quality or savings. None are claimed.
- Whether an advisor beats a proxy for a given setup is an open question this sample does not answer.
