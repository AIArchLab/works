"""Example durable recipient inbox. Bind to loopback unless put behind HTTPS/auth."""
import hashlib, hmac, http.server, json, sqlite3, time, uuid
from .core import canonical, sign


def server(host, port, db_path, secret, fail_first=0):
    if len(secret) < 16:
        raise ValueError('Webhook secret must be at least 16 characters')
    db = sqlite3.connect(db_path)
    db.execute('CREATE TABLE IF NOT EXISTS inbox(event_id TEXT PRIMARY KEY, digest TEXT NOT NULL, receipt TEXT NOT NULL, payload TEXT NOT NULL)')
    db.commit(); db.close()
    failures = [fail_first]

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path != '/health':
                self.send_error(404); return
            self.server.inspections += 1
            self.send_response(200); self.send_header('Content-Length', '2'); self.end_headers(); self.wfile.write(b'OK')

        def do_POST(self):
            if self.path != '/inbox':
                self.send_error(404); return
            self.server.delivery_requests += 1
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 65536:
                    self.send_error(413); return
                body = self.rfile.read(size)
                ts = self.headers.get('X-Taskloop-Time', '')
                if abs(time.time() - int(ts)) > 300:
                    self.send_error(401); return
                signature = sign(secret, ts.encode() + b'.' + body)
                if not hmac.compare_digest(signature, self.headers.get('X-Taskloop-Signature', '')):
                    self.send_error(401); return
                payload = json.loads(body)
                event_id = payload['event_id']
                if not isinstance(event_id, str) or event_id != self.headers.get('Idempotency-Key'):
                    self.send_error(400); return
                if failures[0] > 0:
                    failures[0] -= 1
                    self.send_error(503); return
                digest = hashlib.sha256(body).hexdigest()
                with sqlite3.connect(db_path, isolation_level=None, timeout=30) as db:
                    db.execute('BEGIN IMMEDIATE')
                    row = db.execute('SELECT digest,receipt FROM inbox WHERE event_id=?', (event_id,)).fetchone()
                    if row:
                        if row[0] != digest:
                            db.execute('ROLLBACK'); self.send_error(409); return
                        receipt = json.loads(row[1])
                    else:
                        receipt = {'accepted': True, 'event_id': event_id, 'receipt_id': str(uuid.uuid4()), 'payload_sha256': digest}
                        db.execute('INSERT INTO inbox VALUES(?,?,?,?)', (event_id, digest, canonical(receipt).decode(), body.decode()))
                    db.execute('COMMIT')
                answer = canonical(receipt)
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('X-Taskloop-Signature', sign(secret, answer)); self.send_header('Content-Length', str(len(answer))); self.end_headers(); self.wfile.write(answer)
            except (ValueError, KeyError, TypeError):
                self.send_error(400)

    instance = http.server.HTTPServer((host, port), Handler)
    instance.inspections = 0
    instance.delivery_requests = 0
    return instance
