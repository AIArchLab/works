"""外送傳輸層。正式環境用 HttpTransport；測試與演示用 RecordingTransport。"""
import json
import urllib.request
import urllib.error


class Transport:
    def send(self, req) -> dict:
        raise NotImplementedError


class HttpTransport(Transport):
    """真實 HTTP 外送。逾時 10 秒，失敗回錯誤但不拋。"""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def send(self, req) -> dict:
        data = json.dumps(req.body, ensure_ascii=False).encode("utf-8")
        r = urllib.request.Request(req.url, data=data, method=req.method,
                                   headers={**req.headers, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=self.timeout) as resp:
                return {"status": resp.status, "body": resp.read(500).decode("utf-8", "replace")}
        except urllib.error.HTTPError as e:
            return {"status": e.code, "body": e.read(500).decode("utf-8", "replace")}
        except Exception as e:  # 網路層失敗不得讓整個 pipeline 崩
            return {"status": 0, "body": f"transport_error:{type(e).__name__}:{e}"}


class RecordingTransport(Transport):
    """測試用：記錄每一次外送，可指定平台強制失敗，用來驗證重試與升級路徑。"""

    def __init__(self, fail_platforms=()):
        self.sent = []
        self.fail_platforms = set(fail_platforms)

    def send(self, req) -> dict:
        self.sent.append(req)
        if req.platform in self.fail_platforms:
            return {"status": 500, "body": '{"error":"simulated"}'}
        return {"status": 200, "body": '{"ok":true}'}
