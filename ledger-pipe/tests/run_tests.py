#!/usr/bin/env python3
"""月報管線 v0.1 驗收測試：乾淨資料要過，壞資料要指名到列與欄。"""
import csv, os, shutil, subprocess, sys, tempfile, filecmp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "data", "2026-09")
RESULTS = []

def run_case(name, mutate=None, expect_code=0, expect_text=None, data_dir=None):
    tmp = tempfile.mkdtemp(prefix="rp-")
    d = os.path.join(tmp, "data"); shutil.copytree(data_dir or BASE, d)
    out = os.path.join(tmp, "out")
    if mutate: mutate(d)
    p = subprocess.run([sys.executable, os.path.join(ROOT, "pipeline.py"),
                        "--data", d, "--schema", os.path.join(ROOT, "schema.json"),
                        "--out", out, "--period", "2026-09"],
                       capture_output=True, text=True)
    blob = p.stdout + p.stderr
    ok = (p.returncode == expect_code)
    detail = f"exit={p.returncode}"
    if ok and expect_text:
        ok = expect_text in blob
        detail += f" | 需含 {expect_text!r}"
    if ok and expect_code == 0:
        ok = os.path.exists(os.path.join(out, "report.md")) and os.path.getsize(os.path.join(out, "report.md")) > 0
        detail += " | report.md 存在且非空"
    if ok and expect_code == 2:
        ok = os.path.exists(os.path.join(out, "errors.md")) and not os.path.exists(os.path.join(out, "report.md"))
        detail += " | errors.md 產生且未產報表"
    RESULTS.append((name, ok, detail, blob.strip().splitlines()[:3]))
    shutil.rmtree(tmp, ignore_errors=True)

def edit_csv(path, fn):
    rows = list(csv.reader(open(path, encoding="utf-8-sig")))
    rows = fn(rows)
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)

def m_missing_col(d):
    def f(rows):
        rows[0][2] = "保險費"
        return rows
    edit_csv(os.path.join(d, "premium.csv"), f)

def m_bad_money(d):
    def f(rows):
        rows[3][2] = "12O,000"
        return rows
    edit_csv(os.path.join(d, "premium.csv"), f)

def m_dup_key(d):
    def f(rows):
        rows[5] = list(rows[4])
        return rows
    edit_csv(os.path.join(d, "premium.csv"), f)

def m_bad_date(d):
    def f(rows):
        rows[6][3] = "2026-09-31"
        return rows
    edit_csv(os.path.join(d, "claims.csv"), f)

def m_empty(d):
    def f(rows):
        rows[2][1] = ""
        return rows
    edit_csv(os.path.join(d, "claims.csv"), f)

def m_negative(d):
    def f(rows):
        rows[4][2] = "-50000"
        return rows
    edit_csv(os.path.join(d, "premium.csv"), f)

def m_ratio_over(d):
    def f(rows):
        rows[1][2] = "1.8"
        return rows
    edit_csv(os.path.join(d, "commission.csv"), f)

def m_fullwidth(d):
    def f(rows):
        rows[2][2] = "１２,０００"
        return rows
    edit_csv(os.path.join(d, "premium.csv"), f)

def m_bom(d):
    path = os.path.join(d, "claims.csv")
    body = open(path, encoding="utf-8").read()
    open(path, "w", encoding="utf-8-sig").write(body)

def m_clean_copy(d):
    pass

run_case("01 乾淨資料（8 月）", expect_code=0, expect_text="OK period=2026-09",
         data_dir=os.path.join(ROOT, "data", "2026-08"))
run_case("02 乾淨資料（9 月）", expect_code=0, expect_text="OK period=2026-09")
run_case("03 缺欄位（保費→保險費）", m_missing_col, 2, "缺少必要欄位")
run_case("04 金額含英文字母 O", m_bad_money, 2, "第4列")
run_case("05 主鍵重複（保單號）", m_dup_key, 2, "主鍵重複")
run_case("06 不存在的日期 2026-09-31", m_bad_date, 2, "日期格式無法解析")
run_case("07 必填欄位空白", m_empty, 2, "必填欄位為空")
run_case("08 負數保費", m_negative, 2, "不得為負數")
run_case("09 佣金率 1.8（未帶 %）", m_ratio_over, 2, "比率超出")
run_case("10 全形數字 １２,０００（應正規化通過）", m_fullwidth, 0, "OK period=2026-09")
run_case("11 UTF-8 BOM 標頭（應通過）", m_bom, 0, "OK period=2026-09")

# 決定性：同一份資料跑兩次，報表須逐 byte 相同
tmp = tempfile.mkdtemp(prefix="rp-det-")
outs = []
for i in (1, 2):
    o = os.path.join(tmp, f"out{i}")
    subprocess.run([sys.executable, os.path.join(ROOT, "pipeline.py"), "--data", BASE,
                    "--schema", os.path.join(ROOT, "schema.json"), "--out", o, "--period", "2026-09"],
                   capture_output=True, text=True)
    outs.append(os.path.join(o, "report.csv"))
same = filecmp.cmp(outs[0], outs[1], shallow=False)
RESULTS.append(("12 決定性：兩次執行報表逐 byte 相同", same, "filecmp 相同" if same else "內容不同", []))
shutil.rmtree(tmp, ignore_errors=True)

passed = sum(1 for _, ok, _, _ in RESULTS if ok)
print("=" * 68)
for name, ok, detail, head in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  [{detail}]")
    for h in head:
        print(f"        {h}")
print("=" * 68)
print(f"RESULT {passed}/{len(RESULTS)} passed")
sys.exit(0 if passed == len(RESULTS) else 1)
