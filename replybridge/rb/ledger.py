"""ReplyBridge sqlite hash chain

W4 Python 3.11 stdlib
 BOUNDARIES.md

`ledger.Store(path)`  contracts.Store Protocol

 sqlite3 check_same_thread=False threading.RLock
append()  hash → 
 SQL 
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from typing import Any, Optional

GENESIS = "0" * 64

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS seen (
        key  TEXT PRIMARY KEY,
        meta TEXT,
        ts   REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rate (
        bucket       TEXT    NOT NULL,
        window_start INTEGER NOT NULL,
        count        INTEGER NOT NULL,
        PRIMARY KEY (bucket, window_start)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ledger (
        seq       INTEGER PRIMARY KEY AUTOINCREMENT,
        kind      TEXT,
        payload   TEXT,
        prev_hash TEXT,
        hash      TEXT,
        ts        REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS queue (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        event       TEXT,
        decision    TEXT,
        status      TEXT DEFAULT 'open',
        created     REAL,
        resolved_by TEXT,
        reply       TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_queue_status_created ON queue(status, created)",
)


def canonical_json(obj: Any) -> str:
    """ ASCII"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def chain_hash(prev_hash: str, kind: str, payload_json: str, ts: float) -> str:
    """hash = sha256(prev_hash + '\\n' + kind + '\\n' + canonical_json(payload) + '\\n' + f'{ts:.6f}')"""
    material = f"{prev_hash}\n{kind}\n{payload_json}\n{ts:.6f}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _loads(raw: Any) -> Any:
    """ JSON store """
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


class Store:
    """contracts.Store """

    def __init__(self, path: str) -> None:
        self.path = path
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=30000")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            if path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            for ddl in SCHEMA:
                self._conn.execute(ddl)
            self._conn.commit()

    def _write(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _tail_hash(self) -> str:
        """ hash"""
        rows = self._conn.execute(
            "SELECT hash FROM ledger ORDER BY seq DESC LIMIT 1"
        ).fetchall()
        return rows[0]["hash"] if rows else GENESIS

    def seen(self, key: str) -> bool:
        rows = self._query("SELECT 1 FROM seen WHERE key = ? LIMIT 1", (key,))
        return bool(rows)

    def mark_seen(self, key: str, meta: Optional[dict] = None) -> None:
        """ key """
        self._write(
            "INSERT OR IGNORE INTO seen(key, meta, ts) VALUES(?, ?, ?)",
            (key, canonical_json(meta if meta is not None else {}), time.time()),
        )

    def incr_rate(self, bucket: str, window_s: int) -> int:
        """ 3 """
        if int(window_s) <= 0:
            raise ValueError("window_s must be positive")
        window_s = int(window_s)
        now = time.time()
        window_start = int(now // window_s * window_s)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO rate(bucket, window_start, count) VALUES(?, ?, 1)
                ON CONFLICT(bucket, window_start)
                DO UPDATE SET count = rate.count + 1
                """,
                (bucket, window_start),
            )
            self._conn.execute(
                "DELETE FROM rate WHERE window_start < ?",
                (int(now - 3 * window_s),),
            )
            row = self._conn.execute(
                "SELECT count FROM rate WHERE bucket = ? AND window_start = ?",
                (bucket, window_start),
            ).fetchone()
            self._conn.commit()
        return int(row["count"])

    def append(self, kind: str, payload: dict) -> dict:
        """ {'seq','hash','prev_hash'}"""
        payload_json = canonical_json(payload if payload is not None else {})
        with self._lock:
            prev_hash = self._tail_hash()
            ts = time.time()
            digest = chain_hash(prev_hash, kind, payload_json, ts)
            cur = self._conn.execute(
                """
                INSERT INTO ledger(kind, payload, prev_hash, hash, ts)
                VALUES(?, ?, ?, ?, ?)
                """,
                (kind, payload_json, prev_hash, digest, ts),
            )
            self._conn.commit()
            seq = int(cur.lastrowid)
        return {"seq": seq, "hash": digest, "prev_hash": prev_hash}

    def verify_chain(self) -> tuple:
        """ (True, None) (False,  seq)"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, kind, payload, prev_hash, hash, ts FROM ledger ORDER BY seq ASC"
            ).fetchall()
        expected_prev = GENESIS
        for row in rows:
            payload = _loads(row["payload"])
            if not isinstance(payload, (dict, list)):
                return (False, int(row["seq"]))
            recomputed = chain_hash(
                expected_prev, row["kind"], canonical_json(payload), float(row["ts"])
            )
            if row["prev_hash"] != expected_prev or row["hash"] != recomputed:
                return (False, int(row["seq"]))
            expected_prev = row["hash"]
        return (True, None)

    def enqueue(self, event: dict, decision: dict) -> int:
        """ queue id"""
        cur = self._write(
            "INSERT INTO queue(event, decision, status, created) VALUES(?, ?, 'open', ?)",
            (
                canonical_json(event if event is not None else {}),
                canonical_json(decision if decision is not None else {}),
                time.time(),
            ),
        )
        return int(cur.lastrowid)

    def list_queue(self, limit: int = 50) -> list:
        """ status='open' created """
        rows = self._query(
            """
            SELECT id, event, decision, status, created, resolved_by, reply
            FROM queue
            WHERE status = 'open'
            ORDER BY created ASC, id ASC
            LIMIT ?
            """,
            (max(0, int(limit)),),
        )
        out = []
        for row in rows:
            out.append(
                {
                    "id": int(row["id"]),
                    "event": _loads(row["event"]),
                    "decision": _loads(row["decision"]),
                    "status": row["status"],
                    "created": row["created"],
                    "resolved_by": row["resolved_by"],
                    "reply": row["reply"],
                }
            )
        return out

    def resolve_queue(self, item_id: int, reply_text: str, by: str) -> dict:
        """ id  KeyError"""
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM queue WHERE id = ?", (int(item_id),)
            ).fetchone()
            if row is None:
                raise KeyError(item_id)
            self._conn.execute(
                """
                UPDATE queue
                   SET status = 'resolved', reply = ?, resolved_by = ?
                 WHERE id = ?
                """,
                (reply_text, by, int(item_id)),
            )
            self._conn.commit()
        return {"id": int(item_id), "status": "resolved"}

    def stats(self) -> dict:
        """by_action / by_platform  ledger payload """
        with self._lock:
            ledger_entries = int(
                self._conn.execute("SELECT COUNT(*) AS n FROM ledger").fetchone()["n"]
            )
            queue_open = int(
                self._conn.execute(
                    "SELECT COUNT(*) AS n FROM queue WHERE status = 'open'"
                ).fetchone()["n"]
            )
            seen_count = int(
                self._conn.execute("SELECT COUNT(*) AS n FROM seen").fetchone()["n"]
            )
            rows = self._conn.execute("SELECT payload FROM ledger").fetchall()

        by_action: dict = {}
        by_platform: dict = {}
        for row in rows:
            payload = _loads(row["payload"])
            if not isinstance(payload, dict):
                continue
            action = payload.get("action")
            if isinstance(action, str) and action:
                by_action[action] = by_action.get(action, 0) + 1
            platform = payload.get("platform")
            if isinstance(platform, str) and platform:
                by_platform[platform] = by_platform.get(platform, 0) + 1

        return {
            "ledger_entries": ledger_entries,
            "by_action": by_action,
            "by_platform": by_platform,
            "queue_open": queue_open,
            "chain_ok": self.verify_chain()[0],
            "seen_count": seen_count,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
