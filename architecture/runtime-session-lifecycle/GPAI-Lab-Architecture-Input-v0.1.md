# Runtime Session Lifecycle ADD — Lab Architecture Input v0.1

**Draft - Not for External Use**

- 文件類型：Architecture Definition Document 的 Lab 架構輸入與共同審查基線，不是已核准 ADD。
- 日期：2026-11-05；產出者：GPAI／Lab Technical Architect。
- Runtime Architect：GSpark；Runtime Developer／Space owner：dsh-sd；唯一裁決者：Allen。
- Space 狀態：已請 dsh-sd 本人建立，尚未取得 ID、參與者與入口；本檔不是另建的 Space。
- 設計主件：由 GSpark 在該 Space 整合；其唯一主件 ID、版本、hash 及審查紀錄需由 Space owner 公布。
- 變更門控：ADD 定版前不改相關 DSH runtime/profile/plugin/service/hook。此門控取代先前 SESSION-CONTROL-01 立即停用的指令；Memory Evolve 保持原狀。

## 1. 目的、範圍與完成定義

讓 session 的建立、執行、context 管理、換模型、暫停、恢復、handoff、封存與刪除成為可追溯、可恢復且有明確責任的生命週期；工作、資產及授權不得隨聊天切換而失去或被自動升等。

涵蓋現有 DSH、Session Shift、Memory Evolve、官方 compaction、session persistence/export、模型route、任務/資產與擬議 Lab Memory RAG。GPAI 及其他外部agent只以各自實際可用adapter整合，不假定共享process/session或模型。

不涵蓋未授權採購、外部embedding送件、改供應商平台、複製模型內部狀態、一次性全庫搬遷、刪除session或替代Allen核准。這些不能因本ADD成立而自動取得授權。

ADD完成＝AS-IS證據清楚、TO-BE與介面完整、ADR結案、測試與遷移回退方案對應、三方對精確版本完成審查、Allen採認該版本。ADD完成不等於已部署；部署及滅件操作分開取得相應授權。

## 2. 原始需求及架構需求（REQ）

| ID | 需求 | 對應驗收 |
|---|---|---|
| R01 | 不再讓Allen做人肉轉貼、重教脈絡或每輪決定換班 | T01/T14 |
| R02 | 保留Memory Evolve及既有資產；本案不藉削功能解決Shift缺陷 | T02 |
| R03 | context使用量不是交接完成證據；來源、授權與禁止條件不被摘要吞掉 | T03/T04 |
| R04 | 未完工作可恢復交接，不要求全部工作終態 | T05/T06 |
| R05 | 單一副作用writer、明確模型及權限設定、版本可追蹤 | T07/T08 |
| R06 | 歷史保存、工作記憶、RAG索引與現役context分開 | T09/T10 |
| R07 | 可從崩潰、重啟、回執遺失與重複投遞恢復，不憑推測重做付款等副作用 | T06/T11 |
| R08 | 定版前不動runtime；配置可讀回、遷移可演練、回退不倒退fencing權威 | T12/T13 |
| R09 | 原session刪除前資料/附件保存驗收，且每次滅件另取單次核准 | T09/T15 |

## 3. AS-IS：證據、責任與未知

| 部件 | 已有證據 | 不能宣稱 |
|---|---|---|
| Session Shift公開a0c0f5c、package 0.2.6 | GPAI讀原始碼並跑6項隔離mock；預設60%/壓縮2次、模板最後消息=待辦、400字切片、user來源注入、先建新端再處理停舊端 | 不能以mock當host整合通過；不能以GSpark口述bytes相同代替本機hash原件 |
| Memory Evolve本地包 | GSpark定位D:/DSH_Data/packages/dsh-memory-evolve、notifyUnread及記憶注入 | GPAI尚未讀本地源碼，不能把另一個公開repo當本機版本；不得因此改或停用 |
| 官方compaction/token-meter | 已讀固定commit fcc0ad4的官方文件；display projection不作權威gating；model-switch由目的route量測 | 不能說最新master能力已在本機啟用 |
| DSH session export | 已讀官方ZIP/MD差異；原始committed log不因surface compaction而消失 | 不等於本機已掛載；不等於有原生session import/restore |
| 既有Lab任務協議 | AIArchLab/works正式mailbox曾兩輪往返驗收 | 不等於常駐collector、OS scheduler或新session恢復已驗收 |
| 外部GPAI | 隔離雲端；官方回信當時無外部execution API/native scheduled runs | 不把CDP wrapper叫原生API；不冒充原生背景常駐 |

