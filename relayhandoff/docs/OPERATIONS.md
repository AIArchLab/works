# Launch, Operations, and Deployment

From the repo root, enter `relayhandoff/` first. All commands below use it as the working directory.

## Start with one command

Python 3.10+ (standard library only, no pip install):

```sh
python launch.py
```

On Windows, if the environment uses `py`: `py launch.py`. Linux/macOS commonly use `python3 launch.py`.

This starts the Broker on loopback, creates local-only keys and SQLite, and opens the console. On first launch the key is handed to the page memory via URL fragment and the fragment is cleared immediately; it never enters an HTTP request or localStorage. Do not share this launch URL. Without a desktop environment use `python launch.py --no-browser`; credentials live in `.runtime/keys.json`.

## A real cross-runtime demo

Also requires Node.js 18+:

```sh
python demo.py
```

Not a mock: Python writes a checkpoint and a UTF-8 attachment over HTTP, the Broker archives and freezes the old owner, a standalone Node.js process reads the bundle, verifies SHA-256 and attachments, claims, ACKs, then writes under a new fencing epoch. Finally it tries to overwrite with the old token and confirms rejection. Produces `demo_receipt.json`, containing no credentials.

## Operating the console

Create a task, acquire a lease, write a checkpoint, then archive and hand off. The taker uses their own scoped key and presses take over, verify, ACK on the same Task ID. You can read the task list and audits, and cancel unfinished handoffs.

The console is not a commercial-grade UI verified by browser automation; this version's HTTP pages and API are verified, while click interactions still await browser acceptance.

## Deployment

For a real service use `server.py`, injecting scoped credential JSON via `RH_KEYS`; never commit real keys:

```sh
python server.py --host 127.0.0.1 --port 8787 --db /your/private/path/state.db
```

`RH_KEYS` format: `{"random secret of at least 32 characters":{"tenant":"customer id","actor":"executor id","role":"worker"}}`. Production keys should be generated with cryptographic randomness; never use the example string as a key.

A Dockerfile / compose.yaml is included, but this environment has no Docker, so **container execution is not yet verified**. External exposure requires a TLS reverse proxy, connection and body-read timeouts, rate limits, backups, and network access controls first. The built-in Python HTTP server is for local or controlled pilot use only; do not expose it directly to the Internet.

## Acceptance

```sh
python tests/test_e2e.py
```

See `ACCEPTANCE.md` and `test_report.json` for details. `PROTOCOL.md` is the adapter contract; `openapi.json` provides the machine-readable API definition.
