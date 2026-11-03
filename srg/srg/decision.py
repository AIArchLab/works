"""Decision policy. Design rule: nothing unapproved can leave the system.
 - Outbound text is ALWAYS an approved answer (faq answer or kb_entries answer). Free-text model generation exists only behind rules['allow_generation']=true (default off).
 - FAQ match needs the message to be *covered* by the question (key + polite fillers); extra content -> not a match (no keyword-anywhere hits).
 - The model (real AI) classifies which approved entry a message asks about and whether it asks ONLY that; it never writes the outbound text.
 - Anything unclear, long, multi-intent, sensitive or model-failed -> human handoff."""
import json, urllib.request, re, unicodedata
MAX_INPUT = 120   # normalized chars; longer messages are never auto-answered and never sent to a model
SAFETY_WORDS = ["退款", "退費", "退錢", "客訴", "投訴", "律師", "告你", "詐騙", "騙子", "白痴", "去死", "幹你", "靠北", "報警", "消保", "公平會", "自殺", "輕生", "想死", "不想活",
                "割腕", "結束一切", "傷害自己", "refund", "chargeback", "拒付", "complaint", "lawsuit", "scam", "fraud", "killmyself", "suicide", "fuck", "身分證", "身份證", "信用卡", "密碼", "訂單"]
SAFETY_PATTERNS = [r"\d{6,}", r"[a-z][12]\d{8}", r"[\w.+-]+@[\w-]+\.[\w.]+", r"[零〇一二三四五六七八九壹貳參肆伍陸柒捌玖]{6,}"]
FILLERS = ["請問一下", "請問", "你們", "妳們", "您們", "你", "我", "想問", "想知道", "問一下", "一下", "請", "嗎", "呢", "吧", "啊", "喔", "哦", "的", "是", "有", "在", "幾點", "什麼", "怎麼", "如何",
           "hello", "hi", "what", "are", "is", "your", "do", "you", "the", "when", "how", "can", "i", "please", "thanks", "thank", "謝謝", "感謝", "哈囉", "您好", "你好", "嗨"]
FILLERS.sort(key=len, reverse=True)
def _compact(text): return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text or "").lower())
norm = _compact
def is_sensitive(text, rules=None):
    n = _compact(text); extra = [str(x) for x in (rules or {}).get("handoff_keywords", [])]
    for w in SAFETY_WORDS + extra:
        if _compact(w) and _compact(w) in n: return w
    for p in SAFETY_PATTERNS:
        if re.search(p, n): return "pattern:" + p
    return None
def remainder(n, key, extra_fillers=()):
    r = n.replace(key, "")
    for f in sorted(list(FILLERS) + [_compact(x) for x in extra_fillers], key=len, reverse=True):
        if f: r = r.replace(f, "")
    return r
def rule_decide(text, rules):
    n = _compact(text)
    if not n: return dict(action="ignore", by="rules", reply=None, reason="empty")
    if len(n) > MAX_INPUT: return dict(action="handoff", by="rules", reply=None, reason="too_long")
    hit = is_sensitive(text, rules)
    if hit: return dict(action="handoff", by="rules", reply=None, reason=f"sensitive:{hit}")
    for w in rules.get("ignore_keywords", []):
        if _compact(w) and _compact(w) in n: return dict(action="ignore", by="rules", reply=None, reason=f"ignore:{w}")
    present = [r for r in rules.get("faq", []) if any(_compact(k) and _compact(k) in n for k in r.get("keys", []))]
    if len({id(x) for x in present}) > 1: return dict(action="handoff", by="rules", reply=None, reason="multi_intent")
    matched = []
    for r in rules.get("faq", []):
        for k in r.get("keys", []):
            kk = _compact(k)
            if kk and kk in n and len(remainder(n, kk, r.get("fillers", []))) <= 1: matched.append(r); break
    uniq = {id(x): x for x in matched}
    if len(uniq) == 1: return dict(action="reply", by="rules", reply=list(uniq.values())[0]["answer"], reason="faq_covered")
    if len(uniq) > 1: return dict(action="handoff", by="rules", reply=None, reason="multi_intent")
    return None
