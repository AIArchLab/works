"""ReplyBridge 4  payload 

 BOUNDARIES.md/
    verify(platform, headers, raw_body: bytes, secrets: dict) -> bool
    verify_challenge(platform, query: dict, secrets: dict | None = None) -> str | None
    parse(platform, payload: dict, tenant_id: str) -> list[InboundEvent]
    build_reply_request(platform, ev, text, creds: dict) -> OutRequest


-  Python 3.11 stdlibhmac / hashlib / base64 / json / urllib.parse / datetime
  jsonurllib.parse 
- fail closedverify()  Falseparse()  []
   raisewebhook  payload 500
-  parse()  build_reply_request()  InboundEvent
-  endpoint /  `

secrets 
    meta_instagram / meta_facebook : meta_app_secret, meta_verify_token, meta_access_token
    line                           : line_channel_secret, line_channel_access_token
    tiktok                         : tiktok_client_secret, tiktok_access_token, tiktok_business_id

creds secrets 
    meta_* : meta_access_token page_access_token / access_token
    line   : line_channel_access_token line_access_token
    tiktok : tiktok_access_token, tiktok_business_id
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone

try:
    from . import contracts
    from .contracts import (
        KIND_COMMENT,
        KIND_DM,
        PLATFORMS,
        InboundEvent,
        OutRequest,
    )
except ImportError:
    import contracts  # type: ignore
    from contracts import (  # type: ignore
        KIND_COMMENT,
        KIND_DM,
        PLATFORMS,
        InboundEvent,
        OutRequest,
    )

__all__ = [
    "ENDPOINTS",
    "ENDPOINT_STATUS",
    "PLATFORMS",
    "verify",
    "verify_challenge",
    "parse",
    "build_reply_request",
    "configure_secrets",
]

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
GRAPH = "https://graph.facebook.com/v26.0"

ENDPOINTS: dict[str, dict[str, str]] = {
    "meta_instagram": {
        "comment_reply": GRAPH + "/{message_id}/replies",
        "dm": GRAPH + "/me/messages",  # VERIFY
    },
    "meta_facebook": {
        "comment_reply": GRAPH + "/{message_id}/comments",
        "dm": GRAPH + "/{thread_id}/messages",  # VERIFY
    },
    "line": {
        "reply": "https://api.line.me/v2/bot/message/reply",
        "push": "https://api.line.me/v2/bot/message/push",
    },
    "tiktok": {
        "comment_reply": "https://business-api.tiktok.com/open_api/v1.3/business/comment/reply/",  # VERIFY
    },
}

_DEFAULT_SECRETS: dict = {}


def configure_secrets(secrets: dict) -> None:
    """ webhook secrets verify_challenge(platform, query) """
    global _DEFAULT_SECRETS
    _DEFAULT_SECRETS = dict(secrets) if isinstance(secrets, dict) else {}


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
def _s(v) -> str:
    """ str None -> """""
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", "ignore").strip()
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _list(v) -> list:
    return v if isinstance(v, list) else []


def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _to_bytes(raw) -> bytes:
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, bytearray):
        return bytes(raw)
    if isinstance(raw, str):
        return raw.encode("utf-8")
    return b""


def _header(headers, name: str):
    """ dict / email.message  .items()"""
    if not headers:
        return None
    lname = name.lower()
    try:
        items = headers.items()
    except Exception:
        return None
    for k, v in items:
        if isinstance(k, bytes):
            k = k.decode("latin-1", "ignore")
        if isinstance(k, str) and k.lower() == lname:
            if isinstance(v, (list, tuple)):
                v = v[0] if v else None
            if isinstance(v, bytes):
                return v.decode("utf-8", "ignore").strip()
            return None if v is None else str(v).strip()
    return None


def _to_iso(value) -> str:
    """ -> 'YYYY-MM-DDTHH:MM:SSZ'UTC """""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        num = float(value)
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return ""
        if s.isdigit():
            num = float(s)
        else:
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                return ""
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        return ""
    if num <= 0:
        return ""
    if num > 1e11:
        num = num / 1000.0
    try:
        dt = datetime.fromtimestamp(num, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _hmac_hex(key: str, body: bytes) -> str:
    return hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _eq(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a, b)
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
ENDPOINT_STATUS: dict[str, str] = {
    "meta_instagram": "verified",
    "meta_facebook": "verified",
    "line": "verified",
    "tiktok": "unverified",
}


def verify(platform: str, headers, raw_body: bytes, secrets: dict) -> bool:
    """ webhook fail closed /  secret /  /  -> False"""
    try:
        if platform not in PLATFORMS:
            return False
        if not isinstance(secrets, dict) or not secrets:
            return False
        if raw_body is None:
            return False
        body = _to_bytes(raw_body)

        if platform in ("meta_instagram", "meta_facebook"):
            secret = secrets.get("meta_app_secret")
            if not secret:
                return False
            got = _header(headers, "X-Hub-Signature-256")
            if not got:
                return False
            alg, sep, digest = got.partition("=")
            if not sep or alg.strip().lower() != "sha256":
                return False
            return _eq(_hmac_hex(_s(secret), body), digest.strip().lower())

        if platform == "line":
            secret = secrets.get("line_channel_secret")
            if not secret:
                return False
            got = _header(headers, "X-Line-Signature")
            if not got:
                return False
            expected = base64.b64encode(
                hmac.new(_s(secret).encode("utf-8"), body, hashlib.sha256).digest()
            ).decode("ascii")
            return _eq(expected, got.strip())

        # tiktok
        secret = secrets.get("tiktok_client_secret")
        if not secret:
            return False
        expected = _hmac_hex(_s(secret), body)

        raw_sig = _header(headers, "TikTok-Signature")
        if raw_sig:
            parts = {}
            for chunk in raw_sig.split(","):
                k, sep, v = chunk.partition("=")
                if sep:
                    parts[k.strip().lower()] = v.strip()
            s_val = parts.get("s") or parts.get("signature")
            if not s_val:
                return False
            return _eq(expected, s_val.lower())

        alt = _header(headers, "X-Tiktok-Signature")
        if alt:
            val = alt.strip()
            if "=" in val and not all(c in "0123456789abcdefABCDEF" for c in val):
                val = val.rsplit("=", 1)[-1].strip()
            return _eq(expected, val.lower())

        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
def verify_challenge(platform: str, query: dict, secrets: dict | None = None):
    """Meta GET hub.mode=subscribe  verify_token  ->  hub.challenge

     None  403
    secrets  configure_secrets() 
     query  HTTP  'meta_verify_token'
    """
    try:
        if platform not in ("meta_instagram", "meta_facebook"):
            return None
        if not isinstance(query, dict):
            return None

        q = {}
        for k, v in query.items():
            if isinstance(v, (list, tuple)):
                v = v[0] if v else ""
            q[str(k).strip().lower()] = v

        def get(*names):
            for n in names:
                if n in q and q[n] is not None:
                    return q[n]
            return None

        mode = _s(get("hub.mode", "hub_mode"))
        token = _s(get("hub.verify_token", "hub_verify_token"))
        challenge = get("hub.challenge", "hub_challenge")

        if mode != "subscribe" or not token or challenge is None:
            return None

        sec = secrets if isinstance(secrets, dict) else _DEFAULT_SECRETS
        expected = _s(sec.get("meta_verify_token") if sec else "") or _s(
            get("meta_verify_token")
        )
        if not expected:
            return None
        if not _eq(expected, token):
            return None
        return _s(challenge)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
def _mk(
    *,
    platform: str,
    tenant_id: str,
    account_id: str,
    kind: str,
    message_id: str,
    thread_id: str,
    parent_id: str,
    author_id: str,
    author_name: str,
    text: str,
    created_at,
    raw: dict,
) -> InboundEvent | None:
    text = _s(text)
    if not message_id or not text:
        return None
    return InboundEvent(
        platform=platform,
        tenant_id=_s(tenant_id),
        account_id=_s(account_id),
        kind=kind,
        message_id=_s(message_id),
        thread_id=_s(thread_id),
        parent_id=_s(parent_id),
        author_id=_s(author_id),
        author_name=_s(author_name),
        text=text,
        created_at=_to_iso(created_at),
        lang="",
        raw=dict(raw or {}),
    )


def _messenger_event(value, platform: str, tenant_id: str, account_id: str, kind=KIND_DM):
    """Messenger / IG DM {sender, recipient, message{mid,text,is_echo}, timestamp}"""
    v = _dict(value)
    sender = _dict(v.get("sender"))
    recipient = _dict(v.get("recipient"))
    msg = _dict(v.get("message"))
    if not msg:
        return None
    if msg.get("is_echo") or msg.get("is_deleted") or msg.get("is_unsupported"):
        return None
    sid = _s(sender.get("id"))
    rid = _s(recipient.get("id"))
    self_id = _s(account_id) or rid
    if not sid or sid == self_id:
        return None
    return _mk(
        platform=platform,
        tenant_id=tenant_id,
        account_id=self_id,
        kind=kind,
        message_id=_s(msg.get("mid")) or _s(v.get("message_id")),
        thread_id=sid,
        parent_id=_s(v.get("reply_to") or msg.get("reply_to_mid")),
        author_id=sid,
        author_name=_s(sender.get("username") or sender.get("name")),
        text=_s(msg.get("text")),
        created_at=v.get("timestamp"),
        raw={
            "peer_id": sid,
            "recipient_id": rid,
            "message_type": _s(msg.get("type")),
            "raw": v,
        },
    )


def _ig_comment(value, tenant_id: str, account_id: str):
    v = _dict(value)
    frm = _dict(v.get("from"))
    media = _dict(v.get("media"))
    author_id = _s(frm.get("id"))
    if v.get("is_echo"):
        return None
    if author_id and author_id == _s(account_id):
        return None
    return _mk(
        platform="meta_instagram",
        tenant_id=tenant_id,
        account_id=account_id,
        kind=KIND_COMMENT,
        message_id=_s(v.get("id")) or _s(v.get("comment_id")),
        thread_id=_s(media.get("id")) or _s(v.get("media_id")),
        parent_id=_s(v.get("parent_id")),
        author_id=author_id,
        author_name=_s(frm.get("username")),
        text=_s(v.get("text")),
        created_at=v.get("created_time") or v.get("timestamp"),
        raw={"media_id": _s(media.get("id")), "raw": v},
    )


def _parse_instagram(payload: dict, tenant_id: str) -> list:
    if _s(payload.get("object")) not in ("instagram", ""):
        return []
    out = []
    for entry in _list(payload.get("entry")):
        e = _dict(entry)
        account_id = _s(e.get("id"))
        for ch in _list(e.get("changes")):
            c = _dict(ch)
            field = _s(c.get("field")).lower()
            val = c.get("value")
            if field == "comments":
                ev = _ig_comment(val, tenant_id, account_id)
            elif field == "messages":
                ev = _messenger_event(val, "meta_instagram", tenant_id, account_id)
            elif field == "message_reactions":
                ev = None
            else:
                ev = None
            if ev:
                out.append(ev)
        for m in _list(e.get("messaging")):
            ev = _messenger_event(m, "meta_instagram", tenant_id, account_id)
            if ev:
                out.append(ev)
    return out


def _fb_feed_comment(value, tenant_id: str, account_id: str):
    v = _dict(value)
    if _s(v.get("item")).lower() != "comment":
        return None
    frm = _dict(v.get("from"))
    author_id = _s(frm.get("id"))
    if v.get("is_echo"):
        return None
    if author_id and author_id == _s(account_id):
        return None
    post_id = _s(v.get("post_id"))
    return _mk(
        platform="meta_facebook",
        tenant_id=tenant_id,
        account_id=account_id,
        kind=KIND_COMMENT,
        message_id=_s(v.get("comment_id")) or _s(v.get("id")),
        thread_id=post_id,
        parent_id=_s(v.get("parent_id")),
        author_id=author_id,
        author_name=_s(frm.get("name")),
        text=_s(v.get("message")) or _s(v.get("text")),
        created_at=v.get("created_time") or v.get("timestamp"),
        raw={"post_id": post_id, "verb": _s(v.get("verb")), "raw": v},
    )


def _parse_facebook(payload: dict, tenant_id: str) -> list:
    if _s(payload.get("object")) not in ("page", ""):
        return []
    out = []
    for entry in _list(payload.get("entry")):
        e = _dict(entry)
        account_id = _s(e.get("id"))
        for ch in _list(e.get("changes")):
            c = _dict(ch)
            field = _s(c.get("field")).lower()
            val = c.get("value")
            if field == "feed":
                ev = _fb_feed_comment(val, tenant_id, account_id)
            elif field == "messages":
                ev = _messenger_event(val, "meta_facebook", tenant_id, account_id)
            else:
                ev = None
            if ev:
                out.append(ev)
        for m in _list(e.get("messaging")):
            ev = _messenger_event(m, "meta_facebook", tenant_id, account_id)
            if ev:
                out.append(ev)
    return out


def _parse_line(payload: dict, tenant_id: str) -> list:
    out = []
    account_id = _s(payload.get("destination"))
    for event in _list(payload.get("events")):
        e = _dict(event)
        if _s(e.get("type")) != "message":
            continue
        msg = _dict(e.get("message"))
        if _s(msg.get("type")) != "text":
            continue
        src = _dict(e.get("source"))
        author_id = _s(src.get("userId"))
        if author_id and author_id == account_id:
            continue
        thread_id = (
            _s(src.get("groupId")) or _s(src.get("roomId")) or author_id
        )
        ev = _mk(
            platform="line",
            tenant_id=tenant_id,
            account_id=account_id,
            kind=KIND_DM,
            message_id=_s(msg.get("id")),
            thread_id=thread_id,
            parent_id="",
            author_id=author_id,
            author_name="",
            text=_s(msg.get("text")),
            created_at=e.get("timestamp"),
            raw={
                "reply_token": _s(e.get("replyToken")),
                "source_type": _s(src.get("type")),
                "user_id": author_id,
                "raw": e,
            },
        )
        if ev:
            out.append(ev)
    return out


def _parse_tiktok(payload: dict, tenant_id: str) -> list:
    ev_name = _s(payload.get("event")) or _s(payload.get("type"))
    if ev_name not in ("comment.create", "comment.reply"):
        return []
    d = _dict(payload.get("data")) or _dict(payload.get("content"))
    inner = _dict(d.get("data"))
    if inner:
        d = inner

    account_id = (
        _s(payload.get("business_id"))
        or _s(payload.get("client_key"))
        or _s(d.get("business_id"))
        or _s(d.get("owner_id"))
    )
    author_id = (
        _s(d.get("user_id"))
        or _s(d.get("comment_user_id"))
        or _s(_dict(d.get("user")).get("id"))
    )
    if author_id and author_id == account_id:
        return []
    if d.get("is_owner") or d.get("is_self") or d.get("from_owner"):
        return []

    ev = _mk(
        platform="tiktok",
        tenant_id=tenant_id,
        account_id=account_id,
        kind=KIND_COMMENT,
        message_id=_s(d.get("comment_id")) or _s(d.get("id")),
        thread_id=_s(d.get("video_id")) or _s(d.get("item_id")),
        parent_id=_s(d.get("parent_comment_id")) or _s(d.get("reply_comment_id")),
        author_id=author_id,
        author_name=_s(d.get("username")) or _s(_dict(d.get("user")).get("display_name")),
        text=_s(d.get("text")) or _s(d.get("comment_text")),
        created_at=d.get("create_time") or d.get("create_time_ms") or payload.get("timestamp"),
        raw={
            "video_id": _s(d.get("video_id")) or _s(d.get("item_id")),
            "event": ev_name,
            "raw": payload,
        },
    )
    return [ev] if ev else []


_PARSERS = {
    "meta_instagram": _parse_instagram,
    "meta_facebook": _parse_facebook,
    "line": _parse_line,
    "tiktok": _parse_tiktok,
}


def parse(platform: str, payload: dict, tenant_id: str) -> list:
    """ list[InboundEvent] -> [] raise"""
    fn = _PARSERS.get(platform)
    if fn is None or not isinstance(payload, dict):
        return []
    try:
        events = fn(payload, tenant_id) or []
    except Exception:
        return []
    return [e for e in events if isinstance(e, InboundEvent)]


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
def _coerce_event(ev) -> InboundEvent:
    if isinstance(ev, InboundEvent):
        return ev
    if isinstance(ev, dict):
        return InboundEvent(**ev)
    raise TypeError("ev must be InboundEvent or dict")


def _bearer(creds: dict, *names) -> str:
    for n in names:
        v = creds.get(n)
        if v:
            return _s(v)
    return ""


def build_reply_request(platform: str, ev, text: str, creds: dict) -> OutRequest:
    """transport 

     /  (, kind)  raise ValueError
    
    """
    e = _coerce_event(ev)
    c = _dict(creds)
    body_text = _s(text)

    if platform == "meta_instagram":
        token = _bearer(c, "meta_access_token", "page_access_token", "access_token", "ig_access_token")
        if e.kind == KIND_COMMENT:
            url = ENDPOINTS["meta_instagram"]["comment_reply"].format(
                message_id=e.message_id
            )
            return OutRequest(
                platform=platform,
                method="POST",
                url=url,
                headers=_json_headers(token),
                body={"message": body_text},
                target=e.message_id,
            )
        if e.kind == KIND_DM:
            url = ENDPOINTS["meta_instagram"]["dm"]
            peer = _s(e.raw.get("peer_id")) or e.author_id
            return OutRequest(
                platform=platform,
                method="POST",
                url=url,
                headers=_json_headers(token),
                body={
                    "recipient": {"id": peer},
                    "message": {"text": body_text},
                    "messaging_type": "RESPONSE",  # VERIFY
                },
                target=peer,
            )
        raise ValueError(f"unsupported kind for meta_instagram: {e.kind}")

    if platform == "meta_facebook":
        token = _bearer(c, "meta_access_token", "page_access_token", "access_token")
        if e.kind == KIND_COMMENT:
            url = ENDPOINTS["meta_facebook"]["comment_reply"].format(
                message_id=e.message_id
            )
            return OutRequest(
                platform=platform,
                method="POST",
                url=url,
                headers=_json_headers(token),
                body={"message": body_text},
                target=e.message_id,
            )
        if e.kind == KIND_DM:
            url = ENDPOINTS["meta_facebook"]["dm"].format(thread_id=e.thread_id)
            peer = _s(e.raw.get("peer_id")) or e.author_id or e.thread_id
            return OutRequest(
                platform=platform,
                method="POST",
                url=url,
                headers=_json_headers(token),
                body={
                    "recipient": {"id": peer},
                    "message": {"text": body_text},
                    "messaging_type": "RESPONSE",
                },
                target=e.thread_id or peer,
            )
        raise ValueError(f"unsupported kind for meta_facebook: {e.kind}")

    if platform == "line":
        token = _bearer(c, "line_channel_access_token", "line_access_token", "channel_access_token")
        reply_token = _s(_dict(e.raw).get("reply_token")) or _s(c.get("line_reply_token"))
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if _s(c.get("line_delivery")).lower() == "push" or not reply_token:
            return OutRequest(
                platform=platform,
                method="POST",
                url=ENDPOINTS["line"]["push"],
                headers=headers,
                body={
                    "to": e.author_id,
                    "messages": [{"type": "text", "text": body_text}],
                },
                target=e.author_id,
            )
        return OutRequest(
            platform=platform,
            method="POST",
            url=ENDPOINTS["line"]["reply"],
            headers=headers,
            body={
                "replyToken": reply_token,
                "messages": [{"type": "text", "text": body_text}],
            },
            target=e.thread_id or e.author_id,
        )

    if platform == "tiktok":
        token = _bearer(c, "tiktok_access_token", "access_token")
        business_id = _s(c.get("tiktok_business_id")) or e.account_id
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Access-Token"] = token
        return OutRequest(
            platform=platform,
            method="POST",
            url=ENDPOINTS["tiktok"]["comment_reply"],
            headers=headers,
            body={
                "business_id": business_id,  # VERIFY
                "video_id": e.thread_id,  # VERIFY
                "comment_id": e.message_id,  # VERIFY
                "text": body_text,  # VERIFY
            },
            target=e.message_id,
        )

    raise ValueError(f"unsupported platform: {platform!r}")


def _json_headers(token: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


assert set(ENDPOINTS) == set(contracts.PLATFORMS), "ENDPOINTS "
