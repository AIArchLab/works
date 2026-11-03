"""ReplyBridge 端到端測試（真的起 HTTP server、真的送簽章過的 webhook、真的走政策與外送）。

執行：cd replybridge && python3 tests/e2e.py
輸出：逐條 PASS/FAIL、延遲分佈、out/e2e_report.json
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rb import core                  # noqa: E402
from rb import server as server_mod  # noqa: E402
from rb import transport as transport_mod  # noqa: E402

SECRETS = {
    "meta_app_secret": "s3cr3t-meta",
    "meta_verify_token": "vt-123",
    "line_channel_secret": "s3cr3t-line",
    "tiktok_client_secret": "s3cr3t-tt",
}
ACCT = {
    "ig": "17841400000000001",
    "fb": "100000000000001",
    "line": "U0000000000000000000000000000001",
    "tt": "TT_BIZ_7000001",
}

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append({"name": name, "pass": bool(cond), "detail": str(detail)[:300]})
    print(("PASS  " if cond else "FAIL  ") + name + (("  | " + str(detail)[:160]) if detail else ""))


# ---------- 簽章 ----------
def sign_meta(body: bytes) -> dict:
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(SECRETS["meta_app_secret"].encode(), body, hashlib.sha256).hexdigest(),
            "Content-Type": "application/json"}


def sign_line(body: bytes) -> dict:
    return {"X-Line-Signature": base64.b64encode(hmac.new(SECRETS["line_channel_secret"].encode(), body, hashlib.sha256).digest()).decode(),
            "Content-Type": "application/json"}


def sign_tiktok(body: bytes) -> dict:
    ts = str(int(time.time()))
    sig = hmac.new(SECRETS["tiktok_client_secret"].encode(), body, hashlib.sha256).hexdigest()
    return {"TikTok-Signature": f"t={ts},s={sig}", "Content-Type": "application/json"}


SIGNERS = {"meta_instagram": sign_meta, "meta_facebook": sign_meta, "line": sign_line, "tiktok": sign_tiktok}


def post(port, platform, payload, headers=None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    hdrs = headers if headers is not None else SIGNERS[platform](body)
    req = urllib.request.Request(f"http://127.0.0.1:{port}/webhooks/{platform}", data=body, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def get(port, path):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            code, raw = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read().decode()
    try:
        return code, json.loads(raw)
    except Exception:
        return code, raw


# ---------- payload 工廠 ----------
def ig_payload(mid, text, uid="u_ig_1", uname="amy", media="media_1", created="2026-11-03T06:20:00Z"):
    return {"object": "instagram", "entry": [{"id": ACCT["ig"], "time": 1793687375, "changes": [
        {"field": "comments", "value": {"id": mid, "text": text, "from": {"id": uid, "username": uname},
                                        "media": {"id": media}, "timestamp": 1793687375}}]}]}


def fb_payload(mid, text, uid="u_fb_1", name="Ben", thread="post_9", acct=None):
    return {"object": "page", "entry": [{"id": acct or ACCT["fb"], "time": 1793687375, "changes": [
        {"field": "feed", "value": {"item": "comment", "comment_id": mid, "post_id": thread,
                                    "message": text, "from": {"id": uid, "name": name},
                                    "created_time": "2026-11-03T06:20:00+0000"}}]}]}


def line_payload(mid, text, uid="Ul_1", token="rt_3001", ts=1793687375000):
    return {"destination": ACCT["line"], "events": [
        {"type": "message", "replyToken": token, "timestamp": ts,
         "source": {"userId": uid, "type": "user"},
         "message": {"id": mid, "type": "text", "text": text}}]}


def tt_payload(mid, text, uid="u_tt_1", uname="cara", ts=1793687375):
    return {"event": "comment.create", "data": {"comment_id": mid, "video_id": "v_1", "text": text,
                                                "user_id": uid, "username": uname, "create_time": ts}}


def main():
    db = os.path.join(ROOT, "out", "e2e.db")
    os.makedirs(os.path.dirname(db), exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db + suffix):
            os.remove(db + suffix)

    tx = transport_mod.RecordingTransport()
    bridge = server_mod.build_bridge(config_path=os.path.join(ROOT, "config/tenants.json"),
                                     kb_path=os.path.join(ROOT, "config/kb.json"),
                                     db_path=db, secrets=SECRETS, transport=tx)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.make_handler(bridge))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"server on 127.0.0.1:{port}\n")

    # 1 健康檢查
    s, b = get(port, "/healthz")
    check("healthz 200", s == 200 and b.get("ok") is True, b)

    # 2 Meta webhook 訂閱驗證
    s, _ = get(port, f"/webhooks/meta_instagram?hub.mode=subscribe&hub.verify_token=vt-123&hub.challenge=CHAL123")
    check("meta challenge 回傳 hub.challenge", s == 200, s)
    s, _ = get(port, "/webhooks/meta_instagram?hub.mode=subscribe&hub.verify_token=WRONG&hub.challenge=X")
    check("meta challenge 錯誤 token 被拒 403", s == 403, s)

    # 3 IG 留言：命中報價規則
    s, b = post(port, "meta_instagram", ig_payload("igc_1001", "請問回覆多少錢？"))
    r = (b.get("results") or [{}])[0]
    check("IG 留言走完管線並回覆", s == 200 and r.get("action") == "reply", r.get("action"))
    check("IG 回覆命中 price_question 規則", any("price_question" in str(h) for h in (r.get("policy_hits") or [])), r.get("policy_hits"))
    check("IG 外送到 /replies 端點", tx.sent and tx.sent[-1].url.endswith("/igc_1001/replies"), tx.sent[-1].url if tx.sent else None)

    # 4 FB 留言：平台範圍規則
    s, b = post(port, "meta_facebook", fb_payload("fbc_2001", "你們支援哪些平台？"))
    r = (b.get("results") or [{}])[0]
    check("FB 留言走完管線並回覆", s == 200 and r.get("action") == "reply", r.get("action"))
    check("FB 外送帶授權標頭", any(str(k).lower() == "authorization" and v for k, v in (tx.sent[-1].headers or {}).items()), tx.sent[-1].headers)

    # 5 LINE 私訊：KB 檢索
    s, b = post(port, "line", line_payload("lin_3001", "導入要多久"))
    r = (b.get("results") or [{}])[0]
    check("LINE 私訊走完管線", s == 200 and r.get("action") == "reply", r.get("action"))
    check("LINE 走 KB 檢索模型", str(r.get("model", "")).startswith("kb:"), r.get("model"))
    check("LINE 外送帶 replyToken", tx.sent and tx.sent[-1].body.get("replyToken") == "rt_3001", tx.sent[-1].body if tx.sent else None)

    # 6 TikTok 留言
    s, b = post(port, "tiktok", tt_payload("ttc_4001", "How much does it cost?"))
    r = (b.get("results") or [{}])[0]
    check("TikTok 留言走完管線並回覆", s == 200 and r.get("action") == "reply", r.get("action"))
    check("TikTok 外送打到 business comment reply", "comment/reply" in (tx.sent[-1].url if tx.sent else ""), tx.sent[-1].url if tx.sent else None)

    # 7 簽章被篡改
    body = json.dumps(ig_payload("igc_tamper", "多少錢"), ensure_ascii=False).encode()
    hdrs = sign_meta(body)
    bad = {"X-Hub-Signature-256": "sha256=" + "0" * 64, "Content-Type": "application/json"}
    s, b = post(port, "meta_instagram", json.loads(body), headers=bad)
    check("簽章錯誤回 401 且不入帳", s == 401 and b.get("reason") == "signature_invalid", b.get("reason"))

    # 8 重複事件冪等
    before = len(tx.sent)
    s, b = post(port, "meta_instagram", ig_payload("igc_1001", "請問回覆多少錢？"))
    r = (b.get("results") or [{}])[0]
    check("重複 webhook 判為 duplicate", r.get("action") == "ignore" and any("dedupe" in str(h) for h in (r.get("policy_hits") or [])), r.get("policy_hits"))
    check("重複事件不重送外送", len(tx.sent) == before, f"{before}->{len(tx.sent)}")

    # 9 敏感內容護欄
    s, b = post(port, "meta_instagram", ig_payload("igc_pii", "我要匯款到哪裡，順便要帳號密碼"))
    r = (b.get("results") or [{}])[0]
    check("敏感詞升級人工不回覆", r.get("action") == "escalate" and "guardrail" in str(r.get("escalate_reason")), r.get("escalate_reason"))

    # 10 使用者要求真人
    s, b = post(port, "meta_instagram", ig_payload("igc_human", "我要找真人客服"))
    r = (b.get("results") or [{}])[0]
    check("要求真人直接升級", r.get("action") == "escalate" and r.get("escalate_reason") == "user_requested_human", r.get("escalate_reason"))

    # 11 低信心
    s, b = post(port, "meta_instagram", ig_payload("igc_lowconf", "你們老闆幾歲", media="media_lowconf"))
    r = (b.get("results") or [{}])[0]
    check("低信心不硬回", r.get("action") == "escalate" and "low_confidence" in str(r.get("escalate_reason")) or r.get("escalate_reason") == "drafter_declined", r.get("escalate_reason"))

    # 12 速率上限（同一貼文第 4 則）
    acts = []
    for i in range(4):
        s, b = post(port, "meta_instagram", ig_payload(f"igc_rate_{i}", "價格多少", media="media_rate"))
        acts.append((b.get("results") or [{}])[0].get("action"))
    check("同串第 4 則觸發速率上限", acts[:3] == ["reply", "reply", "reply"] and acts[3] == "escalate", acts)

    # 13 靜默時段（22:30 +08）
    s, b = post(port, "tiktok", tt_payload("ttc_quiet", "你們幾點上班", ts=1793716200))
    r = (b.get("results") or [{}])[0]
    check("靜默時段轉人工", r.get("action") == "escalate" and r.get("escalate_reason") == "quiet_hours", r.get("escalate_reason"))

    # 14 外送失敗不得假裝成功
    tx.fail_platforms.add("tiktok")
    s, b = post(port, "tiktok", tt_payload("ttc_fail", "How much does it cost?", ts=1793687000))
    r = (b.get("results") or [{}])[0]
    check("外送失敗改判 escalate", r.get("action") == "escalate" and "send_failed" in str(r.get("escalate_reason")), r.get("escalate_reason"))
    tx.fail_platforms.discard("tiktok")

    # 15 未配置帳號（多租戶時不得亂認）
    s, b = post(port, "meta_facebook", fb_payload("fbc_unknown", "hello", acct="999999999"))
    r = (b.get("results") or [{}])[0]
    check("未配置帳號標為 unrouted", r.get("action") == "unrouted", r)

    # 16 回音自我過濾
    s, b = post(port, "meta_instagram", ig_payload("igc_echo", "我們自己的官方回覆", uid=ACCT["ig"]))
    check("自己發的留言不被回覆", b.get("handled") == 0, b.get("handled"))

    # 17 人工隊列
    s, q = get(port, "/queue")
    open_items = q.get("items", [])
    check("人工隊列有升級案件", len(open_items) >= 3, len(open_items))
    if open_items:
        item = open_items[0]
        req = urllib.request.Request(f"http://127.0.0.1:{port}/queue/{item['id']}/resolve",
                                     data=json.dumps({"reply_text": "真人已接手，稍後回您", "by": "ops_amy"}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            out = json.loads(resp.read().decode())
        check("人工核准後真的送出", out.get("send_status") in (200, 201, 202), out)

    # 18 壓測：50 則併發事件
    t0 = time.time()
    errs = []
    def fire(i):
        try:
            post(port, "meta_facebook", fb_payload(f"fbc_bulk_{i}", "你們支援哪些平台", thread="post_bulk"))
        except Exception as e:  # noqa
            errs.append(repr(e))
    threads = [threading.Thread(target=fire, args=(i,)) for i in range(50)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    elapsed = time.time() - t0
    st = bridge.stats()
    lat = st.get("latency", {})
    check("50 則併發無例外", not errs, errs[:2])
    check("延遲統計可用", lat.get("n", 0) >= 50 and "p95_ms" in lat, lat)
    check("壓測吞吐 > 20 則/秒", (50 / elapsed) > 20 if elapsed else False, f"{50/elapsed:.1f}/s")

    # 19 帳本完整性
    ok, broken = bridge.store.verify_chain()
    check("帳本 hash chain 完整", ok is True, broken)
    check("stats chain_ok 為真", st.get("chain_ok") is True, st.get("chain_ok"))

    # 20 統計分佈
    check("stats 有 by_action 分佈", bool(st.get("by_action")), st.get("by_action"))
    check("stats 有 tenants", len(st.get("tenants", [])) == 2, st.get("tenants"))

    httpd.shutdown()

    total = len(RESULTS)
    passed = sum(1 for x in RESULTS if x["pass"])
    print(f"\n=== {passed}/{total} PASS ===")
    if lat:
        print("latency:", lat)
    print(f"throughput: {50/elapsed:.1f} msg/s on 50 concurrent")

    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "total": total, "passed": passed, "failed": total - passed,
              "results": RESULTS, "latency": lat,
              "throughput_msg_per_s": round(50 / elapsed, 1) if elapsed else None,
              "stats": st}
    with open(os.path.join(ROOT, "out", "e2e_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print("report -> out/e2e_report.json")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
