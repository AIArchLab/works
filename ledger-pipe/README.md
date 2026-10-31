# Ledger Pipe v0.1 — monthly reporting with a source contract

A working command-line tool, not a slide deck. It turns two or three messy source exports into a fixed monthly report, and it refuses to produce numbers when a source breaks the contract.

## Why this shape

Monthly reporting rarely fails because the arithmetic is wrong. It fails because the sources change shape every month: a column gets renamed, amounts arrive with commas or full-width digits, one row is blank, a policy number repeats, a date does not exist. People then read the sheet line by line, and one bad row means redoing the whole table.

So the product is not the report. It is the **source contract**: declare what each source must look like, validate on every run, and only then produce the report. That layer is the part that can be repeated, handed over and verified.

## What it does

- Reads `schema.json`: source files, required columns, types (money / date / ratio), primary keys, non-negative rules.
- Validates: missing file, missing column, empty required cell, malformed amount, impossible date (`2026-09-31` is rejected), ratio out of range, duplicate primary key.
- Normalises: full-width digits, thousands separators, currency prefixes, surrounding spaces, UTF-8 BOM.
- Outputs: `out/report.md` for people, `out/report.csv` for machines, `out/errors.md` listing bad rows.
- Compares with the previous snapshot: totals, per-channel movement, absolute and percentage change.
- Fails closed: any source that fails validation stops the run with exit code 2 and produces no report.

## Run

```bash
python3 pipeline.py --data data/2026-08 --out out
python3 pipeline.py --data data/2026-09 --out out
python3 tests/run_tests.py
```

Python 3 standard library only, including the .xlsx reader. No third-party packages, no network, no login, no database.

## Verification status

Author self-test: 36 of 36 cases pass across three suites (adjacent-period, adversarial, xlsx) (`out/test-report.txt`), covering two clean periods, a missing column, a malformed amount, a duplicate key, an impossible date, an empty required cell, a negative amount, an out-of-range ratio, full-width normalisation, a BOM header, and byte-identical output across two runs.

Independent review: **pending**. Until that review is complete, this tool must not be described as externally validated.

All data in `data/` is **Sample** data generated for demonstration. No client data is included.

## Boundaries

Not in scope: ERP/CRM integration, approval workflows, a web back end, cloud execution, accounts. It reads sources and writes only to its own output folder.

## Known limits

- Sample data keeps Traditional Chinese column headers because it models a local bookkeeping layout; all prose, code identifiers and docs are English.

- Reads .xlsx natively through a bundled standard-library parser; legacy .xls (BIFF) must be re-saved as .xlsx or .csv.
- Only the first worksheet is read; formulas are read as cached values.
- The comparison baseline is the previous snapshot; picking a specific baseline period is not supported yet.
- Report layout is fixed in code; a different industry means editing the schema and the aggregation fields.

## When this pattern does not hold

The pattern applies when the need is: several sources, one fixed report, repeated monthly. It does not apply, and should be declined, when any of these appear: two-way writes into an existing system, a human approval step inside the flow, cross-company data exchange, or a request that is really an interactive dashboard rather than a periodic report.
