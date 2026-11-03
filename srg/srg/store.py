import sqlite3, threading, json, time
class Store:
    def __init__(s, path=":memory:"):
        s.db = sqlite3.connect(path, check_same_thread=False); s.db.row_factory = sqlite3.Row
        s.lock = threading.Lock()
        s.db.executescript("""
        create table if not exists events(id integer primary key, platform text, event_id text, account text, sender text,
          kind text, reply_ref text, text text, status text, decided_by text, decision text, reply text, rule_version int, sent_message_id text,
          attempts int default 0, send_host text, error text, created real, updated real, unique(platform,event_id));
        create table if not exists audit(id integer primary key, event_pk int, ts real, step text, detail text);
        create table if not exists settings(k text primary key, v text);
        create table if not exists rules(version integer primary key, body text, ts real);
        """)
    def q(s, sql, a=()):
        with s.lock:
            cur = s.db.execute(sql, a); s.db.commit(); return cur
    def rows(s, sql, a=()):
        with s.lock:
            return [dict(r) for r in s.db.execute(sql, a).fetchall()]
    def log(s, pk, step, detail=""):
        s.q("insert into audit(event_pk,ts,step,detail) values(?,?,?,?)", (pk, time.time(), step, detail if isinstance(detail,str) else json.dumps(detail, ensure_ascii=False)))
    def get_setting(s, k, d=None):
        r = s.rows("select v from settings where k=?", (k,)); return json.loads(r[0]["v"]) if r else d
    def set_setting(s, k, v): s.q("insert or replace into settings values(?,?)", (k, json.dumps(v)))
    def add_rules(s, body):
        v = (s.rows("select max(version) m from rules")[0]["m"] or 0) + 1
        s.q("insert into rules values(?,?,?)", (v, json.dumps(body, ensure_ascii=False), time.time())); return v
    def latest_rules(s):
        r = s.rows("select * from rules order by version desc limit 1")
        return (r[0]["version"], json.loads(r[0]["body"])) if r else (0, {})
