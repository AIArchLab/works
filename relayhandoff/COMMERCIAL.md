# 商業交付定義

## 現階段能賣的單位

受控環境的 **跨 runtime 交接 developer package + 整合／驗收 pilot**。交付包含 Broker、Python/Node SDK、控制台、協定、測試、部署設定與操作文件。不宣稱已是無人維運 SaaS 或全 runtime 認證產品。

## 典型採購價值

將任務狀態、交接證據與 ownership 從特定模型／IDE／runtime 抽出；換 runtime 時保留可驗證 checkpoint，而不是依賴使用者轉貼對話。

## Pilot 驗收

1. 客戶指定兩個 runtime；每個 adapter 接入安全邊界、checkpoint、ACK、heartbeat 與失租約停止。
2. 真實任務從 source 換 target，驗證交付物 bytes、revision、接手回執。
3. source stale write、雙重 claim、重啟、超時、取消均測試。
4. 外部副作用逐項列出；未有目的端防重／fencing 的項目不能包成 exactly-once 保證。
5. 明列資料類型、tenant 授權、備份／還原、負責維運者與支援範圍。

## 不包含

任意 runtime 的 drop-in adapter、模型供應／模型計費、雲端託管、SSO、訂閱收款、租戶自助開通、HA、SOC2、法遵認證、無限量附件／歷史、所有 OS 認證。

## 授權與上市門檻

採 proprietary commercial licensing 方向，見 LICENSE。這份檔案不是客戶已簽約、法律已審核或收入已發生的證據。正式商用需由權利人確認授權條款、產品名稱／商標可用性、維運與責任邊界，再簽商業契約。不在程式內捏造試用到期或繳費驗證。

## 版本演進

0.1：本機／受控 pilot。本次實測 Linux 上 Python 與 Node 的跨 runtime HTTP 交接。
下一產品增量：實際接入指定 runtime、外部 side-effect gateway、OIDC、Postgres／HA 與簽章 bundle。不是本版已交付能力。
