"""Core primitives: LF_UTF8_v1 hashing, artifact naming, generation ids."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone

#: A generation id looks like ``20261022T043928Z_c4fadc50311c``:
#: a UTC timestamp plus 12 lowercase hex characters.
GEN_RE = re.compile(r"^\d{8}T\d{6}Z_[0-9a-f]{12}$")

#: Agent names are kebab/snake safe, lowercase, start with a letter.
AGENT_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")

_BOM = b"\xef\xbb\xbf"


def lf_utf8_v1(raw: bytes) -> str:
    """Normalize bytes with the LF_UTF8_v1 rule.

    * drop one leading UTF-8 BOM
    * convert CRLF and lone CR to LF
    * decode as UTF-8
    * do **not** strip whitespace
    * do **not** append a trailing newline
    """
    if raw.startswith(_BOM):
        raw = raw[len(_BOM):]
    raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return raw.decode("utf-8")


def sha256_lf_utf8_v1(raw: bytes) -> str:
    """SHA-256 of the LF_UTF8_v1 normalized text."""
    return hashlib.sha256(lf_utf8_v1(raw).encode("utf-8")).hexdigest()


def sha256_text(text: str) -> str:
    """SHA-256 of an already-normalized string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def generation_id(when: datetime | None = None, entropy: bytes | None = None) -> str:
    """Build a generation id.

    ``when`` defaults to now in UTC. ``entropy`` defaults to 6 random bytes,
    which yields 12 hex characters. Pass deterministic entropy in tests.
    """
    if when is None:
        when = datetime.now(timezone.utc)
    when = when.astimezone(timezone.utc)
    if entropy is None:
        entropy = secrets.token_bytes(6)
    if len(entropy) < 6:
        raise ValueError("entropy must provide at least 6 bytes")
    return f"{when:%Y%m%dT%H%M%SZ}_{entropy[:6].hex()}"


def artifact_name(agent: str, kind: str, generation: str) -> str:
    """Canonical artifact file name, e.g. ``demo_handoff_context_<gen>.md``."""
    if kind not in ("context", "summary", "index"):
        raise ValueError(f"unknown artifact kind: {kind}")
    suffix = "json" if kind == "index" else "md"
    return f"{agent}_handoff_{kind}_{generation}.{suffix}"


def parse_generation(value: str) -> datetime:
    """Validate a generation id and return its timestamp (UTC)."""
    if not GEN_RE.match(value or ""):
        raise ValueError(f"generation id format is invalid: {value!r}")
    return datetime.strptime(value[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
