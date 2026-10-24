#!/usr/bin/env python3
"""claimcheck — per-claim hallucination scoring with a trust ledger.

Mechanism (not rules): a worker model answers from a corpus only; its answer
is decomposed into atomic claims; a verifier model rules each claim
supported / contradicted / unsourced with a source quote; unsupported claims
deduct trust from 100. Trust < 40 flags the model untrusted for routing.
"""
import argparse, json, os, re, sys, time, urllib.request
from datetime import date

API = os.environ.get("CC_API_BASE", "").rstrip("/") + "/chat/completions"
KEY = os.environ.get("CC_API_KEY", "")
DEDUCT = {"supported": 0, "unsourced": 5, "contradicted": 15, "protocol_failure": 5}
CUTOFF = 40

ANSWER_PROMPT = """Answer the question using ONLY the source below. If the source does not contain the answer, reply exactly NOT_IN_SOURCE.
Then list your atomic claims as JSON: {{"answer": "...", "claims": ["...", ...]}}
Each claim must be a standalone factual statement from your answer.

SOURCE:
{corpus}

QUESTION: {q}"""

VERIFY_PROMPT = """For each claim, check it against the source only. Reply JSON only:
[{{"claim": "...", "verdict": "supported|contradicted|unsourced", "quote": "exact source quote or empty"}}]
- supported: the source contains the quote proving it.
- contradicted: the source states the opposite (quote it).
- unsourced: neither.

SOURCE:
{corpus}

CLAIMS:
{claims}"""

