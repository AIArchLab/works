#!/usr/bin/env python3
"""對抗測試 v0.2：以「買方會怎麼弄壞它」為題，不是以作者會不會寫為題。"""
import csv, io, json, os, shutil, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "data", "2026-09")
B08 = os.path.join(ROOT, "data", "2026-08")
R = []

def run(data, out, period=None, check=True):
    cmd = [sys.executable, os.path.join(ROOT, "pipeline.py"), "--data", data,
           "--schema", os.path.join(ROOT, "schema.json"), "--out", out]
    if period: cmd += ["--period", period]
    return subprocess.run(cmd, capture_output=True, text=True)

def case(name, mutate=None, expect=0, must=None, seed=None, seed_period=None, period="2026-09"):
    tmp = tempfile.mkdtemp(prefix="adv-")
    d = os.path.join(tmp, "data")
    shutil.copytree(seed or BASE, d)
    out = os.path.join(tmp, "out")
    if seed_period: run(d, out, seed_period)
    if mutate: mutate(d)
    t0 = time.time()
    p = run(d, out, period)
    dur = time.time() - t0
    blob = p.stdout + p.stderr
    ok = p.returncode == expect
    note = f"exit={p.returncode} {dur:.2f}s"
    if ok and must:
        ok = must in blob or (os.path.exists(os.path.join(out, "report.md")) and must in open(os.path.join(out, "report.md"), encoding="utf-8").read())
        note += f" | 需含 {must!r}"
    R.append((name, ok, note, blob.strip().splitlines()[:2]))
    shutil.rmtree(tmp, ignore_errors=True)
    return tmp

def enc_cp950(d):
    p = os.path.join(d, "premium.csv")
    txt = open(p, encoding="utf-8").read()
    open(p, "w", encoding="cp950", errors="strict").write(txt)

def header_space(d):
    p = os.path.join(d, "premium.csv")
    rows = list(csv.reader(open(p, encoding="utf-8")))
    rows[0] = [h + " " for h in rows[0]]
    csv.writer(open(p, "w", newline="", encoding="utf-8")).writerows(rows)

def header_bom(d):
    p = os.path.join(d, "claims.csv")
    txt = open(p, encoding="utf-8").read()
    open(p, "w", encoding="utf-8-sig").write(txt)

def na_value(d):
    rows = list(csv.reader(open(os.path.join(d, "premium.csv"), encoding="utf-8")))
    rows[3][2] = "NA"
    csv.writer(open(os.path.join(d, "premium.csv"), "w", newline="", encoding="utf-8")).writerows(rows)

def dash_value(d):
    rows = list(csv.reader(open(os.path.join(d, "claims.csv"), encoding="utf-8")))
    rows[2][2] = "-"
    csv.writer(open(os.path.join(d, "claims.csv"), "w", newline="", encoding="utf-8")).writerows(rows)

def big_number(d):
    rows = list(csv.reader(open(os.path.join(d, "premium.csv"), encoding="utf-8")))
    rows[3][2] = "1000000000000000"
    csv.writer(open(os.path.join(d, "premium.csv"), "w", newline="", encoding="utf-8")).writerows(rows)

def swapped_cols(d):
    p = os.path.join(d, "premium.csv")
    rows = list(csv.reader(open(p, encoding="utf-8")))
    idx = [rows[0].index(c) for c in rows[0]][::-1]
    rows = [[r[i] for i in idx] for r in rows]
    csv.writer(open(p, "w", newline="", encoding="utf-8")).writerows(rows)

def big_file(d):
    p = os.path.join(d, "premium.csv")
    rows = list(csv.reader(open(p, encoding="utf-8")))
    head, body = rows[0], rows[1:]
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(head)
        for i in range(10000):
            src = body[i % len(body)]
            w.writerow([f"P{i:07d}", src[1], src[2], src[3]])

def dup_header(d):
    p = os.path.join(d, "premium.csv")
    rows = list(csv.reader(open(p, encoding="utf-8")))
    rows[0][1] = rows[0][2]
    csv.writer(open(p, "w", newline="", encoding="utf-8")).writerows(rows)

def empty_file(d):
    p = os.path.join(d, "claims.csv")
    rows = list(csv.reader(open(p, encoding="utf-8")))
    csv.writer(open(p, "w", newline="", encoding="utf-8")).writerow(rows[0])

