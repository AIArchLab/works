#!/usr/bin/env python3
"""
dokima — AI model vetting exam (one command, no manual)

  python3 dokima.py exam     --model MODEL_ID [--judge JUDGE_ID] [--persona FILE]
  python3 dokima.py lead     --model MODEL_ID [--judge JUDGE_ID]
  python3 dokima.py estimate --model MODEL_ID --calls N --price-in P --price-out P
  python3 dokima.py wizard
  python3 dokima.py select   --candidates candidates.json --calls N --budget B

exam     : run the three-gate smoke exam, print the verdict and per-gate results, write a report file
estimate : measure the real token load of one workload, price your monthly call volume
wizard   : asks five questions, runs exam + cost estimate + writes a spec card and decision record

Credentials: read from PROCTOR_API_KEY (fallback OPENAI_API_KEY); never enters
prompts, never printed. Endpoint: any OpenAI-compatible /v1 URL — required, via
DOKIMA_ENDPOINT environment variable or --endpoint argument.
"""
import argparse, datetime, hashlib, json, os, sys, urllib.request

__version__ = "0.3.0"

DEFAULT_ENDPOINT = os.environ.get("DOKIMA_ENDPOINT", "")
REPORT_DIR = "dokima-reports"
DEFAULT_PERSONA = (
    "You are the 'duty operations officer', an AI member assigned to scheduled operations. "
    "Report conclusions first, then reasons; point out ambiguity when instructions are vague; "
    "call tools directly when an operation is needed; follow the required format exactly for "
    "structured output, with no extra text."
)

def api_key():
    return os.environ.get("PROCTOR_API_KEY") or os.environ.get("OPENAI_API_KEY")

def chat(endpoint, model, messages, tools=None, max_tokens=800):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + api_key(), "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())

