# Issue #2 修正與覆驗入口 — 0.1.1

Issue：https://github.com/AIArchLab/works/issues/2

## 狀態

四項缺陷皆先以同儕原始腳本在未修正版本重現；修正後以明確 acceptance assertions 驗收，不把重現腳本退出或「仍重現」當成 pass。自動驗收通過不代表同儕已覆驗；issue 保留給回報者覆核，不代替其確認。

## 缺陷與檢查對照

| 缺陷 | 修正 | 回歸驗收 |
|---|---|---|
| RH-01a：NaN／Infinity 可存但 Node 無法讀 | ingress 與 Python／Node SDK 共用規格的遞迴 portable JSON 檢查，拒絕非有限值 | 19、21、22：create／nested write、送出前／bundle 解碼；含 NaN、正負 Infinity |
| RH-01b：大整數 digest 正確但值被改變 | number 範圍限制為正負 JS safe-integer 上界；大整數以應用明確 schema 字串表達 | 19–22：正負 9007199254740991 可 roundtrip，超界拒絕；另驗 nested 與合法小數 |
| RH-02：ACK 先於必要內容驗證 | Node receiver 在 ACK 前檢查附件、內容、state；release receiver 同步檢查必要輸入、manifest 與檔案 | 23–25、28：正確 hash 但錯語意、缺附件、缺 state、空 manifest 均無 ACK 且維持 CLAIMED；原案例 1 驗正向續作 |
| RH-03：create 不套 snapshot quota | create／write 呼叫同一 `snapshot_check` | 26：ASCII／多位元組 UTF-8，在 1 MiB 界線以下／以上；超額無 revision 改變 |
| RH-04：零位元組附件被拒絕 | 接受空 base64 並核對 empty bytes hash | 27：Python 寫入、Python／Node 驗證、Node ACK 與下一版 checkpoint |

## 重跑

```sh
python tests/test_issue_2.py
python demo.py
python verify_release.py
```

第一項包含原 18 項測試，不需把兩份入口重複相加。Test 19–28 各含多個子案例，報告中的 28 是 unittest 方法數，不是假稱只有 10 個單一輸入。

`test_report.json` 保存本次完整執行輸出與環境；`release_handoff_receipt.json` 保存更新後候選檔案驗證。`docs/issue-2-before-results.json` 是修正前同儕原始腳本的實際重現結果。

## 範圍與未完成事項

沒有新增 exactly-once、外部 side-effect gateway、runtime 認證、跨 OS 認證或 SaaS 承諾。Docker 因新增共用 JSON validator 已補 COPY sdk，但仍未 build/run 實測；控制台已加入 portable JSON 檢查，但仍無瀏覽器點擊 E2E。

不自動刪除或覆寫既有 DB 的不合格數值；詳見 `PROTOCOL.md`。SHA-256 與語意檢查不能互相取代。舊版下載包不會因 repo 已修正而自行更新，對外應交付 0.1.1 或更新版本。
