# 產品定位與賣點協作稿

狀態：工作稿，市場賣點由董事長邀集同儕定稿。這裡先留下技術定位與證據，**不先替大家宣布 slogan、客群或市場領先地位**。

## 技術架構師的定位提案

從「會話 handoff 插件」往上看，它現在承接的是三個不同的責任：

1. **State continuity**：任務 checkpoint、revision 與交付物不依附於單一對話。
2. **Execution ownership**：Broker 內由誰提交、何時交出、失效後誰接續，有可執行的裁決。
3. **Evidence continuity**：交接內容、驗證、ACK 與後續提交有可核對的紀錄。

暫用描述：**跨 runtime 的任務連續性控制層**。它是架構判斷，不是已驗證市場分類。Handoff 是它的一個操作，不是全部產品價值。

## 同儕定稿區

請直接透過 commit／PR 更新本檔，留下作者、日期、依據與狀態。這一區尚無人被代為標記接單。

| 項目 | 待補內容 |
|---|---|
| 第一優先買方 | 誰的哪一種成本／失敗最值得先解決？ |
| 對外一句話 | 不用內部術語，買方能立即理解的結果 |
| 三個主要賣點 | 每個賣點對應場景、控制與驗收證據 |
| 與既有替代方案的差異 | 需具體比較與來源，不寫未查證競品主張 |
| 動態圖主敘事 | 30 秒內要讓觀眾記住什麼？ |
| Pilot 邊界與成效指標 | 如何驗收、哪些不承諾 |

## 可用證據，不是待包裝的幻想

- `tests/test_e2e.py` / `test_report.json`：18 項自動化案例與實際執行環境。
- `demo.py`：Python 到獨立 Node 程序的端到端接力。
- `verify_release.py` / `release_handoff_receipt.json`：本產品真實候選檔案驗證工作流。
- `PROTOCOL.md`：Broker 內提交權、凍結、ACK、恢復的語義。

## 不得偷換的承諾

- Runtime-agnostic protocol 不等於所有 runtime 已適配。
- Fencing 只在有實際驗證 epoch 的寫入端成立。
- SHA-256 不是身份簽章；無外部錨定的 hash chain 不是不可竄改保證。
- ACK 不是任務完成，也不是模型理解的證明。
- 持久化 checkpoint 不是 OS process／記憶體快照。
- 現在不是完整 scheduler、通用 multi-agent orchestration 或 autonomous governance platform。
- 未經量測不寫「零遺失」「零成本」「無限擴展」「效率提升百分比」。

## 定稿檢查

每個對外能力句應能回到實作、案例或已標示的產品假設；市場推論與 roadmap 不混入已交付清單。董事長尚未決定上架，本次只做 repo 內容與協作準備。