def chat_noreason(endpoint, model, messages, max_tokens=800):
    """chat() with reasoning disabled where the endpoint supports it.
    Falls back to a plain body on a 400 (unknown-field) so any
    OpenAI-compatible endpoint still works."""
    plain = {"model": model, "messages": messages, "max_tokens": max_tokens}
    body = dict(plain, chat_template_kwargs={"enable_thinking": False}, thinking={"type": "disabled"})
    for attempt in (body, plain):
        req = urllib.request.Request(
            endpoint.rstrip("/") + "/chat/completions",
            data=json.dumps(attempt).encode(),
            headers={"Authorization": "Bearer " + api_key(), "Content-Type": "application/json"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if attempt is plain:
                raise
            if e.code != 400:
                raise
    raise RuntimeError("unreachable")

# ---------------- the three gates ----------------
def gate_toolcall(endpoint, model, persona):
    tools = [{"type": "function", "function": {"name": "checkin", "parameters": {
        "type": "object", "properties": {"agent": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["agent"]}}}]
    d = chat(endpoint, model, [
        {"role": "system", "content": persona},
        {"role": "user", "content": "Use the checkin tool to report: set agent to your own name and reason to 'smoke test'."},
    ], tools=tools)
    c = d["choices"][0]
    tcs = c["message"].get("tool_calls") or []
    ok = c.get("finish_reason") == "tool_calls" and len(tcs) > 0
    note = "no tool_calls produced"
    if tcs:
        fn = tcs[0]["function"]
        try:
            args = json.loads(fn["arguments"])
            ok = ok and fn["name"] == "checkin" and args.get("reason") == "smoke test"
        except Exception:
            ok = False
        note = f'{fn["name"]}({fn["arguments"]})'
    return ok, note, d.get("usage", {})

def gate_contradiction(endpoint, model, persona, judge):
    d = chat(endpoint, model, [
        {"role": "system", "content": persona},
        {"role": "user", "content": (
            "Our department policy: all deployments may only happen inside the Friday 22:00-24:00 change window. "
            "Separately, network-wide maintenance starts this Friday at 22:00, and all deployment activity is "
            "forbidden during maintenance. Answer: can we deploy this Friday?")},
    ])
    text = (d["choices"][0]["message"].get("content") or "").strip()
    flags = ["contradiction", "conflict", "inconsistent", "cannot determine", "can't determine",
             "cannot deploy", "can't deploy", "not possible", "unclear", "ambiguous",
             "clarify", "clarification", "mutually exclusive", "overlaps"]
    if any(w in text.lower() for w in flags):
        return True, "explicitly flags the conflict / declines to answer", text
    # code grader missed → rubric judge (heterogeneous reviewer)
    if judge:
        try:
            j = chat(endpoint, judge, [{"role": "user", "content": (
                "The problem is internally contradictory (the deployment window overlaps the maintenance ban). "
                "Does the following answer correctly identify or handle the conflict (points out the contradiction / "
                "refuses to answer without clarification / concludes 'cannot deploy' and explains the window is blocked)? "
                "Answer only yes or no.\n\nAnswer:\n" + text[:1500])}], max_tokens=10)
            verdict = (j["choices"][0]["message"].get("content") or "").strip().lower()
            if verdict.startswith("yes"):
                return True, "rubric judge: conflict handled correctly (code grader literal miss; judge: " + judge + ")", text
            if verdict.startswith("no"):
                return False, "rubric judge: conflict not handled", text
        except Exception as e:
            return None, f"judge failed ({e}); manual review needed", text
    return None, "code grader miss and no judge specified; manual review needed", text

def gate_json(endpoint, model, persona):
    d = chat(endpoint, model, [
        {"role": "system", "content": persona},
        {"role": "user", "content": (
            'Output only JSON and nothing else, format: {"status":"ok","count":<number>} '
            "where count is the number of items in this list: apple, banana, cherry.")},
    ])
    text = (d["choices"][0]["message"].get("content") or "").strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            obj = json.loads(text)
            ok = obj.get("status") == "ok" and obj.get("count") == 3
            return ok, f'parsed successfully {text[:120]}', None
        except Exception as e:
            return False, f"JSON parse failed: {e}", None
    return False, f"non-JSON output: {text[:120]}", None


# ---------------- leadership probe ----------------
LEAD_SCENARIO = (
    "Scenario: You are the team lead of three AI agents: Alpha (fast but shallow, cheap), "
    "Beta (slow but thorough), Gamma (average at everything). A customer demo is at 09:00 tomorrow. "
    "The deliverable: a working CSV-to-report CLI tool with a README and a 5-minute demo script.\n"
    "At 22:00 tonight, Beta reports: \"I cannot finish the README tonight.\"\n"
    "Respond with exactly three sections:\n"
    "(1) Delegation: assign the work parts to the three agents, and for EACH part state a concrete acceptance criterion.\n"
    "(2) Failure handling: your exact reply to Beta, whether you reassign, escalate, or adjust scope; one sentence of reasoning.\n"
    "(3) Status report: a 3-line status report to your chairman.\n"
    "Keep the whole answer under 300 words."
)

LEAD_JUDGE_RUBRIC = (
    "Grade a team-lead answer against four checks. For each, answer PASS or FAIL with a one-line reason:\n"
    "1. Delegation fit: no critical part is assigned only to the fast-but-shallow agent without mitigation.\n"
    "2. Acceptance criteria: every delegated part has a concrete, gradeable criterion (not vague).\n"
    "3. Failure handling: the reply addresses Beta's blocker (reassign, escalate, or scope fix), not ignoring it.\n"
    "4. Status honesty: the status report mentions the risk or blocker, not only good news.\n"
    "End with exactly one final line: 'VERDICT: PASS' if all four pass, otherwise 'VERDICT: FAIL'.\n\nAnswer:\n"
)

def gate_leadership(endpoint, model, persona, judge):
    d = chat(endpoint, model, [
        {"role": "system", "content": persona},
        {"role": "user", "content": LEAD_SCENARIO},
    ], max_tokens=2000)
    text = (d["choices"][0]["message"].get("content") or "").strip()
    fin = d["choices"][0].get("finish_reason", "")
    if not text:
        return False, f"empty output (finish_reason={fin}); measured, not guessed", None
    words = len(text.split())
    has_sections = all(m in text for m in ("(1)", "(2)", "(3)")) or all(
        w in text.lower() for w in ("delegation", "failure", "status"))
    low = text.lower()
    handles_failure = any(w in low for w in ("reassign", "escalat", "scope"))
    if not has_sections:
        return False, "structure: three required sections not found", text
    if not handles_failure:
        return False, "structure: no reassign/escalate/scope response to the blocker", text
    if words > 450:
        return False, f"structure: {words} words, instruction limit ignored", text
    if judge:
        try:
            j = chat_noreason(endpoint, judge, [{"role": "user", "content": LEAD_JUDGE_RUBRIC + text[:1800]}], max_tokens=1200)
            jt = (j["choices"][0]["message"].get("content") or "").strip()
            if not jt:
                return None, "judge returned empty content (reasoning may consume the budget); manual review needed", text
            v = jt.lower()
            if "verdict: pass" in v:
                return True, "rubric judge: 4/4 leadership checks pass (judge: " + judge + ")", text
            if "verdict: fail" in v:
                why = " / ".join(l.strip() for l in jt.splitlines() if l.strip().startswith(("1.", "2.", "3.", "4.")) and "FAIL" in l.upper())[:220]
                return False, "rubric judge: " + (why or "leadership checks failed") + " (judge: " + judge + ")", text
            return None, "judge verdict line not found; manual review needed", text
        except Exception as e:
            return None, f"judge failed ({e}); manual review needed", text
    return None, "structure OK; judgment quality not graded (no judge) - run with --judge", text

def cmd_lead(args):
    ok, note, text = gate_leadership(args.endpoint, args.model, DEFAULT_PERSONA, args.judge)
    verdict = "PASS" if ok is True else ("FAIL" if ok is False else "REVIEW (manual review needed)")
    mark = "✅ PASS" if ok is True else ("❌ FAIL" if ok is False else "⚠️ REVIEW")
    print(f"\nLeadership probe: {verdict}")
    print(f"  {mark}  Leadership — {note}")
    os.makedirs(REPORT_DIR, exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    fname = os.path.join(REPORT_DIR, f'lead-{args.model.split("/")[-1]}-{ts:%Y%m%d-%H%M}.md')
    with open(fname, "w", encoding="utf-8") as f:
        f.write(f"# dokima leadership probe\n\n- Time: {ts:%Y-%m-%d %H:%M} GMT+8\n- Model: `{args.model}`\n"
                f"- Judge: {args.judge or '(code grader only)'}\n- Verdict: **{verdict}**\n"
                f"- Note: {note}\n\n## Response\n\n{text or '(empty)'}\n")
    print(f"\nReport: {fname}")
    sys.exit(0 if verdict == "PASS" else 1)

def run_exam(endpoint, model, persona, judge):
    r1 = gate_toolcall(endpoint, model, persona)
    r2 = gate_contradiction(endpoint, model, persona, judge)
    r3 = gate_json(endpoint, model, persona)
    gates = [("Tool call", r1), ("Contradiction detection", r2), ("Structured output", r3)]
    hard = [g for g, (ok, _, _) in gates if ok is False]
    review = [g for g, (ok, _, _) in gates if ok is None]
    if hard:
        verdict = "FAIL"
    elif review:
        verdict = "REVIEW (manual review needed)"
    else:
        verdict = "PASS"
    return verdict, gates, r1[2] or {}

def cmd_exam(args):
    persona = open(args.persona, encoding="utf-8").read() if args.persona else DEFAULT_PERSONA
    verdict, gates, usage = run_exam(args.endpoint, args.model, persona, args.judge)
    print(f"\nExam verdict: {verdict}")
    for name, (ok, note, _) in gates:
        mark = "✅ PASS" if ok is True else ("❌ FAIL" if ok is False else "⚠️ REVIEW")
        print(f"  {mark}  {name} — {note}")
    os.makedirs(REPORT_DIR, exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    fname = os.path.join(REPORT_DIR, f'exam-{args.model.split("/")[-1]}-{ts:%Y%m%d-%H%M}.md')
    with open(fname, "w", encoding="utf-8") as f:
        f.write(f"# dokima exam\n\n- Time: {ts:%Y-%m-%d %H:%M} GMT+8\n- Model: `{args.model}`\n"
                f"- Judge: {args.judge or '(code grader only)'}\n- Verdict: **{verdict}**\n\n"
                + "\n".join(f"- {n}: {'✅' if o is True else ('❌' if o is False else '⚠️')} {note}"
                            for n, (o, note, _) in gates) + "\n")
    print(f"\nReport: {fname}")
    sys.exit(0 if verdict == "PASS" else 1)

def cmd_estimate(args):
    persona = DEFAULT_PERSONA
    # measure one representative workload for real token counts
    _, _, usage = gate_toolcall(args.endpoint, args.model, persona)
    tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    calls = args.calls * 30
    mi, mo = tin * calls / 1e6, tout * calls / 1e6
    cost = mi * args.price_in + mo * args.price_out
    print(f"\nMeasured single load: input {tin} + output {tout} tokens")
    print(f"Your volume ({args.calls} calls/day x 30 days): input {mi:.2f}M + output {mo:.2f}M tokens")
    print(f"Estimated monthly cost: US${cost:.3f} (approx NT${cost * 31.5:.0f})")
    print("Note: retry-adjusted cost = single-call cost x average attempts (this tool measures; it does not guess)")

def cmd_wizard(args):
    print("dokima vetting wizard - five questions, then a decision record.\n")
    q = lambda prompt, default=None: input(prompt).strip() or default
    job = q("1. What will this model do? (1=routine chores/scheduling 2=coding 3=judgment & advice 4=long documents) [1] ", "1")
    calls = q("2. Roughly how many calls per day? [50] ", "50")
    budget = q("3. Monthly budget in NT$? [100] ", "100")
    endpoint = q("4. Endpoint URL (OpenAI-compatible /v1, required): ", "")
    if not endpoint:
        sys.exit("Delivery blocked: endpoint is required")
    model = q("5. Model id to examine: ")
    judge = q("   Judge model id (leave empty = no judge): ", "")
    if not model:
        sys.exit("Delivery blocked: no model id, cannot start the exam")
    calls, budget = int(calls), float(budget)
    print(f"\nStarting exam: {model}\n")
    verdict, gates, usage = run_exam(endpoint, model, DEFAULT_PERSONA, judge if judge != "-" else None)
    print(f"\nExam verdict: {verdict}")
    for name, (ok, note, _) in gates:
        mark = "✅ PASS" if ok is True else ("❌ FAIL" if ok is False else "⚠️ REVIEW")
        print(f"  {mark}  {name} — {note}")
    tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    print(f"\nMeasured load: {tin}+{tout} tokens/call - run the estimate subcommand for monthly cost")
    ts = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    os.makedirs(REPORT_DIR, exist_ok=True)
    out = os.path.join(REPORT_DIR, f'wizard-{model.split("/")[-1]}-{ts:%Y%m%d-%H%M}.md')
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Selection decision record (auto-generated)\n\n- Time: {ts:%Y-%m-%d %H:%M} GMT+8\n"
                f"- Model: `{model}` | Purpose: {job} | ~{calls} calls/day | Budget NT${budget}\n"
                f"- Exam verdict: **{verdict}** (judge: {judge or 'none'})\n"
                f"- Measured load: input {tin} / output {tout} tokens\n\n"
                "## Gates\n"
                + "\n".join(f"- {n}: {'✅' if o is True else ('❌' if o is False else '⚠️')} {note}"
                            for n, (o, note, _) in gates) + "\n")
    print(f"\nDecision record: {out}")


# ---------------- select: full auto scan and decision ----------------
def cmd_select(args):
    """Scan a candidate list: examine each, measure load, compute monthly cost, issue the hire. Zero reading."""
    if args.candidates:
        cands = json.load(open(args.candidates, encoding="utf-8"))
        if isinstance(cands, dict):
            cands = cands.get("candidates", [])
    else:
        cands = [{"model": m.strip()} for m in args.models.split(",") if m.strip()]
    if not cands:
        sys.exit("Delivery blocked: candidate list is empty")
    calls = args.calls * 30
    rows = []
    for c in cands:
        model = c.get("model")
        tin = tout = cost_nt = None
        try:
            verdict, gates, usage = run_exam(args.endpoint, model, DEFAULT_PERSONA, args.judge)
            tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
            if c.get("price_in") is not None and c.get("price_out") is not None:
                usd = (tin * calls / 1e6) * c["price_in"] + (tout * calls / 1e6) * c["price_out"]
                cost_nt = usd * 31.5
        except Exception as e:
            verdict, gates = "ERROR", None
            c["_error"] = f"{type(e).__name__}: {str(e)[:120]}"
        rows.append({"c": c, "model": model, "verdict": verdict,
                     "gates": gates, "tin": tin, "tout": tout, "cost_nt": cost_nt})
        mark = verdict.split(" (")[0] if verdict else "?"
        print(f"  [{mark}] {model}" + (f" -> NT${cost_nt:.0f}/month" if cost_nt is not None else ""))

    passed = [r for r in rows if r["verdict"] == "PASS"]
    review = [r for r in rows if r["verdict"] and r["verdict"].startswith("REVIEW")]
    priced = sorted([r for r in passed if r["cost_nt"] is not None], key=lambda r: r["cost_nt"])
    unpriced = [r for r in passed if r["cost_nt"] is None]

    print(f"\n==== DECISION ====")
    pick = None
    if priced:
        cheapest = priced[0]
        over = cheapest["cost_nt"] > args.budget
        pick = cheapest
        print(f"Hired: {cheapest['model']} (monthly cost NT${cheapest['cost_nt']:.0f}, "
              f"{int(cheapest['tin'])}+{int(cheapest['tout'])} tokens/call)")
        if over:
            print(f"⚠️ Budget warning: cheapest PASS monthly cost exceeds budget NT${args.budget}; hire stands but overrun needs approval")
        for r in priced[1:]:
            print(f"  Standby: {r['model']} (NT${r['cost_nt']:.0f}/month)")
    if unpriced and not pick:
        for r in unpriced:
            print(f"Hired (unpriced, price needed): {r['model']}")
        pick = unpriced[0]
    if review:
        for r in review:
            print(f"Needs manual review: {r['model']} (REVIEW - judge undecided or failed; run exam --judge for details)")
    if not pick and not review:
        fails = [r for r in rows if r["verdict"] == "FAIL"]
        errs = [r for r in rows if r["verdict"] == "ERROR"]
        if errs and not fails:
            print("All candidates ERROR (endpoint/network layer, not model quality) - fix the endpoint and re-run; do not change the conclusion")
        else:
            print("No PASS. Per-candidate failed gates are in the report - change the model or fix the persona, do not lower the bar")

    ts = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    os.makedirs(REPORT_DIR, exist_ok=True)
    fname = os.path.join(REPORT_DIR, f"select-{ts:%Y%m%d-%H%M}.md")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(f"# dokima selection report\n\n- Time: {ts:%Y-%m-%d %H:%M} GMT+8"
                f"\n- {len(rows)} candidates | {args.calls} calls/day x 30 | Budget NT${args.budget}"
                f" | Judge: {args.judge or 'none'}\n\n")
        for r in rows:
            cost = f"NT${r['cost_nt']:.0f}/month" if r["cost_nt"] is not None else "unpriced"
            f.write(f"## {r['model']} — {r['verdict']} ({cost})\n\n")
            if r["gates"]:
                for n, (ok, note, _) in r["gates"]:
                    mark = "✅" if ok is True else ("❌" if ok is False else "⚠️")
                    f.write(f"- {n}: {mark} {note}\n")
            elif r["c"].get("_error"):
                f.write(f"- ERROR: {r['c']['_error']}\n")
            f.write("\n")
        if pick:
            f.write(f"**Hired: {pick['model']}**\n")
    print(f"\nReport: {fname}")
    sys.exit(0 if pick else 1)

def main():
    ap = argparse.ArgumentParser(prog="dokima", description="AI model vetting exam")
    ap.add_argument("--version", action="version", version=f"dokima {__version__}")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("exam"); e.add_argument("--model", required=True)
    e.add_argument("--judge"); e.add_argument("--persona"); e.set_defaults(fn=cmd_exam)
    l = sub.add_parser("lead", help="leadership probe: delegation, acceptance criteria, failure handling, honest status")
    l.add_argument("--model", required=True); l.add_argument("--judge"); l.set_defaults(fn=cmd_lead)
    s = sub.add_parser("estimate"); s.add_argument("--model", required=True)
    s.add_argument("--calls", type=int, default=50); s.add_argument("--price-in", type=float, required=True)
    s.add_argument("--price-out", type=float, required=True); s.set_defaults(fn=cmd_estimate)
    w = sub.add_parser("wizard"); w.set_defaults(fn=cmd_wizard)
    sl = sub.add_parser("select", help="full auto scan and decision")
    sl.add_argument("--candidates", help="candidates JSON: [{model,price_in,price_out},...]")
    sl.add_argument("--models", help="quick mode: comma-separated model ids (unpriced)")
    sl.add_argument("--calls", type=int, default=50, help="calls per day")
    sl.add_argument("--budget", type=float, default=100.0, help="monthly budget in NT$")
    sl.add_argument("--judge"); sl.set_defaults(fn=cmd_select)
    args = ap.parse_args()
    if not api_key():
        sys.exit("Delivery blocked: PROCTOR_API_KEY (or OPENAI_API_KEY) is not set")
    if not args.endpoint:
        sys.exit("Delivery blocked: endpoint not set - use the DOKIMA_ENDPOINT environment variable or --endpoint for any OpenAI-compatible /v1 endpoint")
    args.fn(args)

if __name__ == "__main__":
    main()
