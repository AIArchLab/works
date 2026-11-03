# Issue #2 fixes and re-verification entry - 0.1.1

Issue: https://github.com/AIArchLab/works/issues/2

## Status

All four defects were first reproduced on the unfixed version with the reporter's original script; after the fixes, explicit acceptance assertions verify the behavior, and neither "the repro script exits" nor "still reproduces" counts as a pass. Automated acceptance passing does not mean the reporter has re-verified; the issue stays open for the reporter's review and does not replace their confirmation.

## Defect-to-check mapping

| Defect | Fix | Regression acceptance |
|---|---|---|
| RH-01a: NaN/Infinity could be stored but Node could not read it | Recursive portable JSON validation at ingress and in the Python/Node SDKs under a shared spec, rejecting non-finite values | 19, 21, 22: create / nested write, pre-send / bundle decode; covers NaN and ±Infinity |
| RH-01b: large-integer digest valid but value changed | Numbers limited to the ±JS safe-integer bound; larger integers expressed as explicit schema strings by the application | 19-22: ±9007199254740991 roundtrips and out-of-range rejected; also nested values and legal decimals |
| RH-02: ACK before required content validation | The Node receiver checks attachment, content, and state before ACK; the release receiver also checks required inputs, manifest, and files | 23-25, 28: valid hash but wrong semantics, missing attachment, missing state, and empty manifest all produce no ACK and stay CLAIMED; original case 1 verifies positive continuation |
| RH-03: create did not apply the snapshot quota | create/write call the same `snapshot_check` | 26: ASCII and multi-byte UTF-8, below and above the 1 MiB line; oversized requests make no revision change |
| RH-04: zero-byte artifact rejected | Accepts empty base64 and verifies the empty-bytes hash | 27: Python write, Python/Node verification, Node ACK, and the next checkpoint revision |

## Re-run

```sh
python tests/test_issue_2.py
python demo.py
python verify_release.py
```

The first command includes the original 18 tests; do not add the two entry points together. Tests 19-28 each contain multiple sub-cases; the 28 in the report is the unittest method count, not a claim of only 10 single inputs.

`test_report.json` keeps this run's full output and environment; `release_handoff_receipt.json` keeps the updated candidate-file verification. `docs/issue-2-before-results.json` is the actual pre-fix reproduction result from the reporter's original script.

## Scope and unfinished items

No new exactly-once, external side-effect gateway, runtime certification, cross-OS certification, or SaaS commitments. Docker now COPYs sdk for the shared JSON validator but is still not build/run verified; the console now includes portable JSON validation but still has no browser click-through E2E.

Non-conforming values in existing databases are not auto-deleted or overwritten; see `PROTOCOL.md`. SHA-256 and semantic checks do not replace each other. Older download packages do not update themselves now that the repo is fixed; deliver 0.1.1 or newer externally.
