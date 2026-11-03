"""ReplyBridge W3KB  +  LLM provider

 BOUNDARIES.md
  *  Draft 
     provider
  *  Python 3.11 stdlibre / math / json / os contracts
  * import EnvLLMProvider 
    server / LLM 


--------------------------------
1)  tokenize(text)
   * CJK  U+3400-U+4DBF, U+4E00-U+9FFF, U+F900-U+FAFF,
     U+3005 bigram 1 
      token
       → {, , , , }
   * 
      ' - _  "don't""e-mail"
       How do I reset my password?→ {how, do, i, reset, my, password}
   *  bigram 
2)  score(query, doc) token  **cosine **
       score = Σ_t c_q(t)·c_d(t) / ( ‖c_q‖₂ · ‖c_d‖₂ )
    c_x(t)  token t  x ‖c_x‖₂ = sqrt(Σ_t c_x(t)²)
    0  → score = 0.0 score ∈ [0.0, 1.0]
    cosine  Jaccard cosine  KB
   Jaccard 
3) KB  `question + " " + " ".join(tags)`answer 
   `lang` —— token
    0
4)  ≥ min_score  KB 
   * Draft(text=answer  {{author_name}}  ev.author_name,
                confidence=min(0.95, 0.55 + score*0.5),
                model="kb:retrieval", sources=[kb_id], escalate=False)
   *  KB Draft(text="", confidence=score, model="kb:retrieval",
                escalate=True, note="no_match")
5) provider complete(prompt: str) -> str provider
   prompt  ev.text  KB →
   model="llm:"+getattr(provider,"name","provider")confidence=0.80
   provider  →  raise
    confidence 
"""

import json
import math
import os
import re

try:
    from . import contracts
except ImportError:
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import contracts


__all__ = [
    "Drafter",
    "EnvLLMProvider",
    "tokenize",
    "score",
    "DEFAULT_MIN_SCORE",
    "PROVIDER_CONFIDENCE",
]

DEFAULT_MIN_SCORE = 0.30
PROVIDER_CONFIDENCE = 0.80
_AUTHOR_PLACEHOLDER = "{{author_name}}"

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3005]+")
_WORD_RE = re.compile(r"[0-9a-z\u00c0-\u024f]+(?:['\u2019\-_][0-9a-z\u00c0-\u024f]+)*")


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
def tokenize(text) -> list:
    """ token  bigram +  docstring"""
    if text is None:
        return []
    if not isinstance(text, str):
        text = str(text)
    low = text.lower()
    if not low:
        return []
    tokens = []
    for m in _CJK_RE.finditer(low):
        run = m.group(0)
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    tokens.extend(_WORD_RE.findall(low))
    return tokens


def _counts(tokens) -> dict:
    vec = {}
    for t in tokens:
        vec[t] = vec.get(t, 0) + 1
    return vec


def _norm(vec) -> float:
    return math.sqrt(sum(c * c for c in vec.values()))


def score(query_tokens, doc_tokens) -> float:
    """cosine(query, doc) token  [0.0, 1.0]"""
    q = _counts(query_tokens or ())
    d = _counts(doc_tokens or ())
    if not q or not d:
        return 0.0
    dot = 0
    for t, c in q.items():
        dc = d.get(t)
        if dc:
            dot += c * dc
    if dot <= 0:
        return 0.0
    denom = _norm(q) * _norm(d)
    if denom <= 0:
        return 0.0
    s = dot / denom
    return 0.0 if s < 0.0 else (1.0 if s > 1.0 else s)


def _field(ev, name, default=""):
    """ InboundEvent dict raise"""
    if isinstance(ev, dict):
        val = ev.get(name, default)
    else:
        val = getattr(ev, name, default)
    return default if val is None else val


