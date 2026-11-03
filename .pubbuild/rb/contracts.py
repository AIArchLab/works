"""ReplyBridge 共用契約。所有模組只依賴本檔，不得自行定義平行型別。

設計原則：zero-dep（只用 Python 3.11 stdlib），可被第三方重跑。
"""
from dataclasses import dataclass, field, asdict
from typing import Any, Optional, Protocol

PLATFORMS = ("meta_instagram", "meta_facebook", "line", "tiktok")

# 事件型別
KIND_COMMENT = "comment"      # 貼文留言（IG/FB/TikTok）
KIND_DM = "dm"                # 私訊（LINE/FB Messenger/IG DM）
KIND_MENTION = "mention"      # 提及（限動/貼文標註）


@dataclass
class InboundEvent:
    """跨平台統一入站事件。平台差異必須在 channels.parse() 內被吸收。"""
    platform: str
    tenant_id: str
    account_id: str          # 平台端帳號/粉專/官方帳號 ID
    kind: str                # KIND_* 之一
    message_id: str          # 平台端唯一訊息/留言 ID
    thread_id: str           # 貼文/media/video/chat ID
    parent_id: str           # 被回覆的留言 ID；頂層留言留空字串
    author_id: str
    author_name: str
    text: str
    created_at: str          # ISO8601 UTC，例 2026-11-03T06:20:00Z
    lang: str = ""
    raw: dict = field(default_factory=dict)

    def dedupe_key(self) -> str:
        return f"{self.platform}:{self.account_id}:{self.message_id}"

    def rate_bucket(self) -> str:
        # 同一對話串的速率限制桶
        return f"{self.platform}:{self.account_id}:{self.thread_id}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Draft:
    """AI 或規則產生的候選回覆，尚未通過政策閘門。"""
    text: str
    confidence: float        # 0.0-1.0
    model: str               # 例 "rule:canned" / "kb:retrieval" / "llm:<name>"
    sources: list = field(default_factory=list)  # KB id 或 URL
    escalate: bool = False   # drafter 自行判定「我不該答」
    note: str = ""


@dataclass
class Decision:
    """政策引擎的最終裁決。server 只依 action 行動。"""
    action: str              # "reply" | "escalate" | "ignore"
    reply_text: str = ""
    policy_hits: list = field(default_factory=list)
    confidence: float = 0.0
    model: str = ""
    reason: str = ""
    escalate_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OutRequest:
    """平台外送請求。channels.build_reply_request() 產生，transport 執行。"""
    platform: str
    method: str              # "POST"
    url: str
    headers: dict
    body: dict
    target: str              # 對誰送（留言ID/使用者ID/thread ID）

    def to_dict(self) -> dict:
        return asdict(self)


class Store(Protocol):
    """持久層介面。ledger.Store 為唯一實作。"""

    def seen(self, key: str) -> bool: ...
    def mark_seen(self, key: str, meta: dict) -> None: ...
    def incr_rate(self, bucket: str, window_s: int) -> int: ...
    def append(self, kind: str, payload: dict) -> dict: ...
    def enqueue(self, event: dict, decision: dict) -> int: ...
    def list_queue(self, limit: int = 50) -> list: ...
    def resolve_queue(self, item_id: int, reply_text: str, by: str) -> dict: ...
    def stats(self) -> dict: ...
    def verify_chain(self) -> tuple: ...  # (ok: bool, broken_at: Optional[int])
