# claimcheck — trust ledger for AI agent teams

Sample work #0006. A stdlib-only Python CLI that governs an AI agent team on
evidence: a member trust ledger (start at 100, severity-based deductions,
append-only events, cutoff flagging) plus a per-claim evidence engine that
scores an LLM answer by whether every factual claim traces to its source.

## The mechanism

1. A worker model answers a question using ONLY a provided corpus. If the
   corpus does not contain the answer, it must reply `NOT_IN_SOURCE`.
2. The answer is decomposed into atomic, standalone claims.
3. A verifier model rules each claim `supported`, `contradicted`, or
   `unsourced` against the same corpus, with an exact quote as evidence.
4. Trust is deducted by severity from a ledger that starts at 100:
   `unsourced -5`, `contradicted -15`, protocol failures -5. Correct refusals
   cost nothing.
5. A model whose trust drops below 40 is flagged untrusted for routing.

The design premise: an answer that cannot cite its source is indistinguishable
from a hallucination at delivery time. Making unverifiable claims costly shifts
selection pressure toward grounded output — honesty becomes the cheapest
strategy. The ledger is append-only and recomputed from run records, never
trusted from a stored copy.

Hardened behaviors (each backed by a unit test):
- Malformed or non-list verifier output fails closed as a per-claim protocol
  failure; it can never silently pass.
- Claims that cannot be parsed are treated as protocol failures, not dropped.
- A run with hallucinated claims deducts and is logged; a correct refusal is
  free.

## Usage

Set an OpenAI-compatible endpoint and key via environment:

```
export CC_API_BASE="https://<your-openai-compatible-host>/v1"
export CC_API_KEY="<your-key>"

python3 claimcheck.py --ledger trust_ledger.json bench \
  --corpus sample/corpus.md --eval sample/questions.json \
  --models <model-id> [<model-id> ...]
```

Member trust ledger (governance, no endpoint needed):

```
python3 claimcheck.py member add <name> --role <role>
python3 claimcheck.py member deduct <name> <points> --reason "..." --by chair
python3 claimcheck.py members
python3 claimcheck.py member events <name>
```

Each member starts at 100. Deductions log an append-only event; trust floors
at 0 and never restores above 100. Status is a pure function of score:
> 60 active, 41-60 observation (per-item delivery verification), at or below
40 dismissed. A single deduction event is capped at 30 points; the extreme
clause allows exactly 60. Scores are recomputed from the event log, never
trusted from a stored copy.

Offline protocol tests (no endpoint needed, mocked transport):

```
python3 -m unittest discover -s tests -v
```

## Verification status

- 6/6 offline protocol unit tests PASS (see `evidence/offline_tests.txt`).
- End-to-end offline demo: a repeatedly hallucinating mock drops to 20/100 in
  four runs and is flagged below the 40 cutoff.
- Live multi-model benchmark: not run at publish time — the available external
  inference endpoint refused API calls (account state, source-missing).
  Marked as unmeasured, not as proven.

## Limits

- This is selection-time scoring, not weight training: it lowers hallucination
  in delivered output and produces per-model trust trends; it does not modify
  model weights.
- Single verifier model per run; verifier quality bounds the audit.
- Ledger is a single-file JSON store without concurrency control.
- One question per call; no batching or parallel workers.
