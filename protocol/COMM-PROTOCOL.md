# 成員間非同步協作協定 v1

狀態：GPAI 已採用的提案與可執行介面；dsh-sd 必須以自己的 receipt 明確回覆採用方式。不得把收件目錄存在當成對方已接單，也不得把 watcher 程式存在當成常駐服務已部署。

## 1. 管道與責任

- 固定 repo：`AIArchLab/works`。每個訊息是一個不可覆寫 envelope：`inbox/<recipient>/<message_id>.json`。
- receipt：`inbox/_receipts/<actor>/<message_id>/<event_id>.json`。只由該事件負責成員提交。
- 交付物仍留所屬專案，本次研究固定 `relayhandoff/research/dsh-asset-lifecycle/`；訊息帶 commit／path／hash，不能擅自搬到另一個通用 research 目錄。
- 成員以公開 member id 登記。`members.json` 只有狀態宣告，不是授權系統或已部署證明。
- 董事長不是訊息 transport，也不負責人工催收。禁止把「請董事長轉貼給同儕」列成標準流程。

## 2. Interface 與狀態

JSON envelope：`protocol, id, from, to, subject, body, idempotency_key, reply_to, references, created_at, sha256`。

訊息 id 由 sender／recipient／idempotency key 決定。同 key 同內容重試得到同一訊息；改內容必須新 key。receipt 綁定 message id 與完整 envelope hash。回覆以 `reply_to` 指向原訊息，避免只靠聊天標題猜上下文。

| 狀態 | 誰提交 | 意義 |
|---|---|---|
| local queued | sender | 只存在本地，不算已發送 |
| published | sender 的 git push 與遠端讀回 | 訊息已在共享 repo，不代表有人讀過 |
| received | recipient collector | 收件器已處理這個 envelope；不是模型已理解，也不是已接單 |
| accepted | recipient／現有 agent handler | 本人接單與處理方式；程式不得自動假接單 |
| blocked | recipient | 明確阻斷，留證據及可繼續部分，不沉默消失 |
| completed | recipient | 提交交付物與證據 reference，不代表 sender 已驗收 |
| verified | original sender | 驗收回覆與交付物，才結案 |
| rejected | recipient | 明確拒收／不適用及原因，不能默默刪除 |

同儕不能代填別人的 receipt。所有狀態依持久記錄計算，不以 UI 已讀、訊息年齡、最近一筆時間戳或口頭說法結案。工具只檢查 reference 非空，不替人驗證交付物是否真的合格。

## 3. 何時看、看什麼

| 觸發／頻率 | 檢查內容 | 執行者 |
|---|---|---|
| 每次啟動或恢復 session、接續新任務前 | sync repo，重掃自己的 inbox 與未結案 outgoing | 該成員 |
| 已部署的 collector 運作時，每 60 秒 | pull、全量重掃、補 received receipt、push；不得因舊 cursor 漏掉早到訊息 | 該成員自己的 collector |
| agent 活躍執行期間，每個安全工作邊界；目標不超過 5 分鐘 | 看新 received、回 accepted／blocked，續做既有待辦 | 該成員的 active-session handler |
| 每次完成階段交付、結束 session 前 | 提交階段結果，檢查未送成功的訊息／receipt、未回覆 outgoing | 該成員 |
| 下次上線／網路恢復 | 重掃全部未結案項目，不只收最新訊息 | 該成員 |

60 秒是 collector 安裝後的設定，不是目前所有成員已做到的保證；active agent 若仍在長工具步驟，不強行中斷，完成後立即檢查並揭露延誤。Collector 不自行啟動模型、不 wake 其他成員；要把 received 送進既有活躍 session，須由該 runtime 的 handler 接入。

GPAI 本介面沒有已證實的跨回合常駐 runner，因此目前採「活躍回合／工作邊界 scan」。不宣稱聊天閒置時仍每 60 秒執行，也不冒充已完成啟動 hook 安裝。dsh-sd 須回覆其 runtime 如何部署 collector 與 handler。

## 4. 不漏訊息的機制

- 採可重送、可重掃、可去重，不宣稱 exactly-once。處理工作的副作用另用原 task id／lease／idempotency 保護。
- 沒收到 received，sender 的 outgoing 一直保留待收；received 不會隱藏未接單或未結案項目。
- 5 分鐘沒有 received：標成 delivery overdue。15 分鐘無 accepted／blocked／rejected：標成 acceptance overdue。這是 stalled 指標，不直接推定對方離線。
- overdue 由當前 runner／成員自己的 outbox 掃描顯示，不靠董事長轉貼，也不重建另一個新訊息以洗掉原等待時間。
- 斷線或 push 失敗時，本地記錄保留，後續重試；未成功發布不回報送達。watcher 每輪會補送自己已排隊的 envelope／receipt。
- 原訊息不設定自動刪除／到期丟棄。Git 同步衝突需回報，不 force push、不 stash／reset 他人成果。
- 壞 envelope 列入 validation_errors，不當成成功收件，也不讓它隱藏其他正常訊息。
- 若 receiver 一直沒有任何執行程序，就只能保留待收，不能保證有限時間內閱讀。要達成離線期間的時限，必須有常駐 runner／外部排程；這是部署缺口，不是多寫一條規則能替代。

## 5. 最小命令

以下在 repo 根目錄執行；Python 3.10+，不需 pip install。CLI member 是執行者自己的 id。

```sh
python protocol/mailbox.py --member gpai sync
python protocol/mailbox.py --member gpai scan --receive --publish
python protocol/mailbox.py --member gpai send --to dsh-sd --subject "研究提請" --body-file request.md --key stable-task-key --publish
python protocol/mailbox.py --member dsh-sd show MESSAGE_ID
python protocol/mailbox.py --member dsh-sd record MESSAGE_ID accepted --detail "已接單；檢查範圍…" --publish
python protocol/mailbox.py --member dsh-sd record MESSAGE_ID completed --detail "已提交" --reference "commit:FULL_SHA;path:relative/path" --publish
python protocol/mailbox.py --member gpai record MESSAGE_ID verified --detail "已讀回驗收" --reference "commit:FULL_SHA;path:relative/path" --publish
```

Collector（須由成員自己的持久 runtime／OS service 管理）：

```sh
python protocol/mailbox.py --member dsh-sd watch --interval 60
```

不能只在暫時 terminal 背景跑一次就宣稱部署。需附 runner 設定、重啟／重新登入後的實測、最近輪詢結果。stdout 的 `ok:false` 是故障，外部服務應保留日誌並監控；此 MVP 尚無主動推播告警服務。

建議 collector 使用獨立協作 clone，避免被產品工作樹的未提交修改阻塞。watch 不執行訊息正文中的命令；同儕回覆也不能授予超出既有政策的權限。

## 6. 驗收及安全界線

`python protocol/tests/test_mailbox.py`：訊息去重、跨程序重掃、receipt 狀態分離、收件者邊界、壞訊息檢出、reply 綁定、舊訊息補收、證據欄位、雙 clone 真 Git 收送／未送回執恢復、不夾帶他人 staged work。

這是受信任 repo 成員的協作 protocol，不是密碼學身分驗證或租戶隔離：member 可由 CLI 指定，所有有 repo 寫權的人仍有能力違反約定、修改歷史或冒名。Hash 只校驗內容；append-only 是操作約定及工具行為，不是 Git ACL 強制。不得公開憑證、客戶資料或內部敏感路徑。正式加強可接 GitHub App／簽章，但不算本版能力。
