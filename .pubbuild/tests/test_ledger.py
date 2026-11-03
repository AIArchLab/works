#!/usr/bin/env python3
"""ReplyBridge 持久層單元測試（W4）。

直接執行： python3 tests/test_ledger.py
全部用暫存 sqlite 檔，不碰網路、不依賴其他模組。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rb.ledger import GENESIS, Store, canonical_json, chain_hash  # noqa: E402

RESULTS = []


def test(fn):
    RESULTS.append(fn)
    return fn


class tmp_store:
    """每個測試一個乾淨的暫存 DB（含巢狀目錄，順便驗證自動建目錄）。"""

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="rb_ledger_")
        self.path = os.path.join(self.dir, "nested", "deep", "ledger.db")
        self.store = Store(self.path)
        return self.store

    def __exit__(self, *exc):
        try:
            self.store.close()
        finally:
            for root, dirs, files in os.walk(self.dir, topdown=False):
                for f in files:
                    os.unlink(os.path.join(root, f))
                for d in dirs:
                    os.rmdir(os.path.join(root, d))
            os.rmdir(self.dir)


# ---------------------------------------------------------------- 1. 去重
@test
def test_dedupe_second_seen_true_and_no_duplicate_row():
    with tmp_store() as s:
        key = "meta_instagram:17841400000000:mid_AAA"
        assert s.seen(key) is False, "fresh key must not be seen"
        s.mark_seen(key, {"platform": "meta_instagram", "n": 1})
        assert s.seen(key) is True, "after mark_seen key must be seen"
        s.mark_seen(key, {"platform": "meta_instagram", "n": 2})  # 重複寫入
        assert s.seen(key) is True
        assert s.stats()["seen_count"] == 1, "mark_seen must be idempotent"
        rows = s._conn.execute("SELECT meta FROM seen WHERE key = ?", (key,)).fetchall()
        assert len(rows) == 1
        assert json.loads(rows[0]["meta"])["n"] == 1, "duplicate mark_seen must not overwrite"


# --------------------------------------------------- 2. 速率同窗累加 / 跨窗重置
@test
def test_incr_rate_accumulates_in_same_window():
    with tmp_store() as s:
        vals = [s.incr_rate("line:acct:thread-1", 60) for _ in range(5)]
        assert vals == [1, 2, 3, 4, 5], f"same-window counts wrong: {vals}"
        # 不同桶互不干擾
        assert s.incr_rate("line:acct:thread-2", 60) == 1


@test
def test_incr_rate_resets_across_window():
    with tmp_store() as s:
        bucket = "tiktok:acct:video-9"
        assert s.incr_rate(bucket, 1) == 1
        assert s.incr_rate(bucket, 1) == 2
        time.sleep(1.15)  # 跨到下一刻
        assert s.incr_rate(bucket, 1) == 1, "counter must reset in a new window"
        # 兩個窗都還在表中（未超過 3 窗）
        n = s._conn.execute("SELECT COUNT(*) AS n FROM rate WHERE bucket = ?", (bucket,)).fetchone()["n"]
        assert n == 2, f"expected 2 retained windows, got {n}"


@test
def test_incr_rate_purges_windows_older_than_three():
    with tmp_store() as s:
        bucket = "meta_facebook:acct:post-1"
        ancient = int(time.time()) - 10_000
        s._conn.execute(
            "INSERT INTO rate(bucket, window_start, count) VALUES(?, ?, ?)",
            (bucket, ancient, 99),
        )
        s._conn.commit()
        assert s.incr_rate(bucket, 60) == 1
        left = s._conn.execute(
            "SELECT COUNT(*) AS n FROM rate WHERE window_start = ?", (ancient,)
        ).fetchone()["n"]
        assert left == 0, "windows older than 3*window_s must be deleted"


# --------------------------------------------------------------- 3. 雜湊鏈
@test
def test_chain_hash_matches_documented_formula():
    with tmp_store() as s:
        payload = {"platform": "line", "action": "reply", "text": "哈囉\n世界", "n": [1, 2]}
        r1 = s.append("policy.decision", payload)
        assert r1["seq"] == 1
        assert r1["prev_hash"] == GENESIS and len(GENESIS) == 64, "genesis prev_hash must be 64 zeros"
        row = s._conn.execute("SELECT ts, payload FROM ledger WHERE seq = 1").fetchone()
        canon = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        assert row["payload"] == canon, "payload must be stored as canonical json"
        manual = hashlib.sha256(
            (GENESIS + "\n" + "policy.decision" + "\n" + canon + "\n" + f'{row["ts"]:.6f}').encode("utf-8")
        ).hexdigest()
        assert r1["hash"] == manual, "hash does not match documented formula"
        assert chain_hash(GENESIS, "policy.decision", canon, row["ts"]) == manual
        r2 = s.append("policy.decision", {"platform": "line", "action": "escalate"})
        assert r2["prev_hash"] == r1["hash"], "second entry must link to first hash"
        assert r2["seq"] == 2


@test
def test_verify_chain_true_after_appends():
    with tmp_store() as s:
        assert s.verify_chain() == (True, None), "empty chain must verify"
        for i in range(25):
            s.append("event", {"i": i, "platform": "line" if i % 2 else "tiktok", "action": "reply"})
        assert s.verify_chain() == (True, None)


@test
def test_verify_chain_detects_tampered_payload_at_seq():
    with tmp_store() as s:
        for i in range(6):
            s.append("event", {"i": i, "action": "reply"})
        s._conn.execute("UPDATE ledger SET hash = hash WHERE seq = 99")  # no-op 確認 SQL 正常
        s._conn.execute(
            "UPDATE ledger SET payload = ? WHERE seq = 4",
            (canonical_json({"i": 4, "action": "ignore"}),),
        )
        s._conn.commit()
        ok, at = s.verify_chain()
        assert ok is False, "tampering must break the chain"
        assert at == 4, f"broken_at should be 4, got {at}"


@test
def test_verify_chain_detects_tampered_prev_hash():
    with tmp_store() as s:
        for i in range(4):
            s.append("event", {"i": i})
        s._conn.execute("UPDATE ledger SET prev_hash = ? WHERE seq = 3", ("f" * 64,))
        s._conn.commit()
        ok, at = s.verify_chain()
        assert (ok, at) == (False, 3), f"expected (False, 3), got {(ok, at)}"


# ----------------------------------------------------------------- 4. 隊列
@test
def test_enqueue_list_resolve_flow():
    with tmp_store() as s:
        id1 = s.enqueue({"message_id": "m1", "platform": "line"},
                        {"action": "escalate", "reason": "low confidence"})
        time.sleep(0.01)
        id2 = s.enqueue({"message_id": "m2", "platform": "meta_facebook"},
                        {"action": "escalate", "reason": "policy hit"})
        assert isinstance(id1, int) and isinstance(id2, int) and id1 < id2

        q = s.list_queue(50)
        assert [x["id"] for x in q] == [id1, id2], f"queue must be created ASC, got {[x['id'] for x in q]}"
        assert q[0]["status"] == "open"
        assert q[0]["event"]["message_id"] == "m1"
        assert q[0]["decision"]["action"] == "escalate"
        assert s.stats()["queue_open"] == 2

        out = s.resolve_queue(id1, "已人工回覆：請提供訂單號", "ops@brand")
        assert out == {"id": id1, "status": "resolved"}, f"unexpected resolve result {out}"

        q2 = s.list_queue(50)
        assert [x["id"] for x in q2] == [id2], "resolved item must leave the open queue"
        assert s.stats()["queue_open"] == 1
        assert s.list_queue(1) and len(s.list_queue(1)) == 1, "limit must be honoured"
        row = s._conn.execute(
            "SELECT reply, resolved_by, status FROM queue WHERE id = ?", (id1,)
        ).fetchone()
        assert row["status"] == "resolved"
        assert row["reply"] == "已人工回覆：請提供訂單號"
        assert row["resolved_by"] == "ops@brand"


@test
def test_resolve_missing_id_raises_keyerror():
    with tmp_store() as s:
        try:
            s.resolve_queue(424242, "x", "ops")
        except KeyError as e:
            assert "424242" in str(e) or e.args[0] == 424242
        else:
            raise AssertionError("resolve_queue on missing id must raise KeyError")


# ----------------------------------------------------------------- 5. 統計
@test
def test_stats_fields_and_aggregation():
    with tmp_store() as s:
        s.mark_seen("k1", {})
        s.mark_seen("k2", {})
        s.append("policy.decision", {"action": "reply", "platform": "line"})
        s.append("policy.decision", {"action": "reply", "platform": "meta_instagram"})
        s.append("policy.decision", {"action": "escalate", "platform": "line"})
        s.append("policy.decision", {"action": "ignore"})                 # 無 platform
        s.append("transport.result", {"status": 200, "action": None})     # 兩者皆缺 → 跳過
        s.enqueue({"a": 1}, {"action": "escalate"})

        st = s.stats()
        expected_keys = {"ledger_entries", "by_action", "by_platform", "queue_open", "chain_ok", "seen_count"}
        assert set(st) == expected_keys, f"stats keys wrong: {sorted(st)}"
        assert st["ledger_entries"] == 5
        assert st["by_action"] == {"reply": 2, "escalate": 1, "ignore": 1}, st["by_action"]
        assert st["by_platform"] == {"line": 2, "meta_instagram": 1}, st["by_platform"]
        assert st["queue_open"] == 1
        assert st["seen_count"] == 2
        assert st["chain_ok"] is True
        assert isinstance(st["by_action"], dict) and isinstance(st["by_platform"], dict)


# ------------------------------------------------------------- 6. 併發完整性
@test
def test_concurrent_appends_keep_chain_intact():
    with tmp_store() as s:
        n_threads, per_thread = 20, 5
        errors = []
        barrier = threading.Barrier(n_threads)

        def worker(tid: int):
            try:
                barrier.wait(timeout=10)
                for i in range(per_thread):
                    s.append("concurrent", {"tid": tid, "i": i, "text": f"執行緒{tid}-{i}"})
            except BaseException as e:  # noqa: BLE001
                errors.append(f"{type(e).__name__}: {e}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert not errors, f"thread errors: {errors[:3]}"

        total = n_threads * per_thread
        ok, at = s.verify_chain()
        assert ok is True, f"chain broken at seq {at} after concurrency"
        assert s.stats()["ledger_entries"] == total, f"expected {total} entries"
        seqs = [r["seq"] for r in s._conn.execute("SELECT seq FROM ledger ORDER BY seq").fetchall()]
        assert seqs == list(range(1, total + 1)), "seq must be contiguous 1..N"


# ------------------------------------------------------------- 7. 其他不變量
@test
def test_store_creates_directory_and_reopens_persistently():
    with tempfile.TemporaryDirectory(prefix="rb_ledger_p_") as d:
        path = os.path.join(d, "a", "b", "p.db")
        s1 = Store(path)
        r = s1.append("event", {"k": "v"})
        s1.mark_seen("persist-key", {"x": 1})
        s1.close()
        assert os.path.exists(path), "store must create parent directories"
        s2 = Store(path)
        try:
            assert s2.seen("persist-key") is True
            assert s2.verify_chain() == (True, None)
            r2 = s2.append("event", {"k": "v2"})
            assert r2["prev_hash"] == r["hash"], "reopened store must continue the same chain"
        finally:
            s2.close()


@test
def test_parameter_binding_survives_hostile_strings():
    with tmp_store() as s:
        evil = "x'); DROP TABLE ledger;--"
        s.mark_seen(evil, {"note": evil})
        assert s.seen(evil) is True
        s.incr_rate(evil, 60)
        assert s.incr_rate(evil, 60) == 2
        s.append("event", {"text": evil, "platform": evil})
        assert s.verify_chain() == (True, None)
        id_ = s.enqueue({"text": evil}, {"reply": evil})
        s.resolve_queue(id_, evil, evil)
        assert s.stats()["ledger_entries"] == 1


def main() -> int:
    passed = failed = 0
    for fn in RESULTS:
        name = fn.__name__
        try:
            fn()
        except BaseException:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
        else:
            passed += 1
            print(f"PASS {name}")
    print(f"--- {passed} passed, {failed} failed, {len(RESULTS)} total ---")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
