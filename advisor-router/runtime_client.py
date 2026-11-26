"""Runtime-side example: sticky loop. The runtime owns state, keys, and usage accounting.
The advisor only returns a model name."""
import os, httpx, yaml

ADVISOR = os.getenv("ADVISOR_URL", "http://127.0.0.1:8099")
REG = yaml.safe_load(open("models.yaml"))["models"]       # runtime has keys
usage_ledger = {"in": 0, "out": 0}                         # usage accounting stays HERE

def decide(**kw):
    return httpx.post(f"{ADVISOR}/decide", json=kw, timeout=5).json()

def call_model(tier, messages):
    """Replace with real provider calls. normalize() is where per-provider
    tool-calling quirks get absorbed, written once."""
    m = REG[tier]
    key = os.getenv(m["api_key_env"], "")            # credentials never leave the runtime
    payload = normalize(messages, m["provider"])
    # resp = httpx.post(m["endpoint"] + ..., headers=..., json=payload)
    resp = {"text": f"[fake {m['name']} reply]", "tokens_in": 500, "tokens_out": 200, "ok": True}
    usage_ledger["in"] += resp["tokens_in"]; usage_ledger["out"] += resp["tokens_out"]
    return resp

def normalize(messages, provider):
    # canonical [{role, content, tool_calls?}] -> provider schema
    return messages

def struggling(resp, fails):
    if not resp["ok"]: return "call_error"
    if fails >= 3: return "tool_error_x3"
    return None

def run_task(task_id, steps):
    messages, tier, fails = [], None, 0              # state lives in the runtime
    for step_type, text in steps:
        if tier is None:                              # entry classification, once
            tier = decide(task_id=task_id, step_type=step_type, text=text)["tier"]
        while True:
            messages.append({"role": "user", "content": text})
            resp = call_model(tier, messages)
            why = struggling(resp, fails)
            if not why: break
            up = decide(task_id=task_id, step_type=step_type, text=text,
                        phase="reask", current_tier=tier, struggle=why)
            if up["tier"] == tier: break              # already strongest
            tier, fails = up["tier"], 0               # upgrade only, same messages re-sent
        messages.append({"role": "assistant", "content": resp["text"]})
    print("tier:", tier, "ledger:", usage_ledger)

if __name__ == "__main__":
    run_task("demo-1", [("plan", "design the migration"), ("code_edit", "apply it")])
