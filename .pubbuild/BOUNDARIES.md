# ReplyBridge 模組邊界（施工契約）

repo 根：/app/conversations/6ae97ea907d06e3f830d1dd2/replybridge
一律只依賴 Python 3.11 stdlib，不得 pip install，不得連外網（測試全部用假 payload / 注入式 transport）。

| 檔案 | 擁有者 | 職責 | 不得做的事 |
|---|---|---|---|
| rb/contracts.py | 主持人（已凍結） | 唯一型別契約 | 任何人不得改 |
| rb/channels.py | W1 | 4 平台簽章驗證、payload 正規化、外送請求組裝 | 不得寫政策判斷 |
| rb/policy.py | W2 | 規則引擎、護欄、信心閘門、升級人類 | 不得呼叫網路、不得寫 DB |
| rb/ai.py | W3 | KB 檢索式草稿、可插拔 LLM provider、信心分數 | 不得送訊息 |
| rb/ledger.py | W4 | sqlite 帳本（hash chain）、去重、速率、待辦隊列、統計 | 不得做政策判斷 |
| rb/server.py | 主持人 | HTTP 入口、組裝 | — |
| tests/test_*.py | 各模組擁有者 | 自己的單元測試，須可 `python3 -m pytest` 或直接執行 | 不得依賴其他模組未完成的檔案 |
| tests/e2e.py | 主持人 | 端到端 | — |

介面凍結（違反即整合失敗）：
- `channels.verify(platform, headers, raw_body, secrets) -> bool`
- `channels.parse(platform, payload, tenant_id) -> list[InboundEvent]`
- `channels.build_reply_request(platform, ev, text, creds) -> OutRequest`
- `channels.verify_challenge(platform, query) -> str | None`
- `policy.Policy(config).decide(ev, draft_fn, store) -> Decision`
- `ai.Drafter(kb, provider=None).draft(ev) -> Draft`
- `ledger.Store(path).<Store Protocol 全部方法>`
