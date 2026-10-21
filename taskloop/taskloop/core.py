"""Persistent HTTP-check agent and transactional notification outbox. Standard library only."""
import contextlib, datetime, hashlib, hmac, http.client, ipaddress, json, math, os, socket, sqlite3, ssl, time, urllib.parse, uuid


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sign(secret, data):
    return hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()


class PolicyError(ValueError):
    pass


class Network:
    """Exact-host allowlist; public resolved addresses only; redirects never followed."""
    def __init__(self, hosts, allow_local_demo=False, timeout=20):
        self.hosts = {h.lower() for h in hosts}
        self.local = allow_local_demo
        self.timeout = timeout

    def request(self, method, url, data=None, headers=None, limit=65536):
        u = urllib.parse.urlsplit(url)
        if u.username or u.password or u.fragment or u.query or not u.hostname:
            raise PolicyError("Credentials, query strings, fragments or missing host are not allowed")
        host = u.hostname.lower()
        if host not in self.hosts:
            raise PolicyError("Host is not allowlisted")
        if u.scheme != "https" and not (self.local and u.scheme == "http"):
            raise PolicyError("HTTPS is required")
        port = u.port or (443 if u.scheme == "https" else 80)
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not addresses:
            raise PolicyError("Host has no addresses")
        for a in addresses:
            ip = ipaddress.ip_address(a[4][0])
            if not ip.is_global and not (self.local and ip.is_loopback):
                raise PolicyError("Non-public destination is blocked")
        # Connect to an already checked numeric address. No second DNS lookup/rebinding.
        family, kind, proto, _, addr = addresses[0]
        sock = socket.socket(family, kind, proto)
        sock.settimeout(self.timeout)
        conn = None
        try:
            sock.connect(addr)
            if u.scheme == "https":
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            conn = http.client.HTTPConnection(host, port, timeout=self.timeout)
            conn.sock = sock
            path = urllib.parse.urlunsplit(("", "", u.path or "/", u.query, ""))
            conn.request(method, path, body=data, headers=headers or {})
            response = conn.getresponse()
            body = response.read(limit + 1)
            if len(body) > limit:
                raise PolicyError("Response exceeds size limit")
            return response.status, {k.lower(): v for k, v in response.getheaders()}, body
        finally:
            if conn:
                conn.close()
            else:
                sock.close()


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks(
          id TEXT PRIMARY KEY, spec TEXT NOT NULL, due REAL NOT NULL,
          execution TEXT NOT NULL DEFAULT 'pending', observation TEXT,
          result TEXT, attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0,
          lease_owner TEXT, lease_until REAL NOT NULL DEFAULT 0,
          created TEXT NOT NULL, last_error TEXT);
        CREATE TABLE IF NOT EXISTS outbox(
          event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id),
          payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0,
          lease_owner TEXT, lease_until REAL NOT NULL DEFAULT 0, receipt TEXT, last_error TEXT);
        CREATE TABLE IF NOT EXISTS audit(
          n INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
          task_id TEXT, event TEXT NOT NULL, detail TEXT NOT NULL);
        """)

    @contextlib.contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def log(self, task, event, detail):
        self.db.execute("INSERT INTO audit(at,task_id,event,detail) VALUES(?,?,?,?)", (stamp(), task, event, json.dumps(detail)))

    def submit(self, task_id, target, webhook, due, expected=200, owner="local-agent"):
        if not task_id or len(task_id) > 128:
            raise ValueError("Task ID must be 1..128 characters")
        if not isinstance(expected, int) or not 100 <= expected <= 599:
            raise ValueError("Invalid expected HTTP status")
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 128:
            raise ValueError("Owner must be 1..128 characters")
        if not math.isfinite(due):
            raise ValueError("Due time must be finite")
        for url in (target, webhook):
            u = urllib.parse.urlsplit(url)
            if u.scheme not in ('https', 'http') or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise ValueError("Task URLs must not contain credentials, query strings or fragments")
        spec = canonical({"target": target, "webhook": webhook, "expected": expected, "due": due, "owner": owner}).decode()
        with self.transaction():
            old = self.db.execute("SELECT spec FROM tasks WHERE id=?", (task_id,)).fetchone()
            if old:
                if old['spec'] != spec:
                    raise ValueError("Task ID already exists with a different specification")
                return False
            self.db.execute("INSERT INTO tasks(id,spec,due,created) VALUES(?,?,?,?)", (task_id, spec, due, stamp()))
            self.log(task_id, 'submitted', {"due": due})
        return True

    def claim(self, table, now, lease=240):
        if table not in ('tasks', 'outbox'):
            raise ValueError("Invalid claim table")
        token = uuid.uuid4().hex
        with self.transaction():
            if table == 'tasks':
                row = self.db.execute("SELECT * FROM tasks WHERE execution IN ('pending','running') AND due<=? AND next_try<=? AND lease_until<=? ORDER BY due LIMIT 1", (now, now, now)).fetchone()
                key = 'id'
            else:
                row = self.db.execute("SELECT * FROM outbox WHERE state IN ('pending','retrying') AND next_try<=? AND lease_until<=? ORDER BY rowid LIMIT 1", (now, now)).fetchone()
                key = 'event_id'
            if row is None:
                return None
            self.db.execute(f"UPDATE {table} SET lease_owner=?,lease_until=?,attempts=attempts+1 WHERE {key}=?", (token, now + lease, row[key]))
            if table == 'tasks':
                self.db.execute("UPDATE tasks SET execution='running' WHERE id=?", (row[key],))
            self.log(row['id'] if table == 'tasks' else row['task_id'], 'claimed_' + table, {"token": token})
            return dict(self.db.execute(f"SELECT * FROM {table} WHERE {key}=?", (row[key],)).fetchone())

    def checkpoint(self, row, observation):
        with self.transaction():
            changed = self.db.execute("UPDATE tasks SET observation=? WHERE id=? AND lease_owner=?", (canonical(observation).decode(), row['id'], row['lease_owner'])).rowcount
            if changed != 1:
                raise RuntimeError("Execution lease lost")
            self.log(row['id'], 'observation_checkpointed', {"status": observation.get('status')})

    def finish(self, row, result, successful=True):
        with self.transaction():
            changed = self.db.execute("UPDATE tasks SET execution=?,result=?,lease_owner=NULL,lease_until=0,last_error=NULL WHERE id=? AND lease_owner=?", ('succeeded' if successful else 'failed', canonical(result).decode(), row['id'], row['lease_owner'])).rowcount
            if changed != 1:
                raise RuntimeError("Execution lease lost")
            event_id = row['id'] + ':result:v1'
            payload = canonical({"event_id": event_id, "task_id": row['id'], "kind": "task_result", "owner": json.loads(row["spec"])["owner"], "result": result}).decode()
            self.db.execute("INSERT INTO outbox(event_id,task_id,payload) VALUES(?,?,?)", (event_id, row['id'], payload))
            self.log(row['id'], 'execution_finished_outbox_committed', {"successful": successful, "event_id": event_id})

    def status(self, task_id):
        t = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if t is None:
            raise KeyError(task_id)
        o = self.db.execute("SELECT * FROM outbox WHERE task_id=?", (task_id,)).fetchone()
        state = 'EXECUTION_PENDING'
        if o:
            state = ('COMPLETED' if t['execution'] == 'succeeded' else 'FAILED_REPORTED') if o['state'] == 'delivered' else ('DELIVERY_BLOCKED' if o['state'] == 'blocked' else 'AWAITING_DELIVERY')
        return {"task_id": task_id, "owner": json.loads(t["spec"])["owner"], "state": state, "execution": t['execution'], "execution_attempts": t['attempts'], "result": json.loads(t['result']) if t['result'] else None, "delivery": dict(o) if o else None}


class Engine:
    def __init__(self, store, agent, network, webhook_secret, max_attempts=5, retry_base=2):
        if not webhook_secret or len(webhook_secret) < 16:
            raise ValueError("Webhook secret must be at least 16 characters")
        self.store, self.agent, self.net, self.secret = store, agent, network, webhook_secret
        self.max_attempts, self.retry_base = max_attempts, retry_base

    def execute_one(self, now=None):
        now = time.time() if now is None else now
        row = self.store.claim('tasks', now)
        if not row:
            return False
        spec = json.loads(row['spec'])
        try:
            observation = json.loads(row['observation']) if row['observation'] else None
            if observation is None:
                decision = self.agent.decide(spec, None)
                if decision.get('action') != 'inspect':
                    raise ValueError("Agent must request inspect before report")
                try:
                    status, headers, body = self.net.request('GET', spec['target'])
                    observation = {"observed_at": stamp(), "status": status, "body_sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
                except PolicyError:
                    raise
                except (OSError, http.client.HTTPException) as exc:
                    observation = {"observed_at": stamp(), "status": None, "error": type(exc).__name__}
                self.store.checkpoint(row, observation)
            decision = self.agent.decide(spec, observation)
            summary = decision.get('summary')
            if decision.get('action') != 'report' or not isinstance(summary, str) or not summary.strip() or len(summary) > 4000:
                raise ValueError("Agent must produce a bounded report")
            result = {"verdict": 'PASS' if observation['status'] == spec['expected'] else 'FAIL', "expected": spec['expected'], "observation": observation, "agent_summary": summary, "reported_at": stamp()}
            self.store.finish(row, result)
        except Exception as exc:
            # No response body, URL, authorization header or model text enters the error log.
            with self.store.transaction():
                if row['attempts'] >= self.max_attempts:
                    # finish() owns a transaction, so handle exhaustion outside this transaction.
                    exhausted = True
                else:
                    exhausted = False
                    self.store.db.execute("UPDATE tasks SET execution='pending',next_try=?,lease_owner=NULL,lease_until=0,last_error=? WHERE id=? AND lease_owner=?", (now + self.retry_base * 2 ** (row['attempts'] - 1), type(exc).__name__, row['id'], row['lease_owner']))
                    self.store.log(row['id'], 'execution_retry', {"error": type(exc).__name__})
            if exhausted:
                self.store.finish(row, {"verdict": "AGENT_ERROR", "error": type(exc).__name__, "reported_at": stamp()}, successful=False)
        return True

    def deliver_one(self, now=None):
        now = time.time() if now is None else now
        row = self.store.claim('outbox', now)
        if not row:
            return False
        spec = json.loads(self.store.db.execute("SELECT spec FROM tasks WHERE id=?", (row['task_id'],)).fetchone()['spec'])
        body = row['payload'].encode()
        timestamp = str(int(time.time()))
        headers = {"Content-Type": "application/json", "Idempotency-Key": row['event_id'], "X-Taskloop-Time": timestamp, "X-Taskloop-Signature": sign(self.secret, timestamp.encode() + b'.' + body)}
        try:
            code, response_headers, response = self.net.request('POST', spec['webhook'], data=body, headers=headers)
            if not 200 <= code < 300:
                raise ValueError("Webhook rejected request")
            expected_signature = sign(self.secret, response)
            if not hmac.compare_digest(response_headers.get('x-taskloop-signature', ''), expected_signature):
                raise ValueError("Invalid receipt signature")
            receipt = json.loads(response)
            if receipt.get('accepted') is not True or receipt.get('event_id') != row['event_id'] or receipt.get('payload_sha256') != hashlib.sha256(body).hexdigest() or not isinstance(receipt.get('receipt_id'), str) or not receipt['receipt_id']:
                raise ValueError("Receipt is not bound to this event and payload")
            with self.store.transaction():
                changed = self.store.db.execute("UPDATE outbox SET state='delivered',receipt=?,lease_owner=NULL,lease_until=0,last_error=NULL WHERE event_id=? AND lease_owner=?", (canonical(receipt).decode(), row['event_id'], row['lease_owner'])).rowcount
                if changed != 1:
                    raise RuntimeError("Delivery lease lost")
                self.store.log(row['task_id'], 'delivery_acknowledged', {"receipt_id": receipt['receipt_id']})
        except Exception as exc:
            with self.store.transaction():
                state = 'blocked' if row['attempts'] >= self.max_attempts else 'retrying'
                changed = self.store.db.execute("UPDATE outbox SET state=?,next_try=?,lease_owner=NULL,lease_until=0,last_error=? WHERE event_id=? AND lease_owner=?", (state, now + self.retry_base * 2 ** (row['attempts'] - 1), type(exc).__name__, row['event_id'], row['lease_owner'])).rowcount
                if changed:
                    self.store.log(row['task_id'], 'delivery_' + state, {"error": type(exc).__name__})
        return True

    def tick(self):
        return {"execution_claimed": self.execute_one(), "delivery_claimed": self.deliver_one()}
