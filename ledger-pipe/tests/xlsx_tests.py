#!/usr/bin/env python3
"""xlsx 直讀測試：不裝 openpyxl，用標準庫自製讀寫器驗證。"""
import csv, os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
from xlsxlite import write_xlsx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "2026-09")
R = []

def make(dest, names=("premium", "claims", "commission"), ext=".xlsx", **kw):
    os.makedirs(dest, exist_ok=True)
    for f in names:
        rows = [list(r) for r in csv.reader(open(os.path.join(SRC, f + ".csv"), encoding="utf-8"))]
        write_xlsx(os.path.join(dest, f + ext), rows, **kw)

def run(d, out, period="2026-09"):
    return subprocess.run([sys.executable, os.path.join(ROOT, "pipeline.py"), "--data", d,
                           "--schema", os.path.join(ROOT, "schema.json"), "--out", out,
                           "--period", period], capture_output=True, text=True)

def record(name, ok, detail):
    R.append((name, ok, detail))

def case(name, build, expect=0, must=None):
    tmp = tempfile.mkdtemp(prefix="xl-")
    d = os.path.join(tmp, "data"); out = os.path.join(tmp, "out")
    build(d)
    p = run(d, out)
    blob = p.stdout + p.stderr
    ok = p.returncode == expect
    note = f"exit={p.returncode}"
    if ok and must:
        ok = must in blob
        note += f" | 需含 {must!r}"
    record(name, ok, note + " | " + (blob.strip().splitlines()[0] if blob.strip() else ""))
    shutil.rmtree(tmp, ignore_errors=True)

case("01 xlsx（sharedStrings）與 CSV 同數字", lambda d: make(d, shared=True), 0, "premium=2900664")
case("02 xlsx（inlineStr）與 CSV 同數字", lambda d: make(d, shared=False), 0, "premium=2900664")
case("03 xlsx 日期以序列值儲存（numFmt 14）", lambda d: make(d, shared=True, date_cols=(3,)), 0, "premium=2900664")

def missing_col(d):
    make(d, shared=True)
    rows = [list(r) for r in csv.reader(open(os.path.join(SRC, "premium.csv"), encoding="utf-8"))]
    rows[0][2] = "保險費"
    write_xlsx(os.path.join(d, "premium.xlsx"), rows, shared=True)
case("04 xlsx 缺必要欄位", missing_col, 2, "缺少必要欄位")

def na_cell(d):
    make(d, shared=True)
    rows = [list(r) for r in csv.reader(open(os.path.join(SRC, "claims.csv"), encoding="utf-8"))]
    rows[2][2] = "NA"
    write_xlsx(os.path.join(d, "claims.xlsx"), rows, shared=True)
case("05 xlsx 假空值 NA", na_cell, 2, "假空值")

def legacy_xls(d):
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "premium.xls"), "wb").write(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 128)
case("06 舊版 .xls 明確拒收並給指示", legacy_xls, 2, "舊版 .xls 不支援")

def stem_fallback(d):
    make(d, names=("premium",), shared=True)
    for f in ("claims", "commission"):
        shutil.copy(os.path.join(SRC, f + ".csv"), os.path.join(d, f + ".csv"))
case("07 schema 寫 .csv 但只有 .xlsx（互換解析）", stem_fallback, 0, "premium=2900664")

def trailing_blanks(d):
    make(d, shared=True)
    rows = [list(r) for r in csv.reader(open(os.path.join(SRC, "premium.csv"), encoding="utf-8"))]
    rows += [["", "", "", ""], ["", "", "", ""]]
    rows = [r + ["", ""] for r in rows]
    write_xlsx(os.path.join(d, "premium.xlsx"), rows, shared=True)
case("08 尾端空白列與空欄自動修剪", trailing_blanks, 0, "premium=2900664")

def corrupt(d):
    os.makedirs(d, exist_ok=True)
    for f in ("premium", "claims", "commission"):
        shutil.copy(os.path.join(SRC, f + ".csv"), os.path.join(d, f + ".csv"))
    open(os.path.join(d, "premium.xlsx"), "wb").write(b"not a zip at all")
    os.remove(os.path.join(d, "premium.csv"))
case("09 損壞的 .xlsx 給出可讀錯誤", corrupt, 2, "xlsx 解析失敗")

def mixed(d):
    make(d, names=("premium",), shared=True)
    make(d, names=("claims",), shared=False)
    shutil.copy(os.path.join(SRC, "commission.csv"), os.path.join(d, "commission.csv"))
case("10 三個來源混合格式（xlsx/xlsx/csv）", mixed, 0, "premium=2900664")

passed = sum(1 for _, ok, _ in R if ok)
print("=" * 74)
for name, ok, detail in R:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  [{detail}]")
print("=" * 74)
print(f"RESULT {passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)