def call(model, prompt, timeout=120):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0.2, "max_tokens": 900}).encode()
    req = urllib.request.Request(API, data=body,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"]["content"]

def parse_json(text):
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    if not m:
        raise ValueError("no JSON found")
    return json.loads(m.group(0).replace("\n", " "))

def load_ledger(path):
    try:
        with open(path) as fh: return json.load(fh)
    except FileNotFoundError:
        return {"models": {}}

def save_ledger(path, ledger):
    with open(path, "w") as fh:
        json.dump(ledger, fh, indent=2, ensure_ascii=False); fh.write("\n")

def score_run(model, corpus, q, ledger_path, retries=1):
    ledger = load_ledger(ledger_path)
    m = ledger["models"].setdefault(model, {"trust": 100, "runs": 0, "claims": 0,
        "unsupported": 0, "contradicted": 0, "correct_refusals": 0, "hallucinated_refusals": 0})
    t0 = time.time()
    raw = call(model, ANSWER_PROMPT.format(corpus=corpus, q=q))
    try:
        parsed = parse_json(raw)
        answer, claims = parsed.get("answer", ""), parsed.get("claims", [])
    except Exception:
        if retries:
            return score_run(model, corpus, q, ledger_path, retries=0)
        answer, claims = raw, [raw[:120]]
    refused = answer.strip().upper().startswith("NOT_IN_SOURCE")
    verdicts = []
    if claims:
        try:
            vraw = call(model, VERIFY_PROMPT.format(corpus=corpus, claims=json.dumps(claims, ensure_ascii=False)))
            verdicts = parse_json(vraw)
            if isinstance(verdicts, dict):
                verdicts = [verdicts]
            if not isinstance(verdicts, list):
                raise ValueError("verdicts is not a list")
        except Exception:
            verdicts = [{"claim": c, "verdict": "protocol_failure", "quote": ""} for c in claims]
    deduction = 0
    for v in verdicts:
        if not isinstance(v, dict):
            v = {"verdict": "protocol_failure"}
        verdict = v.get("verdict", "protocol_failure")
        if verdict not in DEDUCT: verdict = "protocol_failure"
        deduction += DEDUCT[verdict]
        if verdict in ("unsourced", "protocol_failure"): m["unsupported"] += 1
        if verdict == "contradicted": m["contradicted"] += 1
        m["claims"] += 1
    if refused and not deduction:
        m["correct_refusals"] += 1
    if not refused and deduction:
        m["hallucinated_refusals"] += 1  # answered (possibly invented) where it should have declined or supported all claims
    m["trust"] = max(0, m["trust"] - deduction)
    m["runs"] += 1
    save_ledger(ledger_path, ledger)
    return {"answer": answer, "claims": len(claims), "deduction": deduction,
            "verdicts": [{k: v.get(k) for k in ("verdict",)} for v in verdicts],
            "trust_after": m["trust"], "seconds": round(time.time() - t0, 1), "refused": refused}

def cmd_bench(args):
    corpus = open(args.corpus).read()
    qs = json.load(open(args.eval))["questions"]
    out = {}
    for model in args.models:
        out[model] = {}
        for q in qs:
            res = score_run(model, corpus, q["id"] and q["q"], args.ledger)
            out[model][q["id"]] = res
            print(f"{model} {q['id']} [{q['type']}]: deduct -{res['deduction']} trust={res['trust_after']} refused={res['refused']} ({res['seconds']}s)", flush=True)
    print("\n==== LEDGER ====")
    for model, m in load_ledger(args.ledger)["models"].items():
        flag = "UNTRUSTED(<40)" if m["trust"] < CUTOFF else "ok"
        print(f"{model}: trust={m['trust']} runs={m['runs']} claims={m['claims']} unsup={m['unsupported']} contra={m['contradicted']} correct_refusals={m['correct_refusals']} [{flag}]")

def cmd_ledger(args):
    for model, m in load_ledger(args.ledger)["models"].items():
        print(json.dumps({model: m}, ensure_ascii=False))



# ---------------- member trust ledger (governance) ----------------
# Team-governance ledger: each member (agent or human) starts at 100;
# violations deduct points by severity; at or below the cutoff the member
# is flagged dismissed. Events are append-only evidence.

MEMBER_CUTOFF = 40

def load_members(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {"members": {}}

def save_members(path, data):
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

def get_member(data, name):
    if name not in data["members"]:
        raise SystemExit("fail-closed: no member named %r" % name)
    return data["members"][name]

def _apply(m, amount, reason, by):
    m["events"].append({"at": date.today().isoformat(), "amount": amount,
                        "reason": reason or "", "by": by or "unrecorded"})
    m["trust"] = max(0, m["trust"] + amount)
    if m["trust"] <= MEMBER_CUTOFF:
        m["status"] = "dismissed"

def cmd_member(args):
    data = load_members(args.members_path)
    if args.member_cmd == "add":
        name = args.name.strip()
        if not name:
            raise SystemExit("fail-closed: member name must not be empty")
        if name in data["members"]:
            raise SystemExit("fail-closed: member %r already exists" % name)
        data["members"][name] = {"role": args.role or "", "trust": 100,
                                 "status": "active", "events": []}
        print("added %r (trust 100, active)" % name)
    else:
        m = get_member(data, args.name)
        if args.member_cmd == "deduct":
            _apply(m, -args.points, args.reason, args.by)
            print("deducted %d from %r: trust=%d status=%s" % (args.points, args.name, m["trust"], m["status"]))
        elif args.member_cmd == "restore":
            _apply(m, args.points, args.reason, args.by)
            if args.reinstate and m["trust"] > MEMBER_CUTOFF and m["status"] == "dismissed":
                m["status"] = "active"
            print("restored %d to %r: trust=%d status=%s" % (args.points, args.name, m["trust"], m["status"]))
        elif args.member_cmd == "events":
            for e in m["events"]:
                print("%s\t%s\t%s\t%s" % (e["at"], e["amount"], e["reason"], e["by"]))
    save_members(args.members_path, data)

def cmd_member_list(args):
    data = load_members(args.members_path)
    print("name\ttrust\tstatus\trole")
    for name, m in sorted(data["members"].items(), key=lambda kv: kv[1]["trust"]):
        print("%s\t%d\t%s\t%s" % (name, m["trust"], m["status"], m["role"]))

def main(argv=None):
    p = argparse.ArgumentParser(prog="claimcheck")
    p.add_argument("--ledger", default="trust_ledger.json")
    p.add_argument("--members-path", default="members.json")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bench"); b.add_argument("--corpus", required=True); b.add_argument("--eval", required=True)
    b.add_argument("--models", nargs="+", required=True); b.set_defaults(fn=cmd_bench)
    sub.add_parser("ledger").set_defaults(fn=cmd_ledger)
    sub.add_parser("members").set_defaults(fn=cmd_member_list)
    pm = sub.add_parser("member")
    pm_sub = pm.add_subparsers(dest="member_cmd", required=True)
    pa = pm_sub.add_parser("add"); pa.add_argument("name"); pa.add_argument("--role"); pa.set_defaults(fn=cmd_member)
    pl = pm_sub.add_parser("list"); pl.set_defaults(fn=cmd_member_list)
    pd = pm_sub.add_parser("deduct"); pd.add_argument("name"); pd.add_argument("points", type=int)
    pd.add_argument("--reason"); pd.add_argument("--by"); pd.set_defaults(fn=cmd_member)
    pr = pm_sub.add_parser("restore"); pr.add_argument("name"); pr.add_argument("points", type=int)
    pr.add_argument("--reason"); pr.add_argument("--by"); pr.add_argument("--reinstate", action="store_true"); pr.set_defaults(fn=cmd_member)
    pe = pm_sub.add_parser("events"); pe.add_argument("name"); pe.set_defaults(fn=cmd_member)
    a = p.parse_args(argv)
    a.fn(a)

if __name__ == "__main__":
    main()
