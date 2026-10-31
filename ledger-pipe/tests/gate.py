#!/usr/bin/env python3
"""宣稱閘門：兩套測試全綠才允許對外宣稱通過。任一紅即 CLAIM_BLOCKED。"""
import subprocess, sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
res = {}
for name, path in (("adjacent", "tests/run_tests.py"), ("adversarial", "tests/adversarial.py"), ("xlsx", "tests/xlsx_tests.py")):
    p = subprocess.run([sys.executable, os.path.join(ROOT, path)], capture_output=True, text=True)
    line = [l for l in p.stdout.splitlines() if l.startswith("RESULT")] or ["RESULT n/a"]
    res[name] = (p.returncode, line[0])
    print(f"[{name}] exit={p.returncode} {line[0]}")
ok = all(rc == 0 for rc, _ in res.values())
print("=" * 52)
print("CLAIM_ALLOWED" if ok else "CLAIM_BLOCKED")
sys.exit(0 if ok else 1)
