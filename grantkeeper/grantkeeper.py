#!/usr/bin/env python3
"""grantkeeper — expiry-aware OAuth grant watch and renewal ledger.

Stdlib-only CLI. Tracks OAuth grants (any service, any owner), recomputes
expiry status, and keeps an append-only renewal log so that renewals leave
evidence instead of folklore.

Design rules (fail-closed):
  - No silent fallbacks: a record that cannot be parsed fails the command.
  - Status is always recomputed from dates, never trusted from the file.
  - Renewals are append-only events; the log is the evidence.
"""

import argparse
import json
import sys
from datetime import date, datetime

STATUSES = ("valid", "expiring", "expired", "revoked", "unknown")

PROVIDERS = (
    "task-board", "cloud-storage", "git-host", "mail", "chat",
    "identity-provider", "other",
)


def today() -> date:
    return date.today()


def load_data(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {"grants": [], "renewals": []}
    except json.JSONDecodeError as exc:
        raise SystemExit(f"fail-closed: {path} is not valid JSON: {exc}")
    if not isinstance(data, dict) or "grants" not in data or "renewals" not in data:
        raise SystemExit(f"fail-closed: {path} must be an object with 'grants' and 'renewals'")
    return data


def save_data(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def parse_date(value):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise SystemExit(f"date must be YYYY-MM-DD, got: {value!r}")


def compute_status(grant: dict, ref: date) -> str:
    """Recompute status from dates. Manual revocation wins; never trust stored status."""
    if grant.get("status") == "revoked":
        return "revoked"
    expires = parse_date(grant.get("expires_at"))
    if expires is None:
        return "unknown"
    days_left = (expires - ref).days
    if days_left < 0:
        return "expired"
    remind = grant.get("remind_days_before", 7)
    if days_left < remind:
        return "expiring"
    return "valid"


def days_left(grant: dict, ref: date):
    expires = parse_date(grant.get("expires_at"))
    return None if expires is None else (expires - ref).days


def cmd_add(args, data, ref):
    name = args.name.strip()
    if not name:
        raise SystemExit("fail-closed: grant name must not be empty")
    if any(g["name"] == name for g in data["grants"]):
        raise SystemExit(f"fail-closed: grant '{name}' already exists")
    expires_at = parse_date(args.expires_at) if args.expires_at else None
    grant = {
        "name": name,
        "provider": args.provider or "other",
        "owner_label": args.owner or "",
        "grant_date": args.grant_date or ref.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "remind_days_before": args.remind_days_before,
        "status": "unknown",
        "renewal_method": args.renewal_method or "",
        "renewal_url": args.renewal_url or None,
        "last_checked": None,
        "notes": args.notes or "",
    }
    grant["status"] = compute_status(grant, ref)
    data["grants"].append(grant)
    return [f"added '{name}' ({grant['status']})"]


def cmd_scan(args, data, ref):
    changed, attention = 0, []
    for grant in data["grants"]:
        new_status = compute_status(grant, ref)
        if new_status != grant.get("status"):
            changed += 1
        grant["status"] = new_status
        grant["last_checked"] = datetime.now().isoformat(timespec="seconds")
        if new_status in ("expiring", "expired"):
            dl = days_left(grant, ref)
            attention.append(
                f"{grant['name']} [{new_status}] "
                f"{dl if dl is not None else '?'} days left — {grant['renewal_method'] or 'renewal method not recorded'}"
            )
    out = [f"scanned {len(data['grants'])} grants, {changed} status changes"]
    if attention:
        out.append(f"{len(attention)} grant(s) need renewal:")
        out.extend(f"  - {line}" for line in attention)
    else:
        out.append("no grants need renewal")
    return out


def cmd_list(args, data, ref):
    out = ["name\tdays_left\tstatus\towner"]
    for grant in sorted(data["grants"], key=lambda g: days_left(g, ref) or 10**9):
        dl = days_left(grant, ref)
        out.append(
            f"{grant['name']}\t{dl if dl is not None else 'long-lived'}\t{grant['status']}\t{grant['owner_label']}"
        )
    return out


def cmd_renew(args, data, ref):
    matches = [g for g in data["grants"] if g["name"] == args.name]
    if not matches:
        raise SystemExit(f"fail-closed: no grant named '{args.name}'")
    grant = matches[0]
    new_expires = parse_date(args.new_expires) if args.new_expires else None
    data["renewals"].append({
        "grant": grant["name"],
        "renewed_at": datetime.now().isoformat(timespec="seconds"),
        "renewed_by": args.by or "unrecorded",
        "result": "success",
        "notes": args.notes or "",
    })
    grant["grant_date"] = ref.isoformat()
    grant["expires_at"] = new_expires.isoformat() if new_expires else grant.get("expires_at")
    grant["status"] = compute_status(grant, ref)
    return [f"renewal logged for '{grant['name']}' (now {grant['status']})"]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="grantkeeper", description=__doc__)
    parser.add_argument("--data", default="credentials.json", help="data file (default ./credentials.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="register a grant")
    p_add.add_argument("name")
    p_add.add_argument("--provider", choices=PROVIDERS)
    p_add.add_argument("--owner", help="owner label (free text)")
    p_add.add_argument("--grant-date")
    p_add.add_argument("--expires-at", help="ISO date; omit for long-lived grants")
    p_add.add_argument("--remind-days-before", type=int, default=7)
    p_add.add_argument("--renewal-method")
    p_add.add_argument("--renewal-url")
    p_add.add_argument("--notes")
    p_add.set_defaults(fn=cmd_add)

    sub.add_parser("scan", help="recompute statuses and list grants needing renewal").set_defaults(fn=cmd_scan)
    sub.add_parser("list", help="list grants with days remaining").set_defaults(fn=cmd_list)

    p_renew = sub.add_parser("renew", help="log a renewal and refresh the grant")
    p_renew.add_argument("name")
    p_renew.add_argument("--new-expires", help="new expiry ISO date (omit to keep)")
    p_renew.add_argument("--by", help="who performed the renewal")
    p_renew.add_argument("--notes")
    p_renew.set_defaults(fn=cmd_renew)

    args = parser.parse_args(argv)
    ref = today()
    data = load_data(args.data)
    lines = args.fn(args, data, ref)
    save_data(args.data, data)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
