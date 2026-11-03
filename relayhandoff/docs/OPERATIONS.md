# 啟動、操作與部署

從 repo 根目錄先進入 `relayhandoff/`。下列命令均以此為工作目錄。

## 一個指令開始

Python 3.10+（標準函式庫即可，不需 pip install）：

```sh
python launch.py
```

Windows 若環境使用 `py`：`py launch.py`。Linux/macOS 常用 `python3 launch.py`。

會在 loopback 啟動 Broker、建立本機專用金鑰與 SQLite，並開啟控制台。初次金鑰透過 URL fragment 交給頁面記憶體後立即清除 fragment，不進 HTTP request 或 localStorage。不要共用這個啟動 URL。無桌面環境使用 `python launch.py --no-browser`；憑證位於 `.runtime/keys.json`。

## 真正的跨 runtime Demo

需另有 Node.js 18+：

```sh
python demo.py
```

不是 mock：Python 透過 HTTP 寫 checkpoint 與 UTF-8 附件，Broker 封存並凍結舊 owner，獨立 Node.js 程序讀取 bundle、驗 SHA-256 與附件、claim、ACK，再以新 fencing epoch 寫入。最後以舊 token 嘗試覆寫並確認被拒絕。產出 `demo_receipt.json`，不含憑證。

## 操作控制台

建立任務 → 取得租約 → 寫入 checkpoint → 封存並交接。接手者使用自己的 scoped key，在同一 Task ID 按「接手、驗證、ACK」。可讀取任務清單與稽核、取消尚未完成的交接。

控制台不是瀏覽器自動化驗收過的商用品 UI；本版 HTTP 頁面與 API 已驗證，點擊互動尚待瀏覽器驗收。

## 部署

正式服務用 `server.py`，從 `RH_KEYS` 注入 scoped credential JSON；禁止把實際 key commit：

```sh
python server.py --host 127.0.0.1 --port 8787 --db /your/private/path/state.db
```

`RH_KEYS` 格式：`{"至少32字元的隨機密鑰":{"tenant":"客戶識別","actor":"執行者識別","role":"worker"}}`。正式金鑰應以密碼學亂數產生，不能把範例字串當密鑰。

附 Dockerfile / compose.yaml，但本次環境沒有 Docker，**未做容器執行驗收**。對外暴露必須先有 TLS reverse proxy、連線與 body-read timeout、rate limit、備份與網路存取控制。內建 Python HTTP server 僅供本機或受控 pilot，不可直接裸露在 Internet。

## 驗收

```sh
python tests/test_e2e.py
```

詳見 `ACCEPTANCE.md`、`test_report.json`。`PROTOCOL.md` 是 adapter 契約；`openapi.json` 提供機器可讀 API 定義。

