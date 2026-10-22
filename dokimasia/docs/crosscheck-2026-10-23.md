# Independent crosscheck — 2026-10-23

Scope: run the published `exam` and `lead` commands from a second operator,
against a commercial OpenAI-compatible gateway, with a judge from a different
model family than the candidate. This is a review record, not a code change.

## Results

| Command | Candidate | Judge | Verdict |
|---|---|---|---|
| `exam` | `qwen/qwen3-coder-30b-a3b-instruct` | `z-ai/glm-5.3` | PASS (3/3 gates) |
| `lead` | `qwen/qwen3-coder-30b-a3b-instruct` | `z-ai/glm-5.3` | REVIEW — judge returned empty content |
| `lead` | `qwen/qwen3-coder-30b-a3b-instruct` | `qwen/qwen3-235b-a22b-2507` | PASS (4/4 rubric checks) |

The candidate output and rubric were unchanged between the two `lead` runs.

## Defect: a reasoning-heavy judge can exhaust the judge budget

`gate_leadership` calls `chat_noreason(..., max_tokens=1200)`. With a judge that
emits reasoning tokens, both the "thinking disabled" body and the plain fallback
finished with `finish_reason=length`, `completion_tokens=1200` and zero content:

```text
nothink: finish=length content_len=0 reasoning_tokens=1201 completion_tokens=1200
plain:   finish=length content_len=0 reasoning_tokens=1202 completion_tokens=1200
```

The disable flags were accepted without an HTTP error but did not stop reasoning
on this provider. The gate then reports REVIEW ("judge returned empty content"),
which is a false negative: the candidate passed every structural check and the
same answer passed 4/4 with a non-reasoning judge.

## Reproduction

1. `exam --model <candidate> --judge z-ai/glm-5.3` → PASS
2. `lead --model <candidate> --judge z-ai/glm-5.3` → REVIEW
3. `lead --model <candidate> --judge qwen/qwen3-235b-a22b-2507` → PASS

## Suggested fixes (not applied here)

1. Raise the judge budget, or retry once with a larger `max_tokens` when
   `finish_reason == "length"` and content is empty.
2. Record the judge's `finish_reason` and reasoning token count in the report so
   a REVIEW can be diagnosed without a second run.
3. Document that a reasoning-style judge needs a larger budget, or prefer a
   non-reasoning judge in the quickstart.

## What this does not establish

One candidate and one gateway. No claim about other providers, other models, or
the `select` and `estimate` paths. No credentials, endpoint URLs, organization
names, member names or internal ids are recorded here.