GSpark負責整合安裝版本、有效profile、依賴/載入順序、session拓樸、寫入路徑、目前執行實態；dsh-sd提交去敏原始證據。不只交套件名與「已安裝」清單。

## 4. 架構分層與正本

1. **Execution/context plane**：session、turn、實際模型route及當輪context。它是執行容器，不是唯一工作正本。
2. **Work/control plane**：正式task ID、狀態、actor-owned receipts、執行權與handoff journal；沿用Lab既有協議，不另創平行inbox。
3. **Evidence/asset plane**：原始事件、附件、交付物、版本、來源manifest與受限備份；不放任何可公開的憑證。
4. **Memory/retrieval plane**：Memory Evolve保留；Lab RAG為可重建索引與按需引用，不覆寫工作帳本，不將檢索片段當新指令。

正本優先序依資料種類決定：正式任務/權限/裁決在其帳本；交付物在版本化asset；原始事件在archive；RAG只是索引。衝突須留下來源、有效時間及supersedes，不以最後一則對話一律覆蓋。

## 5. 身分、資料與事件契約

每個session有穩定session_id、parent/fork來源、workspace_id、actor_id、runtime/profile/config hash、建立/更新時間。模型另記provider/model/route及能力/容量來源；不能只靠顯示名稱。

每個task有task_id及正式message來源、scope、授權、禁止條件、狀態、owner/attempt、資產引用。每次handoff有handoff_id、source/target_session、task清單、checkpoint revision、model/profile/permission差異、資產manifest hash及切換狀態。

每個lifecycle事件有event_id、event_type、schema_version、actor、session/task/handoff關聯、occurred_at/recorded_at、前一revision及payload hash。相同id不同payload報衝突；版本更新不得就地篡改舊證據。

來源必須區分human指令、agent判斷、工具結果、plugin生成背景及引用。既有Shift把生成包標成user，所以不能只以source.kind=user推定為Allen的新授權。摘要只是有損表示，限制原文須有可讀回引用。

## 6. Session生命週期（TO-BE邏輯狀態，尚未映射本機實作）

| 狀態 | 進入條件 | 允許動作 | 出口與檢查 |
|---|---|---|---|
| CREATED | 已記錄身分與配置 | 載入最小入口 | 轉RESTORING，不直接取得副作用權 |
| RESTORING | 指向已committed的工作checkpoint | 唯讀讀取、核對模型/權限/來源與待辦 | 完成核對→READY；失敗→FAULTED/保留來源 |
| READY | 恢復檢查通過 | 接收正式任務、取得有效執行權 | 有任務與權限→RUNNING |
| RUNNING | task已接受、有效writer授權 | 授權範圍內執行，持久化checkpoint | turn完成→READY；需換端→QUIESCING |
| QUIESCING | 已關閉新副作用admission | 排空/分類已送出操作、保存checkpoint | 安全暫停→SUSPENDED；handoff依第8節 |
| SUSPENDED | 無新副作用admission，工作位置已保存 | 查閱、恢復準備 | 重驗權/恢復→RESTORING |
| ARCHIVED | 非現役；歷史與附件清單可讀回 | 唯讀查詢/依法另建恢復端 | 刪除須進DELETE_PENDING |
| DELETE_PENDING | 單次刪除申請、保留/備援條件檢查 | 僅核准範圍檢查 | 未核准則不刪；核准並執行→PURGED |
| PURGED | 目標確實刪除且有收據 | 依保留政策查其tombstone/備份 | 不宣稱全部副本消失；備份另有保留規則 |
| FAULTED | 工具、模型、資料或配置失敗 | 讀取證據、隔離副作用、修復 | 不盲目重跑；重新恢復需驗證 |

Session狀態不等於task狀態，也不等於turn是否在stream。標題、日期和[已交接]不是狀態正本。模型stream未commit片段不得算已保存成果。

## 7. Context、compaction與model-switch

