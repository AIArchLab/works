#!/usr/bin/env python3
"""W1 通道層單元測試。可直接執行：python3 tests/test_channels.py

只依賴 stdlib 與 rb.contracts / rb.channels，不連外網、不讀寫 DB。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from rb import channels, contracts  # noqa: E402
from rb.contracts import KIND_COMMENT, KIND_DM, InboundEvent  # noqa: E402

PASSED = 0
FAILED = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"PASS  {name}")
    else:
        FAILED += 1
        FAILURES.append(name)
        print(f"FAIL  {name}" + (f"  -> {detail}" if detail else ""))


def eq(name: str, got, want) -> None:
    check(name, got == want, f"got={got!r} want={want!r}")


# ---------------------------------------------------------------------------
# 簽章工具
# ---------------------------------------------------------------------------
META_SECRET = "meta-app-secret-123"
META_TOKEN = "verify-token-abc"
LINE_SECRET = "line-channel-secret-xyz"
TIKTOK_SECRET = "tiktok-client-secret-789"

SECRETS = {
    "meta_app_secret": META_SECRET,
    "meta_verify_token": META_TOKEN,
    "line_channel_secret": LINE_SECRET,
    "tiktok_client_secret": TIKTOK_SECRET,
}


def meta_header(secret: str, body: bytes) -> dict:
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}


def line_header(secret: str, body: bytes) -> dict:
    sig = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    return {"X-Line-Signature": sig}


def tiktok_header(secret: str, body: bytes, ts: int = 1793686800) -> dict:
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"TikTok-Signature": f"t={ts},s={sig}"}


def _b(obj) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode()


# ---------------------------------------------------------------------------
# 1) verify：4 平台正確簽章
# ---------------------------------------------------------------------------
IG_BODY = _b({"object": "instagram", "entry": []})
FB_BODY = _b({"object": "page", "entry": []})
LINE_BODY = _b({"destination": "Uxxxxxxxx", "events": []})
TT_BODY = _b({"event": "comment.create", "data": {}})

check("verify/IG 正確簽章通過", channels.verify("meta_instagram", meta_header(META_SECRET, IG_BODY), IG_BODY, SECRETS) is True)
check("verify/FB 正確簽章通過", channels.verify("meta_facebook", meta_header(META_SECRET, FB_BODY), FB_BODY, SECRETS) is True)
check("verify/LINE 正確簽章通過", channels.verify("line", line_header(LINE_SECRET, LINE_BODY), LINE_BODY, SECRETS) is True)
check("verify/TikTok t=,s= 正確簽章通過", channels.verify("tiktok", tiktok_header(TIKTOK_SECRET, TT_BODY), TT_BODY, SECRETS) is True)

# 大小寫不敏感標頭
check(
    "verify 標頭名大小寫不敏感",
    channels.verify("meta_instagram", {"x-hub-signature-256": "sha256=" + hmac.new(META_SECRET.encode(), IG_BODY, hashlib.sha256).hexdigest()}, IG_BODY, SECRETS) is True,
)
check(
    "verify LINE 標頭小寫也通",
    channels.verify("line", {"x-line-signature": line_header(LINE_SECRET, LINE_BODY)["X-Line-Signature"]}, LINE_BODY, SECRETS) is True,
)

# TikTok 純 hex 變體
check(
    "verify/TikTok X-Tiktok-Signature 純 hex 通過",
    channels.verify(
        "tiktok",
        {"x-tiktok-signature": hmac.new(TIKTOK_SECRET.encode(), TT_BODY, hashlib.sha256).hexdigest()},
        TT_BODY,
        SECRETS,
    )
    is True,
)
check(
    "verify/TikTok sha256=hex 變體通過",
    channels.verify(
        "tiktok",
        {"X-Tiktok-Signature": "sha256=" + hmac.new(TIKTOK_SECRET.encode(), TT_BODY, hashlib.sha256).hexdigest()},
        TT_BODY,
        SECRETS,
    )
    is True,
)

# ---------------------------------------------------------------------------
# 2) verify：篡改 body / 缺 secret / 缺標頭 / 未知平台 -> False（fail closed）
# ---------------------------------------------------------------------------
for plat, hdr_fn, body, label in [
    ("meta_instagram", lambda b: meta_header(META_SECRET, IG_BODY), IG_BODY, "IG"),
    ("meta_facebook", lambda b: meta_header(META_SECRET, FB_BODY), FB_BODY, "FB"),
    ("line", lambda b: line_header(LINE_SECRET, LINE_BODY), LINE_BODY, "LINE"),
    ("tiktok", lambda b: tiktok_header(TIKTOK_SECRET, TT_BODY), TT_BODY, "TikTok"),
]:
    tampered = body[:-2] + b"9}"
    check(f"verify/{label} 被篡改 body 失敗", channels.verify(plat, hdr_fn(body), tampered, SECRETS) is False)

check("verify/缺 meta_app_secret 失敗", channels.verify("meta_instagram", meta_header(META_SECRET, IG_BODY), IG_BODY, {"meta_verify_token": META_TOKEN}) is False)
check("verify/缺 line_channel_secret 失敗", channels.verify("line", line_header(LINE_SECRET, LINE_BODY), LINE_BODY, {}) is False)
check("verify/缺 tiktok_client_secret 失敗", channels.verify("tiktok", tiktok_header(TIKTOK_SECRET, TT_BODY), TT_BODY, {"meta_app_secret": META_SECRET}) is False)
check("verify/空 secrets 失敗", channels.verify("meta_instagram", meta_header(META_SECRET, IG_BODY), IG_BODY, {}) is False)
check("verify/缺標頭失敗", channels.verify("meta_instagram", {}, IG_BODY, SECRETS) is False)
check("verify/LINE 缺標頭失敗", channels.verify("line", {"X-Other": "x"}, LINE_BODY, SECRETS) is False)
check("verify/TikTok 缺標頭失敗", channels.verify("tiktok", {}, TT_BODY, SECRETS) is False)
check("verify/未知平台失敗", channels.verify("twitter", meta_header(META_SECRET, IG_BODY), IG_BODY, SECRETS) is False)
check("verify/空平台失敗", channels.verify("", {}, b"", SECRETS) is False)
check("verify/壞標頭格式不 raise 且 False", channels.verify("meta_instagram", {"X-Hub-Signature-256": "garbage"}, IG_BODY, SECRETS) is False)
check("verify/錯誤 secret 失敗", channels.verify("line", line_header("wrong", LINE_BODY), LINE_BODY, SECRETS) is False)
check("verify/headers 為 None 不 raise", channels.verify("line", None, LINE_BODY, SECRETS) is False)
check("verify/raw_body 為 None 不 raise", channels.verify("line", line_header(LINE_SECRET, LINE_BODY), None, SECRETS) is False)
check("verify/LINE base64 但錯誤簽章失敗", channels.verify("line", {"X-Line-Signature": base64.b64encode(b"\x00" * 32).decode()}, LINE_BODY, SECRETS) is False)

# ---------------------------------------------------------------------------
# 3) verify_challenge
# ---------------------------------------------------------------------------
Q_OK = {"hub.mode": "subscribe", "hub.verify_token": META_TOKEN, "hub.challenge": "1158201444"}
eq("verify_challenge 正確 token 回 challenge", channels.verify_challenge("meta_instagram", Q_OK, SECRETS), "1158201444")
eq("verify_challenge FB 也支援", channels.verify_challenge("meta_facebook", Q_OK, SECRETS), "1158201444")
eq("verify_challenge 錯 token 回 None", channels.verify_challenge("meta_instagram", {"hub.mode": "subscribe", "hub.verify_token": "bad", "hub.challenge": "1"}, SECRETS), None)
eq("verify_challenge mode 非 subscribe 回 None", channels.verify_challenge("meta_instagram", {"hub.mode": "unsubscribe", "hub.verify_token": META_TOKEN, "hub.challenge": "1"}, SECRETS), None)
eq("verify_challenge LINE 回 None", channels.verify_challenge("line", Q_OK, SECRETS), None)
eq("verify_challenge 缺 challenge 回 None", channels.verify_challenge("meta_instagram", {"hub.mode": "subscribe", "hub.verify_token": META_TOKEN}, SECRETS), None)
eq("verify_challenge 兩參數版（configure_secrets）", (channels.configure_secrets(SECRETS), channels.verify_challenge("meta_instagram", Q_OK))[1], "1158201444")

# ---------------------------------------------------------------------------
# 4) parse：meta_instagram 留言
# ---------------------------------------------------------------------------
IG_PAYLOAD = {
    "object": "instagram",
    "entry": [
        {
            "id": "17841400000000000",
            "time": 1793686800000,
            "changes": [
                {
                    "field": "comments",
                    "value": {
                        "id": "17858893269123456",
                        "text": "有現貨嗎？",
                        "from": {"id": "9988776655", "username": "amy.chen"},
                        "media": {"id": "17900000000000001", "media_product_type": "FEED"},
                        "created_time": "2026-11-03T06:20:00+0000",
                    },
                }
            ],
        }
    ],
}

ig_events = channels.parse("meta_instagram", IG_PAYLOAD, "tenant-A")
check("parse/IG 產生 1 個事件", len(ig_events) == 1, f"len={len(ig_events)}")
if ig_events:
    e = ig_events[0]
    eq("parse/IG platform", e.platform, "meta_instagram")
    eq("parse/IG tenant_id", e.tenant_id, "tenant-A")
    eq("parse/IG account_id", e.account_id, "17841400000000000")
    eq("parse/IG kind", e.kind, KIND_COMMENT)
    eq("parse/IG message_id", e.message_id, "17858893269123456")
    eq("parse/IG thread_id(media)", e.thread_id, "17900000000000001")
    eq("parse/IG parent_id 空", e.parent_id, "")
    eq("parse/IG author_id", e.author_id, "9988776655")
    eq("parse/IG author_name", e.author_name, "amy.chen")
    eq("parse/IG text", e.text, "有現貨嗎？")
    eq("parse/IG created_at ISO UTC", e.created_at, "2026-11-03T06:20:00Z")
    eq("parse/IG dedupe_key", e.dedupe_key(), "meta_instagram:17841400000000000:17858893269123456")
    check("parse/IG raw 保留原始 value", isinstance(e.raw.get("raw"), dict))

# ---------------------------------------------------------------------------
# 5) parse：meta_facebook 留言 + Messenger
# ---------------------------------------------------------------------------
FB_PAYLOAD = {
    "object": "page",
    "entry": [
        {
            "id": "1122334455",
            "time": 1793686800000,
            "changes": [
                {
                    "field": "feed",
                    "value": {
                        "item": "comment",
                        "verb": "add",
                        "comment_id": "1122334455_999888777",
                        "post_id": "1122334455_111222333",
                        "parent_id": "",
                        "from": {"id": "5566778899", "name": "Wang Xiaoming"},
                        "message": "多少錢？",
                        "created_time": "2026-11-03T06:21:30+0000",
                    },
                }
            ],
        }
    ],
}
fb_events = channels.parse("meta_facebook", FB_PAYLOAD, "tenant-A")
check("parse/FB 產生 1 個事件", len(fb_events) == 1, f"len={len(fb_events)}")
if fb_events:
    e = fb_events[0]
    eq("parse/FB kind", e.kind, KIND_COMMENT)
    eq("parse/FB message_id=comment_id", e.message_id, "1122334455_999888777")
    eq("parse/FB thread_id=post_id", e.thread_id, "1122334455_111222333")
    eq("parse/FB author_name", e.author_name, "Wang Xiaoming")
    eq("parse/FB text", e.text, "多少錢？")
    eq("parse/FB created_at", e.created_at, "2026-11-03T06:21:30Z")

FB_DM_PAYLOAD = {
    "object": "page",
    "entry": [
        {
            "id": "1122334455",
            "time": 1793686800000,
            "messaging": [
                {
                    "sender": {"id": "5566778899"},
                    "recipient": {"id": "1122334455"},
                    "timestamp": 1793686890123,
                    "message": {"mid": "m_ABC123", "text": "私訊問一下運費"},
                }
            ],
        }
    ],
}
fb_dm = channels.parse("meta_facebook", FB_DM_PAYLOAD, "tenant-A")
check("parse/FB 私訊產生 1 個事件", len(fb_dm) == 1, f"len={len(fb_dm)}")
if fb_dm:
    e = fb_dm[0]
    eq("parse/FB 私訊 kind=dm", e.kind, KIND_DM)
    eq("parse/FB 私訊 message_id=mid", e.message_id, "m_ABC123")
    eq("parse/FB 私訊 thread_id=對方ID", e.thread_id, "5566778899")
    eq("parse/FB 私訊 author_id", e.author_id, "5566778899")
    eq("parse/FB 私訊 created_at(ms→ISO)", e.created_at, "2026-11-03T06:21:30Z")
    eq("parse/FB 私訊 raw.peer_id", e.raw.get("peer_id"), "5566778899")

# ---------------------------------------------------------------------------
# 6) parse：LINE
# ---------------------------------------------------------------------------
LINE_PAYLOAD = {
    "destination": "U4af4980629",
    "events": [
        {
            "type": "message",
            "message": {"type": "text", "id": "325708", "text": "我要退貨"},
            "timestamp": 1793686950000,
            "source": {"type": "user", "userId": "Udeadbeefdeadbeef"},
            "replyToken": "nHuyWiB7yP5Zw52FIkcQobQuGDXCTA",
            "mode": "active",
        }
    ],
}
line_events = channels.parse("line", LINE_PAYLOAD, "tenant-A")
check("parse/LINE 產生 1 個事件", len(line_events) == 1, f"len={len(line_events)}")
if line_events:
    e = line_events[0]
    eq("parse/LINE platform", e.platform, "line")
    eq("parse/LINE kind=dm", e.kind, KIND_DM)
    eq("parse/LINE account_id=destination", e.account_id, "U4af4980629")
    eq("parse/LINE message_id", e.message_id, "325708")
    eq("parse/LINE author_id=userId", e.author_id, "Udeadbeefdeadbeef")
    eq("parse/LINE thread_id", e.thread_id, "Udeadbeefdeadbeef")
    eq("parse/LINE text", e.text, "我要退貨")
    eq("parse/LINE created_at", e.created_at, "2026-11-03T06:22:30Z")
    eq("parse/LINE reply_token 存入 raw", e.raw.get("reply_token"), "nHuyWiB7yP5Zw52FIkcQobQuGDXCTA")

# ---------------------------------------------------------------------------
# 7) parse：TikTok
# ---------------------------------------------------------------------------
TT_PAYLOAD = {
    "event": "comment.create",
    "business_id": "7000000000000000001",
    "data": {
        "comment_id": "7100000000000000001",
        "video_id": "7200000000000000001",
        "text": "出貨到香港嗎",
        "user_id": "6800000000000000001",
        "username": "hk_buyer",
        "create_time": 1793685800,
    },
}
tt_events = channels.parse("tiktok", TT_PAYLOAD, "tenant-A")
check("parse/TikTok 產生 1 個事件", len(tt_events) == 1, f"len={len(tt_events)}")
if tt_events:
    e = tt_events[0]
    eq("parse/TikTok platform", e.platform, "tiktok")
    eq("parse/TikTok kind=comment", e.kind, KIND_COMMENT)
    eq("parse/TikTok account_id=business_id", e.account_id, "7000000000000000001")
    eq("parse/TikTok message_id=comment_id", e.message_id, "7100000000000000001")
    eq("parse/TikTok thread_id=video_id", e.thread_id, "7200000000000000001")
    eq("parse/TikTok author_id=user_id", e.author_id, "6800000000000000001")
    eq("parse/TikTok author_name=username", e.author_name, "hk_buyer")
    eq("parse/TikTok text", e.text, "出貨到香港嗎")
    eq("parse/TikTok created_at(s→ISO)", e.created_at, "2026-11-03T06:03:20Z")

TT_REPLY = {
    "event": "comment.reply",
    "business_id": "7000000000000000001",
    "data": {
        "comment_id": "7100000000000000002",
        "video_id": "7200000000000000001",
        "parent_comment_id": "7100000000000000001",
        "text": "+1",
        "user_id": "6800000000000000002",
        "create_time": 1793686890,
    },
}
ttr = channels.parse("tiktok", TT_REPLY, "tenant-A")
check("parse/TikTok comment.reply 也解析", len(ttr) == 1)
if ttr:
    eq("parse/TikTok reply parent_id", ttr[0].parent_id, "7100000000000000001")

# ---------------------------------------------------------------------------
# 8) 自我留言過濾（不可回覆自己）
# ---------------------------------------------------------------------------
SELF_IG = {
    "object": "instagram",
    "entry": [
        {
            "id": "17841400000000000",
            "changes": [
                {
                    "field": "comments",
                    "value": {
                        "id": "c_self_1",
                        "text": "感謝詢問，已私訊您",
                        "from": {"id": "17841400000000000", "username": "our_brand"},
                        "media": {"id": "17900000000000001"},
                        "created_time": "2026-11-03T06:25:00+0000",
                    },
                }
            ],
        }
    ],
}
eq("filter/IG 自己帳號的留言被濾掉", channels.parse("meta_instagram", SELF_IG, "tenant-A"), [])

ECHO_IG = {
    "object": "instagram",
    "entry": [
        {
            "id": "17841400000000000",
            "changes": [
                {
                    "field": "comments",
                    "value": {
                        "id": "c_echo",
                        "text": "自動回覆內容",
                        "is_echo": True,
                        "from": {"id": "9988776655", "username": "amy.chen"},
                        "media": {"id": "17900000000000001"},
                    },
                }
            ],
        }
    ],
}
eq("filter/IG is_echo 被濾掉", channels.parse("meta_instagram", ECHO_IG, "tenant-A"), [])

SELF_FB = {
    "object": "page",
    "entry": [
        {
            "id": "1122334455",
            "changes": [
                {
                    "field": "feed",
                    "value": {
                        "item": "comment",
                        "comment_id": "1122334455_1",
                        "post_id": "1122334455_2",
                        "from": {"id": "1122334455", "name": "Our Page"},
                        "message": "謝謝",
                    },
                }
            ],
        }
    ],
}
eq("filter/FB 粉專自己的留言被濾掉", channels.parse("meta_facebook", SELF_FB, "tenant-A"), [])

FB_ECHO_DM = {
    "object": "page",
    "entry": [
        {
            "id": "1122334455",
            "messaging": [
                {
                    "sender": {"id": "1122334455"},
                    "recipient": {"id": "5566778899"},
                    "message": {"mid": "m_1", "text": "我們已收到", "is_echo": True},
                }
            ],
        }
    ],
}
eq("filter/FB 私訊 is_echo 被濾掉", channels.parse("meta_facebook", FB_ECHO_DM, "tenant-A"), [])

TT_SELF = {
    "event": "comment.create",
    "business_id": "7000000000000000001",
    "data": {
        "comment_id": "7100000000000000009",
        "video_id": "7200000000000000001",
        "text": "老闆自己回",
        "user_id": "7000000000000000001",
        "create_time": 1793685800,
    },
}
eq("filter/TikTok 自己留言被濾掉", channels.parse("tiktok", TT_SELF, "tenant-A"), [])

# ---------------------------------------------------------------------------
# 9) 非文字訊息 / 不支援形狀
# ---------------------------------------------------------------------------
LINE_STICKER = {
    "destination": "U4af4980629",
    "events": [
        {"type": "message", "message": {"type": "sticker", "id": "1", "packageId": "1", "stickerId": "1"}, "timestamp": 1793686950000, "source": {"type": "user", "userId": "U1"}, "replyToken": "rt1"},
        {"type": "follow", "timestamp": 1793686950000, "source": {"type": "user", "userId": "U2"}, "replyToken": "rt2"},
        {"type": "message", "message": {"type": "image", "id": "2"}, "timestamp": 1793686950000, "source": {"type": "user", "userId": "U3"}, "replyToken": "rt3"},
        {"type": "message", "message": {"type": "text", "id": "3", "text": "文字才算"}, "timestamp": 1793686950000, "source": {"type": "user", "userId": "U4"}, "replyToken": "rt4"},
    ],
}
line_mixed = channels.parse("line", LINE_STICKER, "tenant-A")
eq("filter/LINE 非文字與非 message 事件被跳過（只剩 1 文字）", len(line_mixed), 1)
if line_mixed:
    eq("filter/LINE 剩下的是文字事件", line_mixed[0].text, "文字才算")

IG_NONCOMMENT = {
    "object": "instagram",
    "entry": [{"id": "1", "changes": [{"field": "message_reactions", "value": {"id": "x"}}]}],
}
eq("filter/IG 非 comments field 被跳過", channels.parse("meta_instagram", IG_NONCOMMENT, "tenant-A"), [])
eq("filter/FB item=post 被跳過", channels.parse("meta_facebook", {"object": "page", "entry": [{"id": "1", "changes": [{"field": "feed", "value": {"item": "post", "post_id": "1", "message": "hi"}}]}]}, "t"), [])
eq("filter/未知平台回空 list", channels.parse("twitter", {"object": "x"}, "t"), [])
eq("filter/payload 非 dict 不 raise", channels.parse("line", None, "t"), [])
eq("filter/payload 空 dict 不 raise", channels.parse("tiktok", {}, "t"), [])
eq("filter/entry 是字串不 raise", channels.parse("line", {"events": "oops"}, "t"), [])
eq("filter/LINE 缺 text 被跳過", channels.parse("line", {"events": [{"type": "message", "message": {"type": "text", "id": "1"}, "source": {"userId": "U1"}}]}, "t"), [])

# ---------------------------------------------------------------------------
# 10) build_reply_request
# ---------------------------------------------------------------------------
EV_IG = channels.parse("meta_instagram", IG_PAYLOAD, "tenant-A")[0]
EV_FB = channels.parse("meta_facebook", FB_PAYLOAD, "tenant-A")[0]
EV_FB_DM = channels.parse("meta_facebook", FB_DM_PAYLOAD, "tenant-A")[0]
EV_LINE = channels.parse("line", LINE_PAYLOAD, "tenant-A")[0]
EV_TT = channels.parse("tiktok", TT_PAYLOAD, "tenant-A")[0]

META_CREDS = {"meta_access_token": "EAAG-fake-token"}
LINE_CREDS = {"line_channel_access_token": "line-fake-token"}
TT_CREDS = {"tiktok_access_token": "tt-fake-token", "tiktok_business_id": "7000000000000000001"}

r = channels.build_reply_request("meta_instagram", EV_IG, "有的，現貨充足", META_CREDS)
eq("build/IG 留言 method", r.method, "POST")
eq("build/IG 留言 url", r.url, "https://graph.facebook.com/v26.0/17858893269123456/replies")
eq("build/IG 留言 body", r.body, {"message": "有的，現貨充足"})
eq("build/IG 留言 target", r.target, "17858893269123456")
eq("build/IG 留言 Authorization", r.headers.get("Authorization"), "Bearer EAAG-fake-token")
check("build/IG 留言 url 在 ENDPOINTS 內", channels.ENDPOINTS["meta_instagram"]["comment_reply"].format(message_id=EV_IG.message_id) == r.url)

r = channels.build_reply_request("meta_facebook", EV_FB, "399 元", META_CREDS)
eq("build/FB 留言 method", r.method, "POST")
eq("build/FB 留言 url", r.url, "https://graph.facebook.com/v26.0/1122334455_999888777/comments")
eq("build/FB 留言 body", r.body, {"message": "399 元"})

r = channels.build_reply_request("meta_facebook", EV_FB_DM, "運費 60 元", META_CREDS)
eq("build/FB 私訊 method", r.method, "POST")
eq("build/FB 私訊 url", r.url, "https://graph.facebook.com/v26.0/5566778899/messages")
eq("build/FB 私訊 body.recipient", r.body.get("recipient"), {"id": "5566778899"})
eq("build/FB 私訊 body.message.text", r.body["message"]["text"], "運費 60 元")

r = channels.build_reply_request("line", EV_LINE, "請提供訂單編號", LINE_CREDS)
eq("build/LINE method", r.method, "POST")
eq("build/LINE url", r.url, "https://api.line.me/v2/bot/message/reply")
eq("build/LINE Authorization", r.headers.get("Authorization"), "Bearer line-fake-token")
eq("build/LINE replyToken 有帶入", r.body.get("replyToken"), "nHuyWiB7yP5Zw52FIkcQobQuGDXCTA")
eq("build/LINE messages", r.body.get("messages"), [{"type": "text", "text": "請提供訂單編號"}])

r = channels.build_reply_request("tiktok", EV_TT, "有，可寄香港", TT_CREDS)
eq("build/TikTok method", r.method, "POST")
eq("build/TikTok url", r.url, "https://business-api.tiktok.com/open_api/v1.3/business/comment/reply/")
eq("build/TikTok Access-Token", r.headers.get("Access-Token"), "tt-fake-token")
eq("build/TikTok body.comment_id", r.body.get("comment_id"), "7100000000000000001")
eq("build/TikTok body.video_id", r.body.get("video_id"), "7200000000000000001")
eq("build/TikTok body.text", r.body.get("text"), "有，可寄香港")

# OutRequest 契約形狀
check("build/回傳 OutRequest", all(isinstance(x, contracts.OutRequest) for x in [r]))
_fields = set(r.to_dict()) if hasattr(r, "to_dict") else set(vars(r))
check("build/OutRequest 六欄齊備", _fields == {"platform", "method", "url", "headers", "body", "target"}, f"fields={sorted(_fields)}")

# 所有 ENDPOINTS 都必須有 URL 且四個平台都存在
check("build/ENDPOINTS 涵蓋 4 平台", set(channels.ENDPOINTS) == set(contracts.PLATFORMS))
check("build/ENDPOINTS 全部 https", all(v.startswith("https://") for d in channels.ENDPOINTS.values() for v in d.values()))

# LINE 人工核准走 push（replyToken 約 1 分鐘失效）
try:
    _ev_push = channels.parse("line", {"destination": "U1", "events": [{
        "type": "message", "replyToken": "rt_old", "timestamp": 1793687375000,
        "source": {"userId": "Uline9", "type": "user"},
        "message": {"id": "m_push", "type": "text", "text": "hi"}}]}, "t")[0]
    _r_push = channels.build_reply_request("line", _ev_push, "真人回覆",
                                           {"line_channel_access_token": "tok", "line_delivery": "push"})
    check("build/LINE 人工核准走 push 端點", _r_push.url == "https://api.line.me/v2/bot/message/push", _r_push.url)
    check("build/LINE push 帶 to", _r_push.body.get("to") == "Uline9", _r_push.body)
    check("build/LINE push 不帶 replyToken", "replyToken" not in _r_push.body, _r_push.body)
except Exception as _e:
    check("build/LINE push 分支", False, repr(_e))

check("端點可信度表涵蓋四平台", set(channels.ENDPOINT_STATUS) == set(contracts.PLATFORMS), channels.ENDPOINT_STATUS)
check("TikTok 端點標為未查證", channels.ENDPOINT_STATUS.get("tiktok") == "unverified", channels.ENDPOINT_STATUS)

# 未知平台 raise（呼叫端必須處理，不得靜默送錯）
try:
    channels.build_reply_request("twitter", EV_IG, "x", {})
    check("build/未知平台 raise ValueError", False, "no raise")
except ValueError:
    check("build/未知平台 raise ValueError", True)

print("-" * 60)
print(f"TOTAL: {PASSED + FAILED}  PASS: {PASSED}  FAIL: {FAILED}")
if FAILED:
    print("FAILED CASES: " + ", ".join(FAILURES))
    sys.exit(1)
print("ALL GREEN")
sys.exit(0)

