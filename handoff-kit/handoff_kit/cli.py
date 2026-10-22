"""Command line interface for handoff-kit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import artifact_name, generation_id, parse_generation, sha256_lf_utf8_v1
from .gate import check_generation, render_prompt, utc_now_iso

CONFIG_TEMPLATE = {
    "agent_name": "demo",
    "store_id": "store-demo-0001",
    "authorization_reference": "the agent's own OAuth token and event-store integration",
    "startup_spec_ref": "docs/spec-startup.md",
    "close_spec_ref": "docs/spec-close.md",
    "pointer_hint": "the pointer file in the store",
}

CONTEXT_TEMPLATE = """# {agent} handoff context

agent_name: {agent}
generation_id: {gen}

## Goal and background

## Latest decisions and reasons

## Role, access and authorization boundary

## Last completed position and official artifacts

## Verified results, failures and corrections

## Unresolved work, schedule and next action

## Source coverage and unavailable scope
"""

SUMMARY_TEMPLATE = """# {agent} handoff summary

agent_name: {agent}
generation_id: {gen}

## Timeline and outcomes

## Completed vs unfinished

## Official artifacts and next action

## Coverage limitations
"""


def _write(path: Path, text: str, force: bool) -> None:
    if path.exists() and not force:
        raise SystemExit(f"refusing to overwrite existing file: {path} (use --force)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def cmd_init(args: argparse.Namespace) -> int:
    run = Path(args.dir)
    run.mkdir(parents=True, exist_ok=True)
    gen = args.generation or generation_id()
    parse_generation(gen)
    agent = args.agent

    cfg = dict(CONFIG_TEMPLATE)
    cfg["agent_name"] = agent
    if args.store:
        cfg["store_id"] = args.store
    _write(run / "agent_config.json", json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", args.force)

    _write(run / artifact_name(agent, "context", gen),
           CONTEXT_TEMPLATE.format(agent=agent, gen=gen), args.force)
    _write(run / artifact_name(agent, "summary", gen),
           SUMMARY_TEMPLATE.format(agent=agent, gen=gen), args.force)

    index = {
        "agent_name": agent,
        "generation_id": gen,
        "handoff_id": gen,
        "store_id": cfg["store_id"],
        "commit_state": "prepared",
        "checkin_request_id": f"{agent}_{gen}_check_in",
        "index_file_id": "",
        "checkout": {
            "request_id": f"{agent}_{gen}_check_out",
            "handoff_id": gen,
            "action": "check_out",
            "verified": False,
            "event_page_id": "",
            "verification_method": "",
        },
        "context": {
            "file_id": "",
            "file_name": artifact_name(agent, "context", gen),
            "parent_id": cfg["store_id"],
            "hash_scope": "full_text",
            "normalization": "LF_UTF8_v1",
            "sha256": "",
        },
        "summary": {
            "file_id": "",
            "file_name": artifact_name(agent, "summary", gen),
            "parent_id": cfg["store_id"],
            "hash_scope": "full_text",
            "normalization": "LF_UTF8_v1",
            "sha256": "",
        },
    }
    _write(run / "index.json", json.dumps(index, ensure_ascii=False, indent=2) + "\n", args.force)
    print(f"prepared generation {gen} in {run}")
    print("next: fill context/summary, then run: handoff-kit seal --commit")
    return 0


def cmd_seal(args: argparse.Namespace) -> int:
    run = Path(args.dir)
    cfg = json.loads((run / "agent_config.json").read_text(encoding="utf-8-sig"))
    index = json.loads((run / "index.json").read_text(encoding="utf-8-sig"))
    agent, gen = cfg["agent_name"], index["generation_id"]
    for kind in ("context", "summary"):
        name = index[kind]["file_name"] or artifact_name(agent, kind, gen)
        path = run / name
        if not path.is_file():
            raise SystemExit(f"missing {kind} body: {path}")
        index[kind]["file_name"] = name
        index[kind]["parent_id"] = cfg["store_id"]
        index[kind]["normalization"] = "LF_UTF8_v1"
        index[kind]["sha256"] = sha256_lf_utf8_v1(path.read_bytes())
    if args.commit:
        index["commit_state"] = "committed"
    (run / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8", newline="\n")
    print(f"sealed hashes ({index['commit_state']}): context={index['context']['sha256'][:12]}... "
          f"summary={index['summary']['sha256'][:12]}...")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    report = check_generation(args.dir, args.config)
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        for check in report.checks:
            if check.ok:
                print(f"[ok  ] {check.code}")
            else:
                print(f"[FAIL] {check.code} {check.detail}")
        print(report.summary())
    return 0 if report.ok else 1


def cmd_prompt(args: argparse.Namespace) -> int:
    run = Path(args.dir)
    cfg = json.loads((run / "agent_config.json").read_text(encoding="utf-8-sig"))
    index = json.loads((run / "index.json").read_text(encoding="utf-8-sig"))
    print(render_prompt(cfg, index), end="")
    return 0


def cmd_hash(args: argparse.Namespace) -> int:
    for name in args.files:
        path = Path(name)
        print(f"{sha256_lf_utf8_v1(path.read_bytes())}  {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="handoff-kit", description="Fail-closed session handoff for LLM agents")
    parser.add_argument("--version", action="version", version=f"handoff-kit {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="scaffold a prepared generation")
    p.add_argument("--agent", required=True)
    p.add_argument("--dir", required=True)
    p.add_argument("--generation", default="")
    p.add_argument("--store", default="")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("seal", help="recompute and store the LF_UTF8_v1 hashes")
    p.add_argument("--dir", required=True)
    p.add_argument("--commit", action="store_true", help="also set commit_state to committed")
    p.set_defaults(func=cmd_seal)

    p = sub.add_parser("check", help="verify one generation offline")
    p.add_argument("--dir", required=True)
    p.add_argument("--config", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("prompt", help="render the new-conversation prompt")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("hash", help="compute the LF_UTF8_v1 SHA-256 of files")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_hash)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