- 當輪context可由可見工作入口、必要治理、任務相關記憶及最近內容組成；不修改Memory Evolve現有注入作為本案捷徑。
- display contextPressure可作預警，不能作目的模型admission或handoff成功判定。權威量測須針對同一log revision、有效request envelope與目的route，含輸出預留及headroom。
- 不一律採60%、70%或85%。70%退化僅為Shift作者自測。各route規則及可接受工作餘量須用實際模型/工具資料驗證。
- compaction修改的是模型可見surface；保持原始committed事件及asset定位。摘要不得被當原件或新增授權。
- model-switch先驗目的容量/輸出預留/pressure policy與相容能力，通過才允許其request。失敗保留先前header不表示先前pruning/summary全部回滾，須記實際事件。
- 官方basic compaction、自動恢復、手動compact、工具輸出pruner不得多頭同時改同一範圍。GSpark需給衝突矩陣及載入順序；不得未查證就疊裝更多compressor。
- 長工具輸出截斷前保存可讀原件及範圍引用；8192字不是普遍安全界線，錯誤尾端/程式與數據可能是關鍵證據。

## 8. Handoff協定、writer與副作用

Handoff邏輯流程：PREPARED→RESTORING→ACCEPTED→COMMITTED；未commit失敗記ABORTED/RECOVERY_REQUIRED。此journal不替代正式task協議的published/received/accepted/blocked/completed/verified。

1. **PREPARE**：source關閉新副作用admission，盤點task及in-flight操作，checkpoint及manifest持久化。新端可先建立但僅能恢復/讀取。不能用時間已滿或一個cancel結果當已排空證據。
2. **RESTORE**：target實讀來源、待辦、禁止條件、資產及route/profile/permission；明確繼承原選擇，差異另記。未確認任務不從最後一句推定。
3. **ACCEPT**：target本人留下接收證據及準備接手的task範圍；不能由source代填。
4. **FENCE/COMMIT**：以持久、遞增且有scope的執行權序列，讓各副作用入口在實際提交時拒絕舊writer，再寫commit。資源不可繞過；須撤銷舊直連憑證或走強制代理。沒有資源端fencing就不能聲稱已保證單writer。
5. **RETIRE WRITER**：commit可讀回後source僅唯讀；不自動刪除。ack丟失時查journal，不再次切換或盲目送單。

多資源fencing不是天然分散式ACID。中間失敗時可能已部分封鎖舊writer；先保持無新副作用並reconcile，不自動把token倒退、不默認舊端能復工。回復舊軟體/資料不等於回復舊writer權；重新接手須取得更高且有效的權威。

無idempotency/query的外部API遇到送出後斷線，記UNKNOWN並保留對帳責任，不能同時保證不重複和最終一定完成。重試政策按副作用能力分類。取消turn不撤回已發出的交易。

## 9. Memory擷取、Lab RAG與保存

- Memory Evolve保持原狀；本地版capture入口由GSpark查證，不以公開同名repo推定。
- 原始保存層、工作記憶卡與可重建索引分離。記憶卡包含來源事件、actor、有效時間、authority、supersedes、task/asset引用；agent推論不得自動成為Allen裁決。
- 優先採explicit工具search/read-source的按需召回。評估既有引擎可先隔離fixture；不在現役runtime新增第二套proactive recall。
- 查詢在召回與重排前套用agent/project/workspace/visibility ACL；回覆帶原文與版本。無資料或衝突要明說，不填補虛構歷史。
- 憑證、cookie、私人敏感工具輸出不得進一般共享索引；archive另依其敏感度保護。RAG不是秘密保存器。
- 衰減、合併或記憶刪除不得抹掉正式裁決/帳本與原始來源。index可重建；撤回/保留/刪除在索引、cache與備份上的語意須各自訂定。

## 10. 任務、通知、啟動與外部adapter

- 新session不是新task。既有task ID去重，完成工作不因換端重派。按原協議收件與回執，不代冒他人事件。
- 背景/廣播是具來源與適用對象的資料，不因被Shift搬入而變成全體必做指令。Memory Evolve通知/注入程式在本案不動；若另有問題另案舉證。
- 啟動入口是版本化指標與必要恢復資訊，不能只是一份無限膨脹的敘事。量測啟動context成本、恢復成本及工作餘量，完整列各注入源。
- adapter以各平台可驗證功能接入。GPAI active-turn handler、CDP等過渡層需明確限制；不可宣稱原生API、常駐cron、同模型clone或閒置SLA。
- agent身分、工具授權與憑證各自持有，不以共用repo/Space意味共用secret。Space只是協作入口，不是執行權威本身。

## 11. 崩潰、重啟與一致性

