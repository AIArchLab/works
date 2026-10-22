# skytale

**Fail-closed session handoff for LLM agents.**

**Status:** Concept — v0.1.0 MVP.
**Evidence state:** 53 standard-library unit tests pass (19 core, 34 adapter/workflow); the example generation
passes all 34 offline gate checks. Remote storage read-back, event read-back,
dispatcher receipts and wakes are not exercised.
**Scenario and data:** a fictional demo agent with synthetic ids. Any resemblance
to real organizations is coincidental.

Long-running agents lose their state when a conversation ends. A handoff is the
artifact set that lets a *new* conversation resume the *same* work without
re-reading the chat log: a generation id, a context file, a summary file, an
index that binds them by hash, a pointer that names the committed generation,
and two events (check-out / check-in) that prove the transition happened.

Most handoff implementations are prose. This one is a contract you can verify
offline, before you claim anything.

```text
$ skytale check --dir examples/demo
[ok  ] CFG-001
[ok  ] IDX-003
[ok  ] CONTEXT-005
[ok  ] SUMMARY-005
...
PASS: 34 offline checks passed. Remote evidence (storage read-back, event
read-back, new-conversation recovery) is still required and is not proven here.
```

## Name

A *skytale* (σκυτάλη) was the baton Spartan officials passed to each other: a
strip of leather wound around the staff, written on, then unwound. The letters
scrambled; only the officer holding a staff of the same thickness could read the
message again. That is the contract here — the narrative only resolves against
the right generation, and a mismatch is visible rather than plausible.

## Background / Why this exists

Agent sessions end. Work does not. A team that runs several agents for days
needs a transition that survives a lost chat window, and needs to know whether
the transition actually happened rather than whether someone wrote a convincing
summary of it.

Earlier internal versions of this idea were prose prompts plus a checklist. They
failed in three predictable ways: an agent claimed "resumed" after only reading
the summary; a file was edited after the index was written, so the recorded hash
described a version nobody had stored; and a check-out event was written with a
time that had not occurred yet. This kit is the answer to those three failures:
identity that travels with the generation, hashes that bind the narrative, and a
gate that fails closed instead of trusting the narrator.

It claims nothing beyond what the included tests and the offline gate show.

## Design

- **Generations, not file names.** Latest is whatever the pointer says. Never
  sort by name or modified time.
- **Hashes bind the narrative.** Context and summary are hashed with
  `LF_UTF8_v1` (strip one BOM, CRLF/CR to LF, no stripping, no appended
  newline) and recorded in the index. A later edit cannot silently pass as the
  committed version.
- **Fail closed.** Missing ids, wrong parent, placeholder text, or a pointer that
  disagrees with the index fail the gate. `prepared` never claims to be
  `committed`.
- **Evidence routes stay separate.** A dispatcher receipt, a direct API
  read-back, an SDK wake and a chat delivery are four different proofs. The gate
  proves none of them; it proves the local artifacts are self-consistent.

## Install

Python 3.10+, standard library only.

```bash
python -m pip install .
skytale --version
```

Or from a checkout without installing:

```bash
python -m skytale.cli check --dir examples/demo
```

## Usage

```bash
# 1. Scaffold a prepared generation
skytale init --agent demo --dir runs/20261022T043928Z_c4fadc50311c --store store-demo-0001

# 2. Fill context/summary, then bind them by hash
skytale seal --dir runs/20261022T043928Z_c4fadc50311c

# 3. Verify before you tell anyone it worked
skytale check --dir runs/20261022T043928Z_c4fadc50311c

# 4. Render the prompt for the new conversation
skytale prompt --dir runs/20261022T043928Z_c4fadc50311c
```

`seal --commit` flips `commit_state` to `committed`; only then do the remote id
fields become mandatory.

### Run directory

```text
<agent>_handoff_context_<generation>.md    # full semantic record
<agent>_handoff_summary_<generation>.md    # short record
index.json                                 # hashes, store id, request ids
agent_config.json                          # agent name, store, authorization note
pointer.json                               # optional: committed generation pointer
```

## What the gate does not prove

It cannot prove that the bytes exist in remote storage, that the check-out event
was written, that a dispatcher delivered the prompt, or that the new
conversation actually recovered and checked in. Those are read back separately —
see [docs/evidence-routes.md](docs/evidence-routes.md).

## Tests

```bash
python -m unittest discover -s tests
```

53 tests (19 core, 34 adapter/workflow), standard library only. CI runs them on Python 3.10 and 3.12 and gates
the example generation.

## Adapter review candidate

Injected storage, event-store and dispatcher receipt APIs are documented in
[docs/adapters.md](docs/adapters.md). Synthetic contract tests exercise these
APIs; provider wiring and live read-back remain unverified. No release version
is advanced by this candidate.

## Roadmap

See [docs/roadmap.md](docs/roadmap.md): storage adapters, a resume verifier, and
a multi-agent chain. Maintainer coordination happens in
[docs/coordination.md](docs/coordination.md) (append-only thread).

## License

MIT — see [LICENSE](LICENSE).