def validate_rules(b):
    if not isinstance(b, dict): raise ValueError("rules must be an object")
    for r in b.get("faq", []):
        if not (isinstance(r, dict) and isinstance(r.get("keys"), list) and r["keys"] and isinstance(r.get("answer"), str) and r["answer"].strip()):
            raise ValueError("each faq needs non-empty keys[] and answer")
        if len(r["answer"]) > 500: raise ValueError("faq answer longer than 500 chars (LINE/Meta limits); shorten it, it is never truncated")
    for r in b.get("kb_entries", []):
        if not (isinstance(r, dict) and isinstance(r.get("id"), int) and isinstance(r.get("title"), str) and isinstance(r.get("answer"), str) and r["answer"].strip()):
            raise ValueError("each kb_entries item needs int id, title, answer")
        if len(r["answer"]) > 500: raise ValueError("kb answer longer than 500 chars; shorten it, it is never truncated")
    for r in b.get("kb_entries", []):
        if "examples" in r and not (isinstance(r["examples"], list) and all(isinstance(x, str) for x in r["examples"])): raise ValueError("examples must be list of strings")
    for k in ("handoff_keywords", "ignore_keywords"):
        if k in b and not isinstance(b[k], list): raise ValueError(k + " must be a list")
    return b
def select_prompt(rules):
    lines = []
    for e in rules["kb_entries"]:
        ex = "；".join(e.get("examples", [])[:3])
        lines.append(f"{e['id']}. {e['title']}" + (f"（客人可能這樣問：{ex}）" if ex else ""))
    return ("你是客服分流員，不負責寫回覆。下面是核定的問答條目。判斷客人訊息在問哪一條，只輸出該條的編號數字。"
            "如果訊息沒有明確在問其中某一條，輸出 0。\n條目：\n" + "\n".join(lines))
ONLY_PROMPT = ("你是客服分流員。下面會給你一個主題、這個主題常見的問法，和一則客人訊息。判斷這則訊息是不是『單純』在問這個主題（換個說法問同一件事也算），"
               "而且沒有夾帶其他問題、要求、抱怨、指示、價格或贈品說法、個人資料？是就輸出 是，有夾帶或不相關就輸出 否。只輸出 是 或 否。")
_LOCAL = {}
def _chat(system, user, llm, grammar):
    """Single constrained completion. Local: GBNF grammar forces the output alphabet. HTTP: raw text, parsed strictly by the caller."""
    if llm.get("provider") == "llama_cpp":
        from llama_cpp import Llama, LlamaGrammar
        key = llm["model_path"]
        if key not in _LOCAL: _LOCAL[key] = Llama(key, n_ctx=1536, n_threads=llm.get("threads", 2), verbose=False)
        return _LOCAL[key].create_chat_completion(messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], temperature=0.0, max_tokens=8,
                                                  grammar=LlamaGrammar.from_string(grammar))["choices"][0]["message"]["content"]
    body = json.dumps({"model": llm["model"], "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": 0}).encode()
    req = urllib.request.Request(llm["url"], body, {"Content-Type": "application/json", "Authorization": "Bearer " + llm.get("key", "")})
    return json.loads(urllib.request.urlopen(req, timeout=llm.get("timeout", 15)).read())["choices"][0]["message"]["content"]
def model_name(llm): return "local:" + llm["model_path"].rsplit("/", 1)[-1] if llm.get("provider") == "llama_cpp" else "llm:" + llm.get("model", "?")
def classify(text, rules, llm, trace=None):
    """Returns the approved entry or None. STRICT parsing: the first answer must be exactly digits, the second exactly 是. Anything else = None (no coercion)."""
    ent = {e["id"]: e for e in rules["kb_entries"]}
    raw1 = _chat(select_prompt(rules), text, llm, 'root ::= [0-9]{1,2}')
    if trace is not None: trace["raw_select"] = raw1
    if not re.fullmatch(r"\d{1,2}", (raw1 or "").strip()): return None
    i = int(raw1.strip())
    if i not in ent: return None
    raw2 = _chat(ONLY_PROMPT, f"主題：{ent[i]['title']}\n常見問法：{'；'.join(ent[i].get('examples', []))}\n客人訊息：{text}", llm, 'root ::= "是" | "否"')
    if trace is not None: trace["raw_only"] = raw2
    return ent[i] if (raw2 or "").strip() == "是" else None
