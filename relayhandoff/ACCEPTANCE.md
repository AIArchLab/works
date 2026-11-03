# Release acceptance — 0.1.1

Issue #2 修正驗收入口：`python tests/test_issue_2.py`。包含下列原 18 項，加 RH-01..04 的 10 項回歸；完整對照見 [ISSUE_2_RESOLUTION.md](docs/ISSUE_2_RESOLUTION.md)。當次環境與結果以 `test_report.json` 為準。

# 原 0.1.0 基線驗收

## 已驗證事實

本次 Linux 實測 18/18 自動化案例通過（時間、runtime 版本與完整輸出見 `test_report.json`）：

1. Python -> 獨立 Node process，UTF-8 checkpoint／附件驗證與舊 source 拒寫。
2. Broker 重啟後 CLAIMED 狀態與 idempotency 回應保留，接續 ACK。
3. PREPARED / CLAIMED 期間不能 write，錯 digest ACK 不能啟用。
4. cancel 讓 claimed token 與舊 source token 同時失效。
5. tenant 隔離、reader 不能寫入、無效 API key 拒絕。
6. 併發 acquire 只有一個 winner。
7. 相同 idempotency key 重播；不同 body 拒絕。
8. 租約過期拒寫、新 owner 的 epoch 遞增。
9. handoff 超時後拒絕舊 ACK、重新 acquire 可恢復。
10. 損毀附件與錯 revision 不能寫入。
11. Audit hash 與事件順序驗證。
12. Dashboard HTML 與 health HTTP 可讀。
13. 錯 owner、重複 claim、非 source cancel 拒絕。
14. 256 種 byte 值完整保留、SDK 預期 bundle digest 不符會拒絕。
15. 同 revision checkpoint 競態只有一個成功。
16. 任務清單 tenant 隔離。
17. ACK / cancel 競態只有一個成功。
18. 不合法 TTL／空 summary／malformed JSON／錯 Content-Type 拒絕。

另已執行出貨版 `demo.py`、`launch.py --no-browser` HTTP smoke，以及三份 Node 程式語法檢查。

## 真實工作流驗收

`verify_release.py` 用本版 Broker 把本次產品 release manifest 從 Python builder 交給獨立 Node reviewer；Node 讀取候選檔案的真實 bytes、逐檔 SHA-256 驗證，通過才 ACK、checkpoint 並回傳 receipt；Python 再從 Broker 讀回驗證。結果見 `release_handoff_receipt.json`。

`MANIFEST.sha256.json` 不包含自身、demo receipt 與 release handoff receipt，避免自我雜湊循環。其餘候選檔案均逐檔驗證；這是內容完整性驗證，不是第三方資安認證。

## 待確認／未驗證

Windows、macOS 實機；Docker build/run；控制台瀏覽器點擊 E2E；DSH／其他指定 Agent runtime 的安全邊界整合；公開網路負載與資安測試；正式商業合約與產品名稱權利清查。

商業定位：受控環境的 developer package / paid pilot MVP。不是已部署的商用 SaaS，也不是全 runtime 已認證成品。
