import argparse, datetime, json, os, time
from . import __version__
from .core import Store, Engine, Network
from .agents import RemoteAgent


def main():
    parser = argparse.ArgumentParser(description='Durable agent HTTP checks with signed delivery receipts')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--db', default='taskloop.sqlite3')
    sub = parser.add_subparsers(dest='command', required=True)
    submit = sub.add_parser('submit')
    for name in ('id', 'target', 'webhook', 'due'):
        submit.add_argument('--' + name, required=True)
    submit.add_argument('--expected', type=int, default=200)
    submit.add_argument('--owner', default='local-agent')
    work = sub.add_parser('worker')
    work.add_argument('--allow-host', action='append', required=True)
    work.add_argument('--allow-local-demo', action='store_true')
    work.add_argument('--once', action='store_true')
    work.add_argument('--poll', type=float, default=1)
    status = sub.add_parser('status'); status.add_argument('id')
    events = sub.add_parser('events'); events.add_argument('id')
    receiver = sub.add_parser('receiver')
    receiver.add_argument('--host', default='127.0.0.1'); receiver.add_argument('--port', type=int, default=8765)
    receiver.add_argument('--fail-first', type=int, default=0)
    x = parser.parse_args()
    if x.command == 'receiver':
        from .receiver import server
        server(x.host, x.port, x.db, os.environ['TASKLOOP_WEBHOOK_SECRET'], x.fail_first).serve_forever(); return
    store = Store(x.db)
    if x.command == 'submit':
        due = datetime.datetime.fromisoformat(x.due.replace('Z', '+00:00'))
        if due.tzinfo is None:
            parser.error('--due must include an explicit timezone')
        created = store.submit(x.id, x.target, x.webhook, due.timestamp(), x.expected, x.owner)
        print(json.dumps({'task_id': x.id, 'created': created})); return
    if x.command == 'status':
        print(json.dumps(store.status(x.id), ensure_ascii=False, indent=2)); return
    if x.command == 'events':
        print(json.dumps([dict(r) for r in store.db.execute('SELECT * FROM audit WHERE task_id=? ORDER BY n', (x.id,))], indent=2)); return
    if x.poll <= 0:
        parser.error('--poll must be positive')
    engine = Engine(store, RemoteAgent(), Network(x.allow_host, x.allow_local_demo), os.environ['TASKLOOP_WEBHOOK_SECRET'])
    while True:
        result = engine.tick()
        if x.once:
            print(json.dumps(result)); break
        time.sleep(x.poll)


if __name__ == '__main__':
    main()
