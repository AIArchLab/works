# advisor-router

## Quick start

Needs Python 3.9 or newer (tested on 3.10).

    pip install "git+https://github.com/AIArchLab/works.git#subdirectory=advisor-router"
    advisor-router serve      # start the advisor on http://127.0.0.1:8099
    advisor-router demo       # run the sticky-loop demo (starts its own temporary advisor)

`serve` options: `--port 8100` (or `ADVISOR_PORT`), `--host`, `--rules my_rules.yaml`, `--models my_models.yaml`, `--log decisions.jsonl`. Without `--rules` and `--models` it uses the packaged example files. Ask it for a model:

    curl -s localhost:8099/decide -H 'content-type: application/json' \
         -d '{"task_id":"t1","step_type":"code_edit"}'

Developers: `git clone https://github.com/AIArchLab/works && cd works/advisor-router && pip install -e ".[dev]" && python -m pytest -q`

**Status:** Sample / Concept (research skeleton, not a product)
**Evidence state:** Verified locally: one-line install and the `advisor-router` commands, rule matching, default-to-strongest, upgrade-only re-ask, decision log (37 tests pass, raw output in `evidence/`; the demo loop runs against a fake model reply). Not verified: any real provider call, any embedding classifier. Model names are placeholders.
**Scenario and data:** fictional. No real models, prices or users are involved.

## What it shows

Anyone who uses more than one model, a hobbyist, a developer, a small team or a large organization, hits the same question: who decides which model handles this step?

The common answer is a proxy that sits in the traffic path and holds keys. This sample takes the other route: an **advisor**. It answers one question, "which model for this step?", and returns only a model name. The caller keeps its own keys, state and usage accounting and makes the API call itself. Judgment is local and cheap; the workers are remote.

Design choices:
- Rules first. A YAML file, first match wins, readable and reviewable.
- Low confidence goes to the strongest model. Uncertainty never silently downgrades.
- The caller classifies once; the advisor only clamps upward. Re-ask only when the caller reports struggle, and only move up, never down.
- Safety rules (long context, hard keywords) sit at the top of `rules.yaml` so no step-type rule can shadow them. `default_model` must be the strongest tier or the advisor refuses to start.
- The advisor sees tier names and model names only. No credentials, no prices.
- Every decision is appended to a JSONL log kept with the advisor. Usage accounting stays with the caller.
  Log fields: `task_id`, `step_type`, `phase`, `current_tier`, `struggle`, `tokens`, `text_sha256` (hash only, the text is never stored), `rules_version` (sha256 of `rules.yaml`), `confidence`, `tier`, `model`, `source` (`rule|classifier|default`), `matched_rule`, `clamp` (`sticky|upgrade|ceiling|none`). `confidence` is null when a rule decided, because no classifier ran.
- `clamp` contract: `sticky` = raised to `current_tier` (never downgrade); `upgrade` = returned tier is above `current_tier` (a re-ask moved up, or an entry call with `current_tier` got a higher tier); `ceiling` = re-ask at the top tier, nothing higher exists, tier unchanged; `none` = no adjustment.
- Rule files fail closed: `when` must be a non-empty mapping using only `step_type`, `min_tokens` (int) and `keywords`. Unknown keys, an empty `when` or a wrong type make the advisor refuse to start, so a typo can never turn a rule into a catch-all.
- `/decide` validates input: `phase` is `entry` or `reask`, `current_tier` must be a configured tier, `phase=reask` requires `struggle` and `current_tier`, `tokens >= 0`. Violations return 422.
- The classifier slot is pluggable. The first version has none.

## Contents

- `advisor/data/rules.yaml`: rules, default tier, confidence threshold (0.6), tier order
- `advisor/data/models.yaml`: illustrative registry (placeholder names; endpoint and key variable names are for the caller only)
- `advisor/`: rule engine, `advisor-router` command line, registry, pluggable classifier, decision log, FastAPI app (`POST /decide`)
- `advisor/runtime_client.py`: caller-side example of the sticky loop with a fake model reply
- `tests/`: unit and HTTP-level tests
- `evidence/`: raw output of the test run and the demo loop

## Limits

- `text_sha256` is an unsalted hash. A short or guessable prompt can be recovered by dictionary guessing, so treat it as a content fingerprint, not as protection for the text. A keyed HMAC would fix that but adds key management, which this sample leaves out.
- Skeleton only. Provider calls and message normalization in `runtime_client.py` are stubs.
- No classifier is implemented; rules plus default-to-strongest is the whole first version. Validate `confidence_threshold`'s type and range before adding a classifier, when the classifier path begins using it.
- No measurements of routing quality or savings. None are claimed.
- Whether an advisor beats a proxy for a given setup is an open question this sample does not answer.