case("01 乾淨資料＋相鄰前期（2026-09 對 2026-08）", expect=0, must="與 2026-08 差異", seed=B08, seed_period="2026-08")
case("02 CP950 編碼（Excel 台灣預設）", enc_cp950, expect=0, must="OK period=")
case("03 標頭帶尾隨空白", header_space, expect=0, must="OK period=")
case("04 UTF-8 BOM 標頭", header_bom, expect=0, must="OK period=")
case("05 假空值 NA", na_value, expect=2, must="假空值")
case("06 假空值 -", dash_value, expect=2, must="假空值")
case("07 大數 10^15", big_number, expect=0, must="OK period=")
case("08 欄位順序全反轉", swapped_cols, expect=0, must="OK period=")
case("09 10,000 列效能（<5 秒）", big_file, expect=0, must="OK period=")
case("10 標頭重複欄位", dup_header, expect=2, must="標頭重複")
case("11 來源只有標頭無資料列", empty_file, expect=2, must="無資料列")

# 12 期間時空錯置：只有 2026-08 快照，跑 2026-10，必須「不比」而不是拿 08 當前期
case("12 跳期：只有 08 快照，跑 10 月不得拿 08 當前一期", expect=0,
     must="不做差異比對", seed=B08, seed_period="2026-08", period="2026-10")

def rerun_twice():
    tmp = tempfile.mkdtemp(prefix="adv-")
    d = os.path.join(tmp, "data"); shutil.copytree(BASE, d); out = os.path.join(tmp, "out")
    p1 = run(d, out, "2026-09"); p2 = run(d, out, "2026-09")
    snaps = sorted(os.listdir(os.path.join(out, "snapshots")))
    audit = open(os.path.join(out, "audit.log"), encoding="utf-8").read().strip().splitlines()
    ok = p1.returncode == 0 and p2.returncode == 0 and len(snaps) == 2 and len(audit) == 2
    R.append(("13 同期重跑兩次：快照保留兩份、audit 兩行（不滅證）", ok,
              f"snapshots={len(snaps)} audit={len(audit)}", []))
    shutil.rmtree(tmp, ignore_errors=True)
rerun_twice()

def path_with_space():
    tmp = tempfile.mkdtemp(prefix="adv-")
    d = os.path.join(tmp, "我的 資料夾"); shutil.copytree(BASE, d); out = os.path.join(tmp, "輸 出")
    p = run(d, out, "2026-09")
    R.append(("14 路徑含空格與中文", p.returncode == 0, f"exit={p.returncode}", []))
    shutil.rmtree(tmp, ignore_errors=True)
path_with_space()

def stale_report_test():
    import tempfile, shutil, os, subprocess, sys, csv
    tmp = tempfile.mkdtemp(prefix="adv-")
    d = os.path.join(tmp, "data"); shutil.copytree(BASE, d); out = os.path.join(tmp, "out")
    subprocess.run([sys.executable, os.path.join(ROOT, "pipeline.py"), "--data", d, "--out", out,
                    "--period", "2026-09"], capture_output=True, text=True)
    ok1 = os.path.exists(os.path.join(out, "report.md"))
    rows = list(csv.reader(open(os.path.join(d, "claims.csv"), encoding="utf-8")))
    rows[3][2] = "12O,000"
    csv.writer(open(os.path.join(d, "claims.csv"), "w", newline="", encoding="utf-8")).writerows(rows)
    p = subprocess.run([sys.executable, os.path.join(ROOT, "pipeline.py"), "--data", d, "--out", out,
                        "--period", "2026-09"], capture_output=True, text=True)
    stale = os.path.exists(os.path.join(out, "report.md")) or os.path.exists(os.path.join(out, "report.csv"))
    latest = os.path.join(out, "LATEST.json")
    status = ""
    if os.path.exists(latest):
        import json as _j
        status = _j.load(open(latest, encoding="utf-8")).get("status", "")
    ok = ok1 and p.returncode == 2 and (not stale) and status == "failed"
    R.append(("15 失敗重跑同目錄：舊報表必須消失、LATEST 標 failed", ok,
              f"first_ok={ok1} exit={p.returncode} stale={stale} status={status}", []))
    shutil.rmtree(tmp, ignore_errors=True)
stale_report_test()

passed = sum(1 for _, ok, _, _ in R if ok)
print("=" * 74)
for name, ok, note, head in R:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  [{note}]")
    for h in head: print(f"        {h}")
print("=" * 74)
print(f"RESULT {passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
