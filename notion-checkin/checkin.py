#!/usr/bin/env python3
"""Generic Notion check-in SDK — Python 3.8+, standard library only.

No organization-specific database id, property names, user paths, or credentials
are embedded. Configure via environment variables or CLI flags.

Usage:
    export CHECKIN_TOKEN="..."
    export CHECKIN_DATABASE_ID="..."
    python checkin.py --agent alice --reason "daily check-in"

Exit codes:
    0 success / already checked in / dry-run
    1 credential, schema, network, or Notion write failure
    2 usage error
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

VERSION = "2.1.6"
NOTION_API_URL = "https://api.notion.com/v1/pages"
NOTION_VERSION = "2022-06-28"
MAX_REASON_LEN = 2000
AGENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")
OFFSET_RE = re.compile(r"^([+-])(\d{2}):?(\d{2})$")

USAGE = """Usage:
  checkin.py --agent <name> --reason <text> [options]

Required:
  --agent <name>        Agent identity
  --reason <text>       Trigger reason (1..2000 chars)

Environment:
  CHECKIN_TOKEN         Notion integration token (required)
  CHECKIN_DATABASE_ID   Notion database id (required unless --database-id)

Options:
  --occurred-at <time>  ISO 8601 or HH:MM[:SS]; default = now
  --local-log <path>    Local JSONL path; default ./checkin.jsonl
  --source-url <url>    Optional source URL
  --database-id <id>    Override Notion database id
  --dry-run             Validate schema/idempotency; no write
  --help, -h            Show help
  --version             Show version

Property mapping (env; defaults are generic English names):
  CHECKIN_PROP_TITLE    default Name
  CHECKIN_PROP_AGENT    default Agent
  CHECKIN_PROP_STATUS   default Status (empty = no status field)
  CHECKIN_PROP_DATE     default Date
  CHECKIN_PROP_NOTES    default Notes
  CHECKIN_PROP_SOURCE   default Source (empty = no source field)

Other env:
  CHECKIN_STATUS_VALUE  default Active
  CHECKIN_TZ_OFFSET     default +00:00 (e.g. +08:00)
