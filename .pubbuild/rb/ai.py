"""ReplyBridge 草稿層（W3）：KB 檢索式草稿 + 可插拔 LLM provider。

責任邊界（見 BOUNDARIES.md）：
  * 只產生 Draft 候選，不送訊息、不判斷平台政策、不寫帳本、不碰網路（除非上層
    明確注入／設定 provider）。
  * 只依賴 Python 3.11 stdlib：re / math / json / os，加上已凍結的 contracts。
  * import 時零副作用、零連線；EnvLLMProvider 在未被設定時於建構子立即失敗，
    讓上層（server / 運維）明確知道「LLM 未配置」，而不是安靜地少了一半功能。

檢索與計分公式（本模組的唯一真相）
--------------------------------
1) 斷詞 tokenize(text)（先轉小寫）
   * 中文（CJK 表意文字，涵蓋 U+3400-U+4DBF, U+4E00-U+9FFF, U+F900-U+FAFF,
     U+3005）：對每個連續中文片段取「字元 bigram」；長度為 1 的片段退化為該單字
     本身（只發一個 token，避免整段被丟棄）。
       例：「我要怎麼退款」→ {我要, 要怎, 怎麼, 麼退, 退款}
   * 英文（含數字與拉丁延伸字元）：以空白切詞後轉小寫，並去掉詞邊標點
     （實作為取「字母數字連續段」，詞內 ' - _ 保留，例如 "don't"、"e-mail"）。
       例：「How do I reset my password?」→ {how, do, i, reset, my, password}
   * 一段文字可同時產出中文 bigram 與英文詞（混合語言查詢不會互相干擾）。
2) 計分 score(query, doc)：對兩個 token 多重集合做 **cosine 相似度**
       score = Σ_t c_q(t)·c_d(t) / ( ‖c_q‖₂ · ‖c_d‖₂ )
   其中 c_x(t) 為 token t 在 x 中的出現次數，‖c_x‖₂ = sqrt(Σ_t c_x(t)²)。
   分子為 0 或任一向量為空 → score = 0.0，因此 score ∈ [0.0, 1.0]。
   選 cosine 而非 Jaccard 的理由：cosine 天然對長度歸一，短問句不會因為 KB
   問句較長而被系統性懲罰（Jaccard 會）。
3) 索引欄位：KB 每筆索引 `question + " " + " ".join(tags)`。answer 不進索引
   （答案裡的行銷詞會造成假命中）；`lang` 只作紀錄，不做硬性過濾——中英 token
   空間本來就不重疊，跨語言假命中的分數是 0。
4) 決策：只取「分數最高」且 ≥ min_score 的一筆（同分取 KB 中較前面者，順序穩定）。
   * 命中：Draft(text=answer 內 {{author_name}} 換成 ev.author_name,
                confidence=min(0.95, 0.55 + score*0.5),
                model="kb:retrieval", sources=[kb_id], escalate=False)
   * 未命中（含 KB 為空）：Draft(text="", confidence=score, model="kb:retrieval",
                escalate=True, note="no_match")
5) provider：物件需有 complete(prompt: str) -> str。若存在則「先」試 provider，
   prompt 內含 ev.text 與 KB 最佳答案。成功（回傳非空字串）→
   model="llm:"+getattr(provider,"name","provider")、confidence=0.80。
   provider 拋任何例外或回空字串 → 安靜退回檢索結果（不 raise、不偽造信心，
   退回時 confidence 一律用檢索分數）。
"""

import json
import math
import os
import re

try:  # 以套件方式 import（rb.ai）與以模組方式 import（sys.path 指向 rb/）都要能用
    from . import contracts
except ImportError:  # pragma: no cover - 直接執行/測試時的退路
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

# 中文片段：CJK Ext-A、CJK 基本區、相容表意文字、々
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3005]+")
# 英文/數字詞：以空白切詞後取字母數字段（詞邊標點自然被去掉，詞內 ' - _ 保留）
_WORD_RE = re.compile(r"[0-9a-z\u00c0-\u024f]+(?:['\u2019\-_][0-9a-z\u00c0-\u024f]+)*")


