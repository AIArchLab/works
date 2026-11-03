# ReplyBridge — 跨平台留言／私訊 AI 自動回覆路由器

一個可自架的入站訊息路由器：IG／FB／LINE／TikTok 的留言與私訊進同一條管線，經過**政策層**（規則、護欄、靜默時段、速率、信心閘門）決定「回覆／升級人工／忽略」，每一則決策都寫進**可驗證帳本**（hash chain）。

起點是 Tasker 案件 TK26110314FORT69，但這一版不是為那個案子寫死：**換客戶＝改 `config/tenants.json` 與 `config/kb.json`，不改程式碼**。案件只佔其中一個 tenant。

## 為什麼不是「四平台串接腳本」

串 API 只是一天的工。真正決定這類系統能不能見人的是四件事，這也是本 MVP 的骨幹：

1. **不回的時候怎麼辦**：敏感內容、信心不足、靜默時段、超速率、使用者要真人 → 一律進人工隊列，不硬回。
2. **失敗不能假裝成功**：平台外送失敗會改判升級並記錄失敗碼，不會在帳上留一筆「已回覆」。
3. **重複不能重複回**：同一個 message_id 送兩次只回一次（冪等）。
4. **每則回覆要能被追溯**：哪條規則、哪個 KB 條目、信心多少、延遲多少，全部入帳，且帳本改一列就驗不過。

## 架構

```
IG / FB / LINE / TikTok webhook
        │  簽章驗證（HMAC / base64 / sha256= 三種格式）
        ▼
  channels.parse()  ──►  InboundEvent（統一事件）
        ▼
  policy.decide()   ──►  Decision(reply | escalate | ignore)
        │                   ├─ 規則命中（canned）
        │                   ├─ KB 檢索草稿 + 信心閘門
        │                   └─ 護欄 / 靜默 / 速率 / 去重
        ▼
  channels.build_reply_request()  ──►  平台 API
        ▼
  ledger（hash chain 帳本 + 人工隊列 + 統計）
        ▼
  後台（GET / 內建單頁）／ /queue ／ /stats
```

## 檔案

| 路徑 | 內容 |
|---|---|
| `rb/contracts.py` | 凍結的型別契約（事件、草稿、裁決、外送、Store） |
| `rb/channels.py` | 四平台簽章驗證、payload 正規化、外送請求組裝 |
| `rb/policy.py` | 規則引擎、護欄、信心閘門、升級人類 |
| `rb/ai.py` | KB 檢索式草稿、可插拔 LLM provider、信心分數 |
| `rb/ledger.py` | sqlite hash chain 帳本、去重、速率窗、隊列、統計 |
| `rb/core.py` | 編排：入站 → 政策 → 外送 → 帳本（可注入 transport） |
| `rb/server.py` | HTTP 入口 + 內建後台單頁 + `--demo` 模式 |
| `config/tenants.json` | 多租戶設定（兩個 tenant：本案 + 一個無關品牌） |
| `config/kb.json` | 知識庫（檢索式草稿的事實來源） |
| `tools/validate_tenant.py` | 新客戶設定檢查（缺護欄會擋） |
| `tools/run_all_tests.sh` | 一鍵重跑全部測試 |
| `tests/e2e.py` | 端到端：真的起 server、真的送簽章 webhook、真的走政策與外送 |

## 怎麼跑

```bash
cd replybridge

# 0) 設定檢查（新客戶上線前的守門員）
python3 tools/validate_tenant.py config/tenants.json

# 1) 全部測試（單元 + 端到端）
bash tools/run_all_tests.sh

# 2) 本機 demo（不真打平台 API，把要送出的請求印在主控台）
python3 -m rb.server --port 8080 --demo
#   開 http://127.0.0.1:8080/ 就是後台；/stats、/queue 是 API

# 3) 正式跑（密鑰只從環境變數注入，不落檔）
RB_SECRETS_JSON='{"meta_app_secret":"...","meta_verify_token":"...","line_channel_secret":"...","tiktok_client_secret":"..."}' \
  python3 -m rb.server --port 8080

# 4) 容器化
docker build -t replybridge . && docker run -p 8080:8080 -e RB_SECRETS_JSON=... replybridge
```

平台端設定（每個平台各一次）：把 webhook 指向 `https://<你的網域>/webhooks/<platform>`，`platform` 用 `meta_instagram`／`meta_facebook`／`line`／`tiktok`。Meta 的訂閱握手走同一條路徑的 GET。

## 驗證邊界（哪些真的跑過、哪些沒有）

跑得過：本機 E2E 33 項全綠（含簽章拒絕、冪等、五種升級路徑、外送失敗、人工核准、50 則併發、帳本鏈完整性），單元測試涵蓋四平台解析與簽章、政策 12 情境、KB 檢索、帳本併發與篡改偵測。

**沒跑過、也沒宣稱**：真實平台 API 的送出（需要各平台憑證與審核）、Meta/LINE/TikTok 的正式 webhook 註冊、LLM provider 的實際接線（未配置時走 KB 檢索並如實降級）、跨機器部署與 TLS。

## 已知限制

- 私訊受平台回覆窗口限制（例：Messenger 24 小時），超窗只能升級人工，本版未做 window 計算，只把平台錯誤如實轉成升級。
- 單一 sqlite writer；多副本部署需換 Postgres 或加單寫入者。
- 靜默時段以設定時區換算，未處理日光節約（台灣無 DST，其他市場要補）。
- TikTok 留言回覆僅適用開通 Business API 的帳號，且需商家授權。