任一邊界崩潰後，先讀durable journal/checkpoint，確認最新commit與有效writer，再決定恢復位置。至少處理：checkpoint未完成、新session建成但尚未接收、accept後未commit、部分fence、commit後回執遺失、結果已提交但task未結案。

採持久message/handoff/attempt IDs及條件更新。檔案與遠端訊息發布若非同一交易，用持久outbox/reconciliation，不把兩個操作假稱原子。臨時目錄與模型記憶不是唯一恢復路徑；重啟不能只重新執行上次prompt。

## 12. 封存、刪除與獨立恢復

封存先保留可查資料與task關聯，不等於session刪除。刪除前需：來源/時間範圍/附件清單核對、完整性讀回、獨立保存、來源不可用條件下恢復測試、保留與法律/工作hold檢查，以及Allen對精確對象的單次核准。

MD是可讀transcript，不是完整runtime image。官方ZIP也不自動證明有可執行session import。必須區分：歷史可讀、附件可用、業務脈絡可重建、原生session可恢復；沒有驗過的級別不得宣稱。

刪除收據列刪掉的範圍、仍保留的備份/索引與期限，不能以主session消失宣稱所有副本已清除。秘密恢復入口與密文不得放同一共享包。

## 13. 元件/介面責任與衝突矩陣

| 元件 | 責任 | 不應越界 |
|---|---|---|
| DSH persistence/export | 保存已commit事件及授權匯出 | 不把browser download當已完成host備份 |
| 官方token-meter/compaction | 路由量測與surface管理 | 不用display meter替代目的route權威量測 |
| Session Shift adapter | lifecycle請求、checkpoint、target恢復/receipt及切換接線 | 不創造task/授權、不以建新即完成、不默取全域設定 |
| Memory Evolve | 既有工作記憶/通知功能 | 本案保持原狀；不被當正式工作/原始資產唯一正本 |
| Lab task/asset ledger | 任務、執行權、成果引用與actor事件 | 不以摘要取代原始證據 |
| Lab RAG | 受權限按需查證與引用 | 不下新指令、不永久權威化舊背景 |
| Space | 三方討論、ADR、版本與審查入口 | 不以「有Space」當ADD已定案/已部署 |

實作須定義read-checkpoint、prepare-handoff、restore、accept、commit、query-status、archive、request-delete、search/read-source的能力契約與去敏錯誤；這是邏輯介面要求，不假裝本機已存在這些API。每個介面指定caller、ACL、idempotency、precondition、durable結果與恢復路徑。

## 14. 可觀測性與可執行政策

事件關聯必含session/task/handoff/attempt、runtime config revision及route。至少記錄：啟動context組成、恢復/切換時長、非必要重做、blocked/UNKNOWN、舊token拒絕、索引命中與來源缺口；不記secret。

政策以測試/檢查落實：沒有驗權不召回、沒有target接收不完成切換、沒有source manifest不宣稱保存齊全、沒有批准版本不部署、沒有單次核准不滅件。警報有明確owner及處理級別，不把所有未讀資訊自動轉全員待辦。

性能與成本門檻尚須使用本機基線訂定；不能捏造p95或容量承諾。定版前必填每route輸入/輸出/啟動餘量、同時session與task規模、恢復目標、資料保留、檢索品質/延遲及存儲成本；缺任一相關基線則對應功能不得宣稱符合SLO。

## 15. 驗收矩陣（設計測試，不是已通過結果）

| ID | 案例 | 通過條件 |
|---|---|---|
| T01 | 同task跨兩次session續作 | 無人工搬運，任務及來源一致，不重派已完成步驟 |
| T02 | Memory Evolve保留 | 啟用與設定hash未被本案改動；相關功能仍可測 |
| T03 | 最後一句僅討論；背景含歷史廣播 | 不產生未授權執行任務 |
| T04 | 長指令尾端含禁止條件 | 恢復端讀到完整限制及原文定位 |
| T05 | 未完工作及UNKNOWN交易交接 | 正確owner/狀態續作，不強迫當完成、不盲重送 |
| T06 | 每個handoff邊界注入崩潰 | 由journal恢復，接收證據/commit不冒填、不重建多個target |
| T07 | 舊writer及已在途操作恢復 | resource端拒絕舊權；無fencing能力明說不能承諾 |
| T08 | 換模型/preset/permission | 明確繼承/差異，目的routebudget不足時安全阻擋 |
| T09 | 原session不可讀下恢復保存物 | 事件及附件可讀回；原生import若聲稱則須實測 |
| T10 | RAG權限、舊裁決與重複匯入 | 未授權零外洩；回有效來源；無重複紀錄 |
| T11 | 網路斷線/commit後ack遺失 | 查實際結果，不重做副作用；UNKNOWN有owner |
| T12 | 變更前門控與fixture隔離 | 無定版/授權則正式runtime無變更；測試不碰正式session |
| T13 | 回退/部分fence失敗 | 軟體可回退、權威不倒退、原件不覆寫 |
| T14 | Space/工具不可用 | 真實blocked可讀；不要求Allen反覆操作；不假稱已接收 |
| T15 | 未核准刪除/批次清理 | 確實拒絕；核准範圍、receipt與保留副本可核對 |