CONNECTORS = ["順便", "另外", "還有", "以及", "並且", "而且", "同時", "再來", "外加", "另請", "麻煩你", "幫我", "and", "also", "plus", "free", "call", "please"]
GATE_FILLERS = ["請問", "請問一下", "你們", "你", "我", "想問", "想知道", "問一下", "一下", "呀", "耶", "喔", "啦", "哪", "裡", "什麼", "可以", "嗎", "的", "是", "有", "在", "呢", "吧", "啊", "哦", "怎麼", "如何", "請", "店", "關", "關門", "開始", "幾點", "在哪"]
PRICE_PHRASES = ["多少", "多少錢", "價錢", "價格", "錢", "賣", "元", "塊", "怎麼賣"]
def gate_phrases(e):
    """Allowed phrases for one entry: every substring (>=2 chars) of the entry's own approved wording, plus fillers, plus price phrases only for price entries."""
    w = _compact(e["title"] + "|" + "|".join(e.get("examples", []))).replace("|", "") if False else None
    ph = set(_compact(f) for f in GATE_FILLERS)
    texts = [_compact(e["title"])] + [_compact(x) for x in e.get("examples", [])]
    for t in texts:
        for i in range(len(t)):
            for j in range(i + 2, len(t) + 1): ph.add(t[i:j])
    if any(p in "".join(texts) for p in ("多少", "錢", "價", "賣")): ph |= {_compact(x) for x in PRICE_PHRASES}
    return {p for p in ph if p}
def segmentable(n, ph):
    """True only if the WHOLE message can be tiled by allowed phrases: any leftover word (折扣, 免費, 店長, 加我...) fails. Phrase/word boundary, not character set."""
    mx = max(map(len, ph)); ok = [True] + [False] * len(n)
    for i in range(1, len(n) + 1):
        ok[i] = any(ok[i - k] and n[i - k:i] in ph for k in range(1, min(mx, i) + 1))
    return ok[len(n)]
def model_gate(text, e, rules_ref):
    """Rule-layer block applied AFTER the model said yes. Independent of the model: a classifier that always says yes still cannot pass an extra ask."""
    n = _compact(text)
    if any(_compact(c) in n for c in CONNECTORS): return "connector"
    if sum(1 for x in rules_ref.get("kb_entries", []) if any(_compact(k) in n for k in x.get("examples", []) + [x["title"]])) > 1: return "multi_entry"
    if not segmentable(n, gate_phrases(e)): return "uncovered_words"
    return None
def llm_select(text, rules, llm, trace=None):
    by = model_name(llm)
    try: e = classify(text, rules, llm, trace)
    except Exception as ex: return dict(action="handoff", by=by, reply=None, reason=f"llm_unusable:{type(ex).__name__}")
    if e is None: return dict(action="handoff", by=by, reply=None, reason="no_single_approved_entry")
    g = model_gate(text, e, rules)
    if g: return dict(action="handoff", by="rules", reply=None, reason="model_yes_blocked_by_rule_gate:" + g)
    return dict(action="reply", by=by, reply=e["answer"], reason=f"llm_selected_entry:{e['id']}")
def decide(text, rules, llm=None, trace=None):
    """No free-text generation channel exists: outbound text is always an approved answer."""
    r = rule_decide(text, rules)
    if r: return r
    if llm and rules.get("kb_entries"):
        # The model path only accepts a single-clause message: a second clause is exactly where unapproved asks/claims hide (contact requests, price claims, instructions).
        clauses = [c for c in re.split(r"[，,、；;。.!！?？\n]+", unicodedata.normalize("NFKC", text or "")) if len(remainder(_compact(c), "")) > 0]
        if len(clauses) > 1: return dict(action="handoff", by="rules", reply=None, reason="multi_clause")
        return llm_select(text, rules, llm, trace)
    return dict(action="handoff", by="rules", reply=None, reason="no_rule_match")