"""


class UsageError(Exception):
    """Fail-closed usage error: exit 2, never write."""


def parse_args(argv):
    args = {"dry_run": False, "help": False, "version": False}
    value_flags = {
        "--agent": "agent",
        "--reason": "reason",
        "--occurred-at": "occurred_at",
        "--occurred_at": "occurred_at",
        "--local-log": "local_log",
        "--local_log": "local_log",
        "--source-url": "source_url",
        "--source_url": "source_url",
        "--database-id": "database_id",
        "--database_id": "database_id",
    }
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--help", "-h"):
            args["help"] = True
            i += 1
            continue
        if arg == "--version":
            args["version"] = True
            i += 1
            continue
        if arg in ("--dry-run", "--dry_run"):
            args["dry_run"] = True
            i += 1
            continue
        matched = False
        for flag, key in value_flags.items():
            if arg == flag:
                if i + 1 >= len(argv):
                    raise UsageError(f"missing value for {flag}")
                args[key] = argv[i + 1]
                i += 2
                matched = True
                break
            if arg.startswith(flag + "="):
                args[key] = arg.split("=", 1)[1]
                i += 1
                matched = True
                break
        if matched:
            continue
        raise UsageError(f"unknown argument: {arg}")
    return args


def _env(name, default=""):
    return os.environ.get(name, default).strip()


def resolve_agent(args):
    agent = (args.get("agent") or _env("CHECKIN_AGENT")).strip()
    if not agent:
        raise UsageError("AGENT_REQUIRED --agent is required (or CHECKIN_AGENT)")
    if agent.lower() == "unknown":
        raise UsageError("AGENT_INVALID 'unknown' is not a valid agent")
    if not AGENT_RE.match(agent):
        raise UsageError(f"AGENT_INVALID unsupported agent name: {agent!r}")
    return agent


def resolve_reason(args):
    reason = args.get("reason")
    if reason is None:
        raise UsageError("REASON_REQUIRED --reason is required")
    reason = reason.strip()
    if not reason:
        raise UsageError("REASON_REQUIRED --reason must not be empty")
    if len(reason) > MAX_REASON_LEN:
        raise UsageError(f"REASON_TOO_LONG max {MAX_REASON_LEN} chars")
    return reason


def resolve_token():
    token = _env("CHECKIN_TOKEN") or _env("NOTION_TOKEN")
    if not token:
        return None
    return token


def resolve_database_id(args):
    db = (args.get("database_id") or _env("CHECKIN_DATABASE_ID") or _env("NOTION_DATABASE_ID")).strip()
    if not db:
        raise UsageError("DATABASE_ID_REQUIRED set CHECKIN_DATABASE_ID or --database-id")
    return db


def resolve_local_log(args):
    return args.get("local_log") or _env("CHECKIN_LOCAL_LOG") or "./checkin.jsonl"


def resolve_source_url(args):
    return (args.get("source_url") or _env("CHECKIN_SOURCE_URL")).strip() or None


def resolve_offset():
    raw = _env("CHECKIN_TZ_OFFSET", "+00:00") or "+00:00"
    match = OFFSET_RE.match(raw)
    if not match:
        raise UsageError("TZ_INVALID CHECKIN_TZ_OFFSET must be like +00:00 or +08:00")
    sign, hh, mm = match.group(1), int(match.group(2)), int(match.group(3))
    if hh > 23 or mm > 59:
        raise UsageError("TZ_INVALID offset out of range")
    delta = timedelta(hours=hh, minutes=mm)
    if sign == "-":
        delta = -delta
    return timezone(delta), raw


def _format_dt(dt, tz, offset_text):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    dt = dt.astimezone(tz)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + offset_text


def resolve_occurred_at(args):
    tz, offset_text = resolve_offset()
    value = (args.get("occurred_at") or _env("CHECKIN_OCCURRED_AT")).strip()
    if not value:
        return _format_dt(datetime.now(tz), tz, offset_text)

    if "T" not in value and " " not in value and ":" in value and "-" not in value:
        parts = value.split(":")
        if len(parts) not in (2, 3):
            raise UsageError(f"invalid --occurred-at: {value!r}")
        try:
            hh, mm = int(parts[0]), int(parts[1])
            ss = int(parts[2]) if len(parts) == 3 else 0
            if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
                raise ValueError
        except ValueError:
            raise UsageError(f"invalid --occurred-at: {value!r}")
        today = datetime.now(tz).date()
        return _format_dt(datetime(today.year, today.month, today.day, hh, mm, ss, tzinfo=tz), tz, offset_text)

    text = value.replace(" ", "T")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise UsageError(f"invalid --occurred-at: {value!r}")
    return _format_dt(dt, tz, offset_text)


def get_schema(token, database_id):
    req = urllib.request.Request(
        f"https://api.notion.com/v1/databases/{database_id}",
        headers={"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"SCHEMA_UNAVAILABLE HTTP {e.code}", file=sys.stderr)
        return None
    except urllib.error.URLError as e:
        print(f"SCHEMA_UNAVAILABLE {e}", file=sys.stderr)
        return None


def resolve_props(schema):
    props = schema.get("properties", {})
    config = {
        "title": _env("CHECKIN_PROP_TITLE", "Name"),
        "agent": _env("CHECKIN_PROP_AGENT", "Agent"),
        "status": _env("CHECKIN_PROP_STATUS", "Status"),
        "date": _env("CHECKIN_PROP_DATE", "Date"),
        "notes": _env("CHECKIN_PROP_NOTES", "Notes"),
        "source": _env("CHECKIN_PROP_SOURCE", "Source"),
    }
    required = ("title", "agent", "date", "notes")
    for key in required:
        name = config[key]
        if not name or name not in props:
            raise UsageError(f"SCHEMA_INCOMPLETE missing property: {name or key}")

    def ptype(name):
        return props[name].get("type") if name in props else None

    if ptype(config["title"]) != "title":
        raise UsageError(f"SCHEMA_INVALID title property '{config['title']}' must be title")
    if ptype(config["agent"]) not in ("select", "rich_text"):
        raise UsageError(f"SCHEMA_INVALID agent property '{config['agent']}' must be select or rich_text")
    if ptype(config["date"]) != "date":
        raise UsageError(f"SCHEMA_INVALID date property '{config['date']}' must be date")
    if ptype(config["notes"]) != "rich_text":
        raise UsageError(f"SCHEMA_INVALID notes property '{config['notes']}' must be rich_text")
    if config["status"] and config["status"] in props and ptype(config["status"]) not in ("select", "status"):
        raise UsageError(f"SCHEMA_INVALID status property '{config['status']}' must be select or status")
    if config["source"] and config["source"] in props and ptype(config["source"]) != "url":
        raise UsageError(f"SCHEMA_INVALID source property '{config['source']}' must be url")

    resolved = {k: (v if v in props else None) for k, v in config.items()}
    return resolved


def ensure_agent(schema, prop_name, agent):
    spec = schema.get("properties", {}).get(prop_name, {})
    if spec.get("type") == "select":
        options = [o.get("name") for o in spec.get("select", {}).get("options", [])]
        if agent not in options:
            raise UsageError(
                f"AGENT_NOT_IN_SCHEMA '{agent}' is not an option in '{prop_name}'. "
                "Add the option in Notion first; this SDK never auto-adds it."
            )
    elif spec.get("type") == "rich_text":
        return
    else:
        raise UsageError(f"SCHEMA_INVALID agent property '{prop_name}' must be select or rich_text")


def _agent_filter(prop_name, prop_type, agent):
    if prop_type == "select":
        return {"property": prop_name, "select": {"equals": agent}}
    return {"property": prop_name, "rich_text": {"equals": agent}}


def find_existing(token, database_id, agent, occurred_at, props, schema):
    dt = datetime.fromisoformat(occurred_at)
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    agent_type = schema["properties"][props["agent"]].get("type")

    filters = [
        _agent_filter(props["agent"], agent_type, agent),
        {"property": props["date"], "date": {"on_or_after": day_start.isoformat()}},
        {"property": props["date"], "date": {"before": day_end.isoformat()}},
    ]
    status_value = _env("CHECKIN_STATUS_VALUE", "Active")
    if props.get("status") and status_value:
        status_type = schema["properties"][props["status"]].get("type")
        filters.append({"property": props["status"], status_type: {"equals": status_value}})

    body = json.dumps({
        "filter": {"and": filters},
        "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
        "page_size": 1,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.notion.com/v1/databases/{database_id}/query",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"IDEMPOTENCY_CHECK_FAILED HTTP {e.code}", file=sys.stderr)
        raise
    except urllib.error.URLError as e:
        print(f"IDEMPOTENCY_CHECK_FAILED {e}", file=sys.stderr)
        raise
    results = data.get("results", [])
    if not results:
        return None
    page = results[0]
    try:
        existing_at = page["properties"][props["date"]]["date"]["start"]
    except (KeyError, TypeError):
        existing_at = None
    return {"id": page.get("id"), "occurred_at": existing_at}


def build_page_properties(agent, occurred_at, reason, props, schema, source_url):
    note = f"{reason} | occurred_at={occurred_at}"
    if len(note) > MAX_REASON_LEN:
        note = note[:MAX_REASON_LEN]

    out = {}
    out[props["title"]] = {"title": [{"text": {"content": agent}}]}
    agent_type = schema["properties"][props["agent"]].get("type")
    if agent_type == "select":
        out[props["agent"]] = {"select": {"name": agent}}
    else:
        out[props["agent"]] = {"rich_text": [{"text": {"content": agent}}]}

    status_value = _env("CHECKIN_STATUS_VALUE", "Active")
    if props.get("status") and status_value:
        status_type = schema["properties"][props["status"]].get("type")
        out[props["status"]] = {status_type: {"name": status_value}}

    out[props["date"]] = {"date": {"start": occurred_at}}
    out[props["notes"]] = {"rich_text": [{"text": {"content": note}}]}
    if source_url and props.get("source"):
        out[props["source"]] = {"url": source_url}
    return out


def write_local_log(agent, occurred_at, reason, path):
    record = {
        "agent": agent,
        "action": "check_in",
        "occurred_at": occurred_at,
        "trigger_reason": reason,
    }
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        print(f"LOCAL_LOG_FAILED {e}", file=sys.stderr)
        return False
    print(f"Local log written: {path}")
    return True


def call_notion(token, database_id, properties, dry_run=False):
    payload = {"parent": {"database_id": database_id}, "properties": properties}
    if dry_run:
        print("DRY_RUN: would create check-in page")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return True
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        NOTION_API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            body_text = resp.read().decode("utf-8", errors="replace")
            print(f"Notion API: HTTP {status}")
            if 200 <= status < 300:
                try:
                    page_id = json.loads(body_text).get("id")
                except ValueError:
                    page_id = None
                print(f"  OK — check-in recorded page_id={page_id}")
                return True
            print(f"  ERROR: {body_text}")
            return False
    except urllib.error.HTTPError as e:
        print(f"Notion API: HTTP {e.code}")
        print(f"  ERROR: {e.read().decode('utf-8', errors='replace')}")
        return False
    except urllib.error.URLError as e:
        print(f"Notion API: Network error — {e}")
        return False


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        args = parse_args(argv)
        if args["help"]:
            print(USAGE)
            return 0
        if args["version"]:
            print(f"checkin {VERSION}")
            return 0

        agent = resolve_agent(args)
        reason = resolve_reason(args)
        occurred_at = resolve_occurred_at(args)
        local_log = resolve_local_log(args)
        database_id = resolve_database_id(args)
        source_url = resolve_source_url(args)
        dry_run = args["dry_run"]

        token = resolve_token()
        if not token:
            print("CREDENTIAL_GAP set CHECKIN_TOKEN or NOTION_TOKEN", file=sys.stderr)
            return 1

        schema = get_schema(token, database_id)
        if not schema:
            return 1
        props = resolve_props(schema)
        ensure_agent(schema, props["agent"], agent)

        existing = find_existing(token, database_id, agent, occurred_at, props, schema)
        if existing:
            print(f"ALREADY_CHECKED_IN page_id={existing['id']} occurred_at={existing['occurred_at']}")
            return 0

        properties = build_page_properties(agent, occurred_at, reason, props, schema, source_url)
        if dry_run:
            return 0 if call_notion(token, database_id, properties, dry_run=True) else 1

        if not write_local_log(agent, occurred_at, reason, local_log):
            return 1
        if not call_notion(token, database_id, properties, dry_run=False):
            return 1
        return 0
    except UsageError as e:
        print(str(e), file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 - fail closed
        print(f"UNEXPECTED_ERROR {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