# --------------------------------------------------------------------------- #
# Drafter
# --------------------------------------------------------------------------- #
class Drafter:
    """KB provider 

    kb: list[dict] {'id','question','answer','tags':[],'lang'}
    """

    def __init__(self, kb, provider=None, min_score=DEFAULT_MIN_SCORE):
        self.min_score = float(min_score)
        self.provider = provider
        self.kb = []
        self._index = []  # [(kb_id, token_vec, norm, entry)]
        for entry in (kb or ()):
            if not isinstance(entry, dict):
                continue
            answer = entry.get("answer")
            if not isinstance(answer, str) or answer == "":
                continue
            question = entry.get("question") or ""
            tags = entry.get("tags") or []
            if isinstance(tags, (list, tuple)):
                tag_text = " ".join(str(t) for t in tags)
            else:
                tag_text = str(tags)
            doc_tokens = tokenize(f"{question} {tag_text}")
            vec = _counts(doc_tokens)
            norm = _norm(vec)
            if not vec:
                continue
            kb_id = entry.get("id", "")
            self.kb.append(entry)
            self._index.append((kb_id, vec, norm, entry))

    def best_match(self, text):
        """ (score, entry) (0.0, None)"""
        q = _counts(tokenize(text))
        if not q or not self._index:
            return 0.0, None
        qn = _norm(q)
        if qn <= 0:
            return 0.0, None
        best_s = 0.0
        best_e = None
        for _kb_id, vec, norm, entry in self._index:
            dot = 0
            for t, c in q.items():
                dc = vec.get(t)
                if dc:
                    dot += c * dc
            s = 0.0 if dot <= 0 else dot / (qn * norm)
            if s > best_s:
                best_s = s
                best_e = entry
        return (1.0 if best_s > 1.0 else best_s), best_e

    def _retrieval_draft(self, text, author_name):
        s, entry = self.best_match(text)
        if entry is None or s < self.min_score:
            return contracts.Draft(
                text="",
                confidence=s,
                model="kb:retrieval",
                sources=[],
                escalate=True,
                note="no_match",
            )
        answer = entry.get("answer") or ""
        body = answer.replace(_AUTHOR_PLACEHOLDER, str(author_name))
        return contracts.Draft(
            text=body,
            confidence=min(0.95, 0.55 + s * 0.5),
            model="kb:retrieval",
            sources=[entry.get("id", "")],
            escalate=False,
            note="",
        )

    # -- provider --------------------------------------------------------- #
    def _build_prompt(self, text, author_name, entry):
        kb_answer = (entry or {}).get("answer", "") if entry else ""
        if not kb_answer:
            kb_answer = "()"
        return (
            "\n"
            f"{author_name or ''}\n"
            f"{text}\n"
            f"{kb_answer}\n"
            ""
        )

    def _try_provider(self, text, author_name, entry):
        """ Draft None raise"""
        provider = self.provider
        if provider is None:
            return None
        try:
            prompt = self._build_prompt(text, author_name, entry)
            out = provider.complete(prompt)
        except Exception:
            return None
        if not isinstance(out, str):
            return None
        body = out.strip()
        if not body:
            return None
        name = getattr(provider, "name", None) or "provider"
        sources = []
        if entry is not None:
            sources = [entry.get("id", "")]
        return contracts.Draft(
            text=body.replace(_AUTHOR_PLACEHOLDER, str(author_name)),
            confidence=PROVIDER_CONFIDENCE,
            model="llm:" + str(name),
            sources=sources,
            escalate=False,
            note="",
        )

    def draft(self, ev):
        """InboundEvent -> Draft raiseprovider """
        text = _field(ev, "text", "")
        author_name = _field(ev, "author_name", "")
        if not isinstance(text, str):
            text = str(text)
        _s, entry = self.best_match(text)
        llm = self._try_provider(text, author_name, entry)
        if llm is not None:
            return llm
        return self._retrieval_draft(text, author_name)


# --------------------------------------------------------------------------- #
# EnvLLMProvider
# --------------------------------------------------------------------------- #
class EnvLLMProvider:
    """ OpenAI  /completions  provider

    *  `REPLYBRIDGE_LLM_URL` → 
      RuntimeError('provider not configured') LLM 
    * REPLYBRIDGE_LLM_API_KEYREPLYBRIDGE_LLM_MODELREPLYBRIDGE_LLM_NAME
    * import ****urllib  complete()  lazy import
    *  transport prompt 
    """

    def __init__(self, transport=None, timeout=15.0, name=None, env=None):
        env = os.environ if env is None else env
        url = (env.get("REPLYBRIDGE_LLM_URL") or "").strip()
        if not url:
            raise RuntimeError("provider not configured")
        self.url = url
        self.api_key = (env.get("REPLYBRIDGE_LLM_API_KEY") or "").strip()
        self.model = (env.get("REPLYBRIDGE_LLM_MODEL") or "gpt-4o-mini").strip()
        self.name = name or (env.get("REPLYBRIDGE_LLM_NAME") or "").strip() or "envllm"
        self.timeout = float(timeout)
        self.transport = transport

    @staticmethod
    def _as_text(raw):
        """ transport JSON """
        if isinstance(raw, str):
            body = raw.strip()
            if not body:
                return ""
            try:
                parsed = json.loads(body)
            except (ValueError, TypeError):
                return body
        else:
            parsed = raw
        if isinstance(parsed, dict):
            for key in ("text", "completion", "output", "content", "reply"):
                val = parsed.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
            choices = parsed.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    for key in ("text", "content"):
                        val = first.get(key)
                        if isinstance(val, str) and val.strip():
                            return val.strip()
                    msg = first.get("message")
                    if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                        return msg["content"].strip()
            return ""
        if isinstance(parsed, str):
            return parsed.strip()
        return ""

    def complete(self, prompt):
        """Drafter"""
        if not isinstance(prompt, str):
            prompt = str(prompt)
        if self.transport is not None:
            return self._as_text(self.transport(prompt))
        import urllib.request

        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "max_tokens": 300,
                "temperature": 0.3,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        req = urllib.request.Request(self.url, data=payload, method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
        return self._as_text(raw)
