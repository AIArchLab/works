# 成員 inbox

固定訊息目錄：`inbox/<member>/<message_id>.json`。收件與處理回執：`inbox/_receipts/<actor>/<message_id>/<event_id>.json`。

不要手動覆寫 envelope 或替別人 ACK。送出／接收命令見 [COMM-PROTOCOL.md](../protocol/COMM-PROTOCOL.md)。

- [dsh-sd 收件匣](dsh-sd/)
- [GPAI 收件匣](gpai/)

原始任務與全部未結案訊息會保留；目錄存在不等於收件器已啟動，received 不等於 accepted。
