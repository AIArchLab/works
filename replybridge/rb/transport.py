""" HttpTransport RecordingTransport"""
import json
import urllib.request
import urllib.error


class Transport:
    def send(self, req) -> dict:
        raise NotImplementedError


class HttpTransport(Transport):
    """ HTTP  10 """

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
        except Exception as e:
            return {"status": 0, "body": f"transport_error:{type(e).__name__}:{e}"}


class RecordingTransport(Transport):
    """"""

    def __init__(self, fail_platforms=()):
        self.sent = []
        self.fail_platforms = set(fail_platforms)

    def send(self, req) -> dict:
        self.sent.append(req)
        if req.platform in self.fail_platforms:
            return {"status": 500, "body": '{"error":"simulated"}'}
        return {"status": 200, "body": '{"ok":true}'}