# --------------------------------------------------------------------------- #
# 斷詞與計分（純函式，供 Drafter 與測試共用）
# --------------------------------------------------------------------------- #
def tokenize(text) -> list:
    """把一段文字轉成 token 清單（中文 bigram + 英文小寫詞）。公式見模組 docstring。"""
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
    """cosine(query, doc)，輸入為 token 清單，回傳 [0.0, 1.0]。"""
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
    # 浮點自我保護：cosine 理論上 ≤ 1，這裡夾住避免 1.0000000000000002
    return 0.0 if s < 0.0 else (1.0 if s > 1.0 else s)


def _field(ev, name, default=""):
    """從 InboundEvent（或 dict）安全取值，永不 raise。"""
    if isinstance(ev, dict):
        val = ev.get(name, default)
    else:
        val = getattr(ev, name, default)
    return default if val is None else val


# --------------------------------------------------------------------------- #
# Drafter
# --------------------------------------------------------------------------- #
class Drafter:
    """KB 檢索式草稿器；provider 可選，失敗時必須能安靜退回首選檢索。

    kb: list[dict]，每筆 {'id','question','answer','tags':[],'lang'}。
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
                continue  # 沒有答案的條目不可能產生草稿，索引時就排除
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
                continue  # 空問句/純標點的條目無法比對
            kb_id = entry.get("id", "")
            self.kb.append(entry)
            self._index.append((kb_id, vec, norm, entry))

    # -- 檢索 ------------------------------------------------------------- #
    def best_match(self, text):
        """回傳 (score, entry)；無可用條目時回 (0.0, None)。同分取索引較前者。"""
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
            kb_answer = "(無相關知識庫條目，請依品牌一般語氣回覆或保守回應)"
        return (
            "你是品牌社群客服助理。請用親切、簡短（兩句內）的語氣回覆以下使用者訊息。\n"
            f"使用者名稱：{author_name or '客人'}\n"
            f"使用者訊息：{text}\n"
            f"知識庫參考答案（可能不相關，若不相關請忽略）：{kb_answer}\n"
            "回覆："
        )

    def _try_provider(self, text, author_name, entry):
        """成功回傳 Draft；任何失敗（例外／空字串／非字串）回 None，永不 raise。"""
        provider = self.provider
        if provider is None:
            return None
        try:
            prompt = self._build_prompt(text, author_name, entry)
            out = provider.complete(prompt)
        except Exception:  # noqa: BLE001 - 合約要求：provider 任何例外都安靜退回
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

    # -- 對外唯一入口 ------------------------------------------------------ #
    def draft(self, ev):
        """InboundEvent -> Draft。永不 raise；provider 失敗時退回檢索結果。"""
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
    """以環境變數啟用的 OpenAI 相容 /completions 風格 provider。

    * 建構子讀 `REPLYBRIDGE_LLM_URL`（必填）；未設 → 立刻
      RuntimeError('provider not configured')，讓上層知道 LLM 沒配置。
    * 選填：REPLYBRIDGE_LLM_API_KEY、REPLYBRIDGE_LLM_MODEL、REPLYBRIDGE_LLM_NAME。
    * import 本模組**不會**連網；urllib 在 complete() 內才 lazy import。
    * 測試請注入 transport（可呼叫物件，收 prompt 回字串），即可完全離線。
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

    # -- 內部 -------------------------------------------------------------- #
    @staticmethod
    def _as_text(raw):
        """把 transport 回應（JSON 字串或已解析物件）抽成純文字；抽不到就原樣回。"""
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

    # -- 對外 -------------------------------------------------------------- #
    def complete(self, prompt):
        """回傳字串；失敗由呼叫端（Drafter）捕捉。此處不吞例外。"""
        if not isinstance(prompt, str):
            prompt = str(prompt)
        if self.transport is not None:
            return self._as_text(self.transport(prompt))
        # lazy import：模組 import 階段絕不觸網
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
