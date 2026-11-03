# 安全與信任邊界

- API keys 靜態注入，按 tenant / actor / reader-worker 授權。不是 OIDC、SSO 或 task-level ACL。
- 金鑰同時存在則輪替加入／移除由部署者設定並重啟。未提供自助帳務、金鑰管理或審批後台。
- SQL 全部參數化；Broker 不執行 bundle 指令、不下載 reference、不解壓附件、不寫入客戶指定路徑。檔名只是邏輯名稱，不是磁碟路徑。
- Bundle / summary / reference 全部是未受信任資料；不得拿文字內容升級 runtime 權限或覆蓋系統政策。
- 含密碼、refresh token、真實客戶資料的 checkpoint 不得送入 Broker。本版沒有 DLP／祕密偵測，不是「寫了禁止就能攔住」。
- SQLite 與備份包含任務內容、附件及 idempotency 回應（含 lease secret）。必須用主機 ACL、加密磁碟與備份加密保護；本版沒有應用層加密、KMS 或 WORM。
- 單台 SQLite WAL，非 HA；只支援本機可靠檔案系統，不建議 NFS。多 tenant 是邏輯隔離，不是獨立資料庫／程序隔離。
- Hash chain 可協助檢查資料完整性，沒有外部可信錨定就不能抵抗持有 DB 寫入權者重算整條鏈。
- 必須以 TLS / reverse proxy / request timeout / rate limit 保護公開入口；本版無 DoS 防護、登入節流或正式負載測試。
- requests / events 無自動 retention，長期運作會成長。此版需受控 pilot、容量監控與備份流程。
- SDK 用固定 timeout，不自動重試；重試者必須使用原 Idempotency-Key。重播的過期 lease 不會重新生效。
- 內建控制台讀寫 key 僅在頁面記憶體；launch.py 的 URL fragment 僅用於 loopback bootstrap 並立即清除。敏感環境以受控 UI 登入替換，不共用啟動 URL。
- Windows 檔案 ACL、macOS、Docker、瀏覽器點擊流程均尚未完成實機驗證。

安全問題請由 AIArchLab 專案交付管道回報；不要把秘密貼進公開 issue。
