"""ReplyBridge 

zero-dep Python 3.11 stdlib
"""
from dataclasses import dataclass, field, asdict
from typing import Any, Optional, Protocol

PLATFORMS = ("meta_instagram", "meta_facebook", "line", "tiktok")

KIND_COMMENT = "comment"
KIND_DM = "dm"
KIND_MENTION = "mention"


@dataclass
class InboundEvent:
    """ channels.parse() """
    platform: str
    tenant_id: str
    account_id: str
    kind: str
    message_id: str
    thread_id: str
    parent_id: str
    author_id: str
    author_name: str
    text: str
    created_at: str
    lang: str = ""
    raw: dict = field(default_factory=dict)

    def dedupe_key(self) -> str:
        return f"{self.platform}:{self.account_id}:{self.message_id}"

    def rate_bucket(self) -> str:
        return f"{self.platform}:{self.account_id}:{self.thread_id}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Draft:
    """AI """
    text: str
    confidence: float        # 0.0-1.0
    model: str
    sources: list = field(default_factory=list)
    escalate: bool = False
    note: str = ""


@dataclass
class Decision:
    """server  action """
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
    """channels.build_reply_request() transport """
    platform: str
    method: str              # "POST"
    url: str
    headers: dict
    body: dict
    target: str

    def to_dict(self) -> dict:
        return asdict(self)


class Store(Protocol):
    """ledger.Store """

    def seen(self, key: str) -> bool: ...
    def mark_seen(self, key: str, meta: dict) -> None: ...
    def incr_rate(self, bucket: str, window_s: int) -> int: ...
    def append(self, kind: str, payload: dict) -> dict: ...
    def enqueue(self, event: dict, decision: dict) -> int: ...
    def list_queue(self, limit: int = 50) -> list: ...
    def resolve_queue(self, item_id: int, reply_text: str, by: str) -> dict: ...
    def stats(self) -> dict: ...
    def verify_chain(self) -> tuple: ...  # (ok: bool, broken_at: Optional[int])
