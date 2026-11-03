# relayhandoff/1 adapter 契約

## Transport

HTTP JSON，基底 `/v1/tasks`。所有業務端點需 `Authorization: Bearer <key>`；所有 POST 另需 `Content-Type: application/json` 與 `Idempotency-Key`（1–128 字元）。同租戶、同 actor、同 key、同 method/path/body 重播原回應；不同請求重用 key 回 409。失敗請求不儲存回應。網路不確定時必須保留原 key 重試；SDK 預設產新 key，呼叫者須明確傳入重試 key。

錯誤：`{"error":"machine_code"}`。400 格式錯誤、401 憑證錯誤、403 不具寫入權／錯 lease secret、404 無此租戶內資源、409 狀態／租約／revision 衝突、413 限額、415 非 JSON。無憑證 health `/health`；控制台 `/`。

| Method | Route（相對基底） | Body／回傳重點 |
|---|---|---|
| GET | 空字串 | 最近最多 100 筆該租戶任務摘要，無分頁 |
| POST | 空字串 | `{state:{...}}` → task id |
| GET | `/{id}` | phase / owner / epoch / revision / state / outputs |
| POST | `/{id}/acquire` | `{ttl:60}` → lease secret / epoch / expires |
| POST | `/{id}/renew` | `{lease,epoch,ttl}` → expires |
| POST | `/{id}/write` | `{lease,epoch,revision,state,artifacts?:[{name,base64,sha256}]}` |
| POST | `/{id}/prepare` | `{lease,epoch,revision,summary,references?:[{uri,sha256}],timeout?:120}` → handoff_id / sha256 / deadline |
| GET | `/{id}/bundle` | bundle / bundle_base64 / sha256 / handoff_id / deadline |
| POST | `/{id}/claim` | `{handoff_id}` → lease / epoch / sha256 / handoff_id |
| POST | `/{id}/ack` | `{handoff_id,lease,epoch,sha256,ttl?:60}` → acknowledged / revision / expires |
| POST | `/{id}/cancel` | `{handoff_id,ttl?:60}` → 新 lease / epoch |
| GET | `/{id}/events` | task 相關 events；hash-chain 是 tenant 範圍，跨 task 會有鏈結間隔 |

租約 TTL 2–300 秒；handoff timeout 2–3600 秒。POST body 上限 2 MiB；state+outputs 編碼後上限 1 MiB。每次 write 最多 20 個附件；附件 base64 字串最多 1 MiB。state 是整體替換，不是 patch；outputs 同名更新、其餘保留，blob 的 hash 對應該版本位元組。MVP 無刪除與 retention API。

## 狀態與 ownership

`ACTIVE(source) → PREPARED(所有 write 凍結) → CLAIMED(所有 write 仍凍結) → ACTIVE(target)`。

1. source adapter 必須先在自身 runtime 的安全邊界停止啟動新工作，等當前工具完成，才 checkpoint/prepare。
2. Broker 不會中斷、暫停或取消遠端 process。prepare 只凍結 Broker 管理的寫入。
3. receiver 核對預期 handoff_id、bundle digest、task identity、附件、外部 reference 與本機必要能力，再 ACK。
4. `bundle_base64` 的解碼位元組是 hash 的權威輸入。**不要跨語言重新序列化 JSON 後計算 hash**。SDK 驗證 bundle 與內嵌 artifacts；reference URI 本版只存 pointer，不自動下載或驗證外部 bytes。
5. ACK 代表 adapter 宣告準備完成，不是客觀證明模型已理解任務、外部檔案已具備或實際工作成功。
6. 只有新 owner 的未過期 lease + 正確 epoch + 當前 revision 才能 write。
7. source 可在 ACK 前 cancel；cancel 發新 epoch 與 lease，舊 source token、claimed target token 一併失效。ACK 後不能 cancel。
8. handoff deadline 到期後，任一該租戶 worker 可 acquire 接手；舊目標 ACK 被拒絕。claim、ack、cancel、write 的競態在單一 DB transaction 下裁決。
9. 正常 lease 過期也可由該租戶 worker acquire。故 worker 是租戶內受信任執行者，不是 task 級別零信任隔離。

## 外部副作用

外部 Git push、SQL、社群發布若不接受 fencing，Broker 不能阻止 stale process 直接操作。`check lease → 呼叫外部 API` 有 TOCTOU，不能當作 exactly-once。Adapter 應採目的端條件寫入、idempotency key 或 outbox/side-effect gateway；本版未提供外部 side-effect gateway。

## Runtime adapter 最小責任

提供：`stop_at_safe_boundary`、`checkpoint`、`verify_inputs_and_capabilities`、`claim_and_ack`、`resume`、`heartbeat`、`stop_on_lease_loss`。Python 與 Node 參考程式展示 cooperative checkpoint；沒有假造 DSH、Claude Code、Cursor 或其他 runtime 的控制 API。自動 LLM 摘要可外接，預設 summary 由 source 明確提供。
