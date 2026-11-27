"""Console entry point: `advisor-router serve` and `advisor-router demo`."""
import argparse, os, socket, sys, threading, time


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(args):
    import uvicorn
    if args.rules: os.environ["RULES"] = args.rules
    if args.models: os.environ["MODELS"] = args.models
    if args.log: os.environ["DECISION_LOG"] = args.log
    print(f"advisor-router listening on http://{args.host}:{args.port}  (POST /decide, GET /health)")
    uvicorn.run("advisor.main:app", host=args.host, port=args.port, log_level="warning")


def demo(args):
    """Start a private advisor on a free port, run the sticky-loop demo, print the decision log."""
    import tempfile, uvicorn
    log = os.path.join(tempfile.mkdtemp(prefix="advisor-demo-"), "decisions.jsonl")
    os.environ["DECISION_LOG"] = log
    port = _free_port()
    os.environ["ADVISOR_URL"] = f"http://127.0.0.1:{port}"
    from . import main as app_mod, runtime_client
    runtime_client.ADVISOR = os.environ["ADVISOR_URL"]
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True); t.start()
    for _ in range(100):
        if server.started: break
        time.sleep(0.05)
    else:
        sys.exit("advisor failed to start")
    runtime_client.main()
    server.should_exit = True; t.join(timeout=5)
    print("\n--- decision log (demo) ---")
    print(open(log).read().strip())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="advisor-router",
        description="A model advisor that returns only a model name.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="start the advisor service")
    s.add_argument("--host", default=os.getenv("ADVISOR_HOST", "127.0.0.1"))
    s.add_argument("--port", type=int, default=int(os.getenv("ADVISOR_PORT", "8099")))
    s.add_argument("--rules", help="path to your rules.yaml (default: packaged example)")
    s.add_argument("--models", help="path to your models.yaml (default: packaged example)")
    s.add_argument("--log", help="decision log path (default: ./decisions.jsonl)")
    s.set_defaults(fn=serve)
    d = sub.add_parser("demo", help="run the sticky-loop demo against a temporary advisor")
    d.set_defaults(fn=demo)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
