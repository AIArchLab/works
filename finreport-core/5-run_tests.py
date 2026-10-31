#!/usr/bin/env python3
"""FinReport-Core MVP acceptance tests v0.2 (synthetic data). Each run writes to a fresh
output directory; existing results are never overwritten or deleted."""
import csv, json, os, shutil, subprocess, sys, time

TS = time.strftime("%Y%m%d-%H%M%S")
RUN = f"evidence/run-{TS}"
os.makedirs(RUN, exist_ok=True)
CORE = ["python3", "finreport_core.py", "mapping.json"]
ok = True

def check(name, cond, detail=""):
    global ok
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    ok = ok and cond

FA, FB = "fixtures/fixture_A_summary.xlsx", "fixtures/fixture_B_detail.csv"

# T1: happy path end to end (timed)
t0 = time.perf_counter()
r = subprocess.run(CORE + [FA, FB, f"{RUN}/out_summary.xlsx", f"{RUN}/err.csv"],
                   capture_output=True, text=True)
check("T1 happy path exit=0", r.returncode == 0, r.stdout.strip())
dt = time.perf_counter() - t0
check("T1 merge of 1,000 detail rows took", True, f"{dt:.3f}s (measured, this machine)")

# T1b: column-exact match against the answer key
from openpyxl import load_workbook
truth = json.load(open("fixtures/expected_truth.json"))
ws = load_workbook(f"{RUN}/out_summary.xlsx").active
rows = {r_[0]: (r_[1], r_[2], r_[4]) for r_ in ws.iter_rows(min_row=2, values_only=True)}
bad = [a for a, v in truth.items()
       if a not in rows or rows[a][1] != v or abs((rows[a][0] or 0) - v) > 0.005 or rows[a][2] != "OK"]
check("T1 column-exact match (50 agents)", not bad, f"mismatch:{bad[:3]}" if bad else "all match")
total_b = sum(truth.values())
check("T1 detail grand total = 5,003,005", total_b == 5003005, f"computed {total_b:,}")

# T2: missing key blocks
lines = open(FB, encoding="utf-8-sig").read().splitlines()
bad_lines = lines[:]
for i in (1, 2, 3):
    p = bad_lines[i].split(","); p[2] = ""; bad_lines[i] = ",".join(p)
open(f"{RUN}/t2.csv", "w", encoding="utf-8").write("\n".join(bad_lines))
r = subprocess.run(CORE + [FA, f"{RUN}/t2.csv", f"{RUN}/t2_out.xlsx", f"{RUN}/t2_err.csv"],
                   capture_output=True, text=True)
errs = list(csv.reader(open(f"{RUN}/t2_err.csv", encoding="utf-8-sig")))[1:]
check("T2 missing-key blocks, exit=2", r.returncode == 2, r.stdout.strip())
check("T2 error list has exactly the 3 planted rows", len(errs) == 3 and all(e[2] == "missing key (agent_id)" for e in errs),
      f"got {len(errs)}")
check("T2 no summary on block", not os.path.exists(f"{RUN}/t2_out.xlsx"))

# T3: bad date/amount format blocks
bad_lines = lines[:]
p = bad_lines[1].split(","); p[0] = "2026/13/45"; bad_lines[1] = ",".join(p)
p = bad_lines[2].split(","); p[3] = "N/A"; bad_lines[2] = ",".join(p)
open(f"{RUN}/t3.csv", "w", encoding="utf-8").write("\n".join(bad_lines))
r = subprocess.run(CORE + [FA, f"{RUN}/t3.csv", f"{RUN}/t3_out.xlsx", f"{RUN}/t3_err.csv"],
                   capture_output=True, text=True)
errs = list(csv.reader(open(f"{RUN}/t3_err.csv", encoding="utf-8-sig")))[1:]
check("T3 bad-format blocks, exit=2", r.returncode == 2, r.stdout.strip())
check("T3 error list has exactly the 2 planted rows", len(errs) == 2, f"got {len(errs)}: {[e[2] for e in errs]}")

# T4: offline (sockets blocked, still passes)
guard = f"{RUN}/sitecustomize.py"
open(guard, "w").write("import socket\nsocket.socket = None\nsocket.create_connection = None\n")
env = dict(os.environ, PYTHONPATH=RUN)
r = subprocess.run(CORE + [FA, FB, f"{RUN}/t4_out.xlsx", f"{RUN}/t4_err.csv"],
                   capture_output=True, text=True, env=env)
check("T4 exit=0 with sockets blocked (no network dependency)", r.returncode == 0, r.stdout.strip() or r.stderr.strip()[:100])

# T5: existing destination -> refuse, no overwrite (QC defect 1 regression)
r = subprocess.run(CORE + [FA, FB, f"{RUN}/out_summary.xlsx", f"{RUN}/err.csv"],
                   capture_output=True, text=True)
check("T5 existing destination refused, exit=1", r.returncode == 1 and "refused" in r.stdout,
      r.stdout.strip()[:80])
check("T5 old summary not overwritten", os.path.exists(f"{RUN}/out_summary.xlsx"))
r2 = subprocess.run(CORE + [f"{RUN}/t2.csv", FB, f"{RUN}/t5_out.xlsx", f"{RUN}/t2_err.csv"],
                    capture_output=True, text=True)
check("T5 existing error-list path also refused", r2.returncode == 1 and "refused" in r2.stdout)

# T6: duplicate key in A blocks (QC defect 2 regression)
from openpyxl import Workbook
wb = Workbook(); ws = wb.active
ws.append(["Name", "Date", "Agent ID", "Item", "Monthly sales"])
ws.append(["Agent 01", "2026-10-31", "A0001", "Monthly close", 100])
ws.append(["Agent 01", "2026-10-31", "A0001", "Monthly close", 999])
wb.save(f"{RUN}/t6_A.xlsx")
r = subprocess.run(CORE + [f"{RUN}/t6_A.xlsx", FB, f"{RUN}/t6_out.xlsx", f"{RUN}/t6_err.csv"],
                   capture_output=True, text=True)
errs = list(csv.reader(open(f"{RUN}/t6_err.csv", encoding="utf-8-sig")))[1:]
check("T6 duplicate key in A blocks, exit=2", r.returncode == 2, r.stdout.strip())
check("T6 error list names the duplicate key", any(e[2] == "duplicate key (agent_id)" and e[3] == "A0001" for e in errs),
      f"got {[e[2] for e in errs]}")

# T7: nan/inf amounts block (QC defect 3 regression)
bad_lines = lines[:]
p = bad_lines[1].split(","); p[3] = "nan"; bad_lines[1] = ",".join(p)
p = bad_lines[2].split(","); p[3] = "inf"; bad_lines[2] = ",".join(p)
p = bad_lines[3].split(","); p[3] = "-inf"; bad_lines[3] = ",".join(p)
open(f"{RUN}/t7.csv", "w", encoding="utf-8").write("\n".join(bad_lines))
r = subprocess.run(CORE + [FA, f"{RUN}/t7.csv", f"{RUN}/t7_out.xlsx", f"{RUN}/t7_err.csv"],
                   capture_output=True, text=True)
errs = list(csv.reader(open(f"{RUN}/t7_err.csv", encoding="utf-8-sig")))[1:]
check("T7 non-finite amounts block, exit=2", r.returncode == 2, r.stdout.strip())
check("T7 error list has exactly the 3 planted rows", len(errs) == 3, f"got {len(errs)}: {[e[2] for e in errs]}")

print(f"\nOutput dir: {RUN}")
print("ALL PASS" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
