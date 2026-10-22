# Notion Check-in SDK v2.1.6 (generic)

A small, dependency-free Python SDK for recording an agent check-in in a Notion
database. It is a generic rewrite: **no database id, property names, user paths,
credentials, organization names, or internal URLs are embedded.**

## What it does

1. Validates arguments and configuration.
2. Reads the target Notion database schema.
3. Checks that the agent and property types match.
4. Checks idempotency for the same agent and day.
5. Writes a local JSONL record.
6. Creates one Notion page.
7. Exits with a machine-readable status code.

It does **not** auto-add select options, auto-create databases, or read credentials
from a fixed local file.

## Background / Why this exists

Agent teams need a check-in record that survives restarts and can be audited
later. Earlier internal versions of this tool grew as ad-hoc scripts that wrote
straight into a live database, with no argument validation, no idempotency, and
credentials and database ids hardcoded in source. That made the record easy to
corrupt and unsafe to share. This SDK is the generic rewrite: one validated
writer, fail-closed usage errors (exit 2, nothing written), same-day
idempotency, a local JSONL audit log before any network write, and every
environment-specific value moved into configuration. It exists so the check-in
habit does not depend on trusting a script with a production database.

## Requirements

- Python 3.8+
- A Notion integration token with access to the target database
- The database shared with that integration

## Quick start

```bash
export CHECKIN_TOKEN="ntn_your_integration_token"
export CHECKIN_DATABASE_ID="your_database_id"

python checkin.py --agent alice --reason "daily check-in"
```

Check the result:

```bash
echo $?   # 0 = success/already checked in
```

## Configuration

### Required

| Variable | Meaning |
|---|---|
| `CHECKIN_TOKEN` or `NOTION_TOKEN` | Notion integration token |
| `CHECKIN_DATABASE_ID` or `NOTION_DATABASE_ID` | Target database id |
| `--agent` | Agent identity |
| `--reason` | Check-in reason |

### Property mapping

The defaults are generic English names. Override them for your own database:

| Variable | Default | Expected Notion type |
|---|---|---|
| `CHECKIN_PROP_TITLE` | `Name` | title |
| `CHECKIN_PROP_AGENT` | `Agent` | select or rich_text |
| `CHECKIN_PROP_STATUS` | `Status` | select or status (empty = skip) |
| `CHECKIN_PROP_DATE` | `Date` | date |
| `CHECKIN_PROP_NOTES` | `Notes` | rich_text |
| `CHECKIN_PROP_SOURCE` | `Source` | url (empty = skip) |

Example for a database whose fields are `Title`, `Owner`, `State`, `When`, `Memo`:

```bash
export CHECKIN_PROP_TITLE=Title
export CHECKIN_PROP_AGENT=Owner
export CHECKIN_PROP_STATUS=State
export CHECKIN_PROP_DATE=When
export CHECKIN_PROP_NOTES=Memo
export CHECKIN_PROP_SOURCE=
```

### Other options

| Variable / flag | Default | Meaning |
|---|---|---|
| `CHECKIN_STATUS_VALUE` | `Active` | Value written to the status property |
| `CHECKIN_TZ_OFFSET` | `+00:00` | Timezone offset used for day boundaries and timestamps |
| `--occurred-at` | now | ISO 8601 or `HH:MM[:SS]` |
| `--local-log` / `CHECKIN_LOCAL_LOG` | `./checkin.jsonl` | Local audit log |
| `--source-url` / `CHECKIN_SOURCE_URL` | none | Optional source URL |
| `--database-id` | env | Override database id |
| `--dry-run` | off | Validate and print the payload; no write |

## Check-in loop

This SDK covers the write step of a simple loop:

```text
wake agent
  -> run checkin.py (this SDK)
  -> agent reports the page id / timestamp to its coordinator
  -> coordinator aggregates and reports to the human
```

The SDK does not send the report itself; the caller owns that step. A minimal
report message:

```text
[check-in] agent=alice occurred_at=... page_id=... status=ok
```

## Exit codes

| Code | Meaning |
|---:|---|
| 0 | success, already checked in, or dry-run |
| 1 | credential, schema, network, local log, or Notion write failure |
| 2 | usage error; nothing written |

## Files

```text
checkin.py          # Python SDK / CLI
test_checkin.py     # unit tests; no network writes
example.env         # configuration template
README.md           # this file
CHANGELOG.md        # release notes
LICENSE             # MIT
```

## Security notes

- The token is read from the environment only; no token file is read by default.
- Do not commit `example.env` with real values.
- Use a Notion integration limited to the target database.
- The SDK never adds select options; an admin must add the agent option first.

## License

MIT. See `LICENSE`.
