# RelayHandoff 動態圖協作 Brief

狀態：等待同儕自行接單與提交；沒有預先標記任何人已承諾交付。

## 要講清楚的事

**不是把摘要從 A 搬到 B，而是讓任務狀態、提交權與驗收證據跨 runtime 延續。**

這是技術敘事提案；品牌與賣點用語待同儕定稿。成品直接提交本 repo，不經董事長搬運。

## 建議分鏡（約 25–35 秒，可循環）

| 段落 | 畫面動作 | 要看懂的事 |
|---|---|---|
| 1｜任務仍在 | 同一張任務卡包含 goal、checkpoint、artifact；Source 是 Python | 任務不是聊天紀錄 |
| 2｜提交與封存 | state、revision、artifact digest 進 Broker；顯示 PREPARED | 可恢復的狀態與交付物已保存 |
| 3｜暫停寫入 | Source 與 Target 指向 Broker 的 write 箭頭都被阻擋 | 交接期間不能搶寫；不是強制停止 OS process |
| 4｜新 runtime 驗證 | Node 讀 bundle、核對 digest，顯示 CLAIMED，但 write 仍關閉 | Claim 不等於獲准寫入 |
| 5｜確認接手 | ACK 後，Node 顯示 epoch 2、write 開啟 | 確認後才接續提交 |
| 6｜舊 owner 失效 | Python 以 epoch 1 write，被 Broker 拒絕 | 防止 Broker 內 stale write |
| 7｜有證據的繼續 | Node 提交結果與 receipt，audit 串起流程 | 接手和結果可以回查 |

可加一個獨立恢復支線：ACK 前失敗／逾時 → 新 epoch → 重新接續。不可畫成 ACK 後仍可原路 cancel，也不可畫成永久卡住。

## 空間與視覺語法

- 固定三區：Source runtime / RelayHandoff Broker / Target runtime。
- 任務卡保持同一個 task id；runtime 變了，不代表換了一件工作。
- 分開呈現 state、artifact、ownership、receipt，不把它們都畫成一團「memory」。
- 要有明確的 Broker 邊界；拒寫能力不可延伸畫到未整合的 Git、DB、社群 API。
- 僅以真實測過的 Python／Node 標示 reference runtime；不得把其他產品 logo 當成已整合證據。
- 不顯示真 API key、lease secret、客戶資料或原始憑證。
- 提供可暫停／重播，避免快速閃爍；縮小到 README 寬度仍可讀。

## 交付位置

- `media/task-continuity.*`：成品，例如 GIF、MP4、WebM；SVG 若含 script 不可當 GitHub inline 動畫保證。
- `media/poster.png` 或 `.svg`：不支援動畫時的靜態海報。
- `media/source/`：可編輯來源；若有外部素材，列出來源與授權。
- `media/PROVENANCE.md`：作者、日期、內容基準 commit、畫面屬概念動畫或實際錄影、工具／版本、重現命令、各成品 SHA-256。
- 本檔接單紀錄與 review 結果：直接 commit／PR，不另建外部進度板。

建議 GIF 小於 8 MiB，MP4 為 H.264/yuv420p。視需要保留高解析原稿，GitHub README 預覽以實際渲染驗證為準。

## 驗收

1. 每個畫面對應 README 或 `PROTOCOL.md` 的真實語義。
2. 清楚分開保存、接手 ACK、任務完成；不把三者畫成同一步。
3. 成品能解碼播放、尺寸可讀，附來源與重現方式。
4. 在 GitHub 實際預覽，不把「檔案存在」算渲染成功。
5. 概念動畫標明 conceptual visualization；實際操作錄影標明版本與錄製環境。
6. 成品到位並完成驗收後，才更新 README 預覽。現在不放假素材或失效佔位圖。

## 接單與提交紀錄

尚未收到同儕接單或成品。請接手者在此新增自己的作者／分工／commit／阻斷；不得替其他人確認接單。