先跑隔離fixture，再跑非破壞canary；錯誤即停止擴大。完整矩陣需由GSpark/dsh-sd映射實際命令、測試檔、資料與原始結果，不能只填PASS字樣。

## 16. 遷移、部署與回退（僅計畫）

G0：本輪凍結與Space開立回執。G1：唯讀AS-IS證據及版本映射。G2：三方審查ADD/ADR，Allen採認精確版本。G3：對應實施計畫/影響範圍授權，備份並驗證去敏配置。G4：隔離測試及非破壞canary。G5：結果驗收後分批部署，觀測並保留可讀回紀錄。

部署owner為dsh-sd，不能由GPAI假稱可操作其host。若需中斷正式工作、修改其他外掛或付費資源，先列具體影響及替代方案，不將ADD採認視為無限授權。變更前已存在的修改如實盤點，不為符合凍結而反向自動restore。

回退觸發：授權/來源丟失、舊writer被接受、無法恢復待辦、重複副作用、資料/來源缺失。先停止新增副作用與擴大，保存證據，回復允許的程式/配置版本；fencing token、已對外提交交易及他人交付物不可直接倒退/覆寫。資料回復與滅件另走單次核准。

## 17. ADR與待決欄位

| ID | 建議 | 狀態/owner |
|---|---|---|
| ADR01 | context/歷史/工作狀態/記憶索引分層 | GPAI建議，GSpark整合審查 |
| ADR02 | 不以自動/手動區分安全；共用交接契約先修 | GPAI建議，需三方採認 |
| ADR03 | 正式任務協議沿用既有mailbox，lifecycle journal不另建平行任務正本 | GPAI建議，dsh-sd映射實作 |
| ADR04 | Memory Evolve原狀；Shift不重包裝其資料成新授權 | Allen既定範圍，需測試保障 |
| ADR05 | 初期按需search，不在現役新增第二套全量注入 | GPAI建議，候選只隔離比較 |
| ADR06 | 權威/持久journal實作與fencing支持 | dsh-sd提可行選項，GSpark比較及決定技術案 |
| ADR07 | 自動觸發策略/啟動餘量/恢復SLO與規模 | GSpark用基線定參數，未量測不承諾 |
| ADR08 | 封存保留與單次刪除責任 | Allen保留最終核准；設計不得偷換成自動清理 |

目前外部缺件：(a)Space真實ID與三方存取，由dsh-sd取得；未交付則只標開立待驗。(b)本機有效套件/設定/所有注入源與寫入路徑，由dsh-sd唯讀匯出、GSpark核對；缺件時不進實施。(c)副作用入口是否可fence/冪等，dsh-sd逐入口測；不支持就不承諾exactly-once/單writer，提出受限處理。(d)三方審查與Allen採認精確版本；缺件則維持runtime凍結，不代填批准。

## 18. 證據索引與審查紀錄

- E01 Session Shift公開原碼： https://github.com/easerlee/dsh-session-shift/blob/a0c0f5c72ef1d24a976cb27b49a983f54aeb9319/lib/index.js
- E02 Token Meter： https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/docs/subsystems/token-meter.md
- E03 Compaction： https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/compaction/compaction-basic/README.md
- E04 Session export： https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/session-query/session-log-export/README.md
以上為2026-11-05本對話已讀固定來源，不代表本機安裝狀態。

三方review表須逐項列 reviewer/role、精確版本hash、accepted/changes-requested、意見與處置；任何留白不得當默認同意。Allen採認列指令來源及版本，部署允許列獨立範圍。現在狀態：GPAI輸入已準備；GSpark/dsh-sd尚未review；Allen未採認；Space尚未驗證；未部署。
