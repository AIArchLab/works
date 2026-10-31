#!/usr/bin/env python3
"""月報管線 v0.2 — 來源契約 + 相鄰前期差異 + 不可覆寫快照。
v0.1 三大致命缺陷修法：
  1) 期間不再用字串排序，改用 (年,月) 解析；只與「相鄰前一期」比對，不相鄰則明確聲明不比。
  2) 編碼自動偵測（utf-8-sig/utf-8/cp950/big5）、標頭正規化、假空值（NA/-/null）視為空。
  3) 快照 append-only（period + run_id），並寫 audit.log；永不覆寫既有快照。
"""
import argparse, csv, hashlib, io, json, os, re, sys
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
from xlsxlite import read_xlsx  # noqa: E402

FW = str.maketrans({chr(0xFF10 + i): str(i) for i in range(10)} |
                   {chr(0xFF0E): ".", "，": ",", "－": "-", "−": "-", "\u3000": " "})
MONEY_RE = re.compile(r"^-?\d+(\.\d+)?$")
EMPTY = {"", "na", "n/a", "-", "—", "null", "none", "nil", "nan"}

def is_empty(v):
    return v is None or str(v).strip().translate(FW).strip().lower() in EMPTY

def parse_money(s):
    v = str(s).strip().translate(FW).replace(",", "").replace(" ", "").replace("$", "").replace("NT", "").strip()
    if not MONEY_RE.match(v):
        raise ValueError(f"金額格式無法解析：'{s}'")
    return Decimal(v)

def parse_date(s):
    v = str(s).strip().translate(FW)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"日期格式無法解析：'{s}'")

def parse_ratio(s):
    raw = str(s).strip().translate(FW)
    pct = raw.endswith("%")
    v = raw.rstrip("%").strip()
    if not MONEY_RE.match(v):
        raise ValueError(f"比率格式無法解析：'{s}'")
    x = Decimal(v) / (Decimal(100) if pct else Decimal(1))
    if x < 0 or x > 1:
        raise ValueError(f"比率超出 0–1（未帶 % 時須為小數）：'{s}'")
    return x

PARSERS = {"money": parse_money, "date": parse_date, "ratio": parse_ratio}
ENCODINGS = ("utf-8-sig", "utf-8", "cp950", "big5")

def norm_header(h):
    return str(h).replace("\ufeff", "").strip().replace("\u3000", " ")

def _rows_to_dicts(rows):
    if not rows:
        return [], []
    header = [norm_header(h) for h in rows[0]]
    dups = {h for h in header if header.count(h) > 1}
    if dups:
        raise ValueError(f"標頭重複欄位：{sorted(dups)}")
    out = []
    for r in rows[1:]:
        vals = [("" if c is None else str(c)) for c in r]
        if not any(v.strip() for v in vals):
            continue
        out.append(dict(zip(header, vals)))
    return header, out

def read_table(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xls":
        raise ValueError("舊版 .xls 不支援（BIFF 格式），請另存為 .xlsx 或 .csv")
    if ext == ".xlsx":
        try:
            rows = read_xlsx(path)
        except ValueError as e:
            raise ValueError(f"xlsx 解析失敗：{e}")
        except Exception as e:
            raise ValueError(f"xlsx 解析失敗：{type(e).__name__}: {e}")
        return _rows_to_dicts(rows)
    last = None
    for enc in ENCODINGS:
        try:
            with open(path, newline="", encoding=enc) as f:
                raw = f.read()
            break
        except UnicodeDecodeError as e:
            last = e
    else:
        raise ValueError(f"無法以 {ENCODINGS} 解碼：{last}")
    rows = [r for r in csv.reader(io.StringIO(raw))]
    return _rows_to_dicts(rows)

def resolve_source(data_dir, spec):
    """允許 .xlsx/.csv 互換：schema 寫 premium.csv，目錄裡只有 premium.xlsx 也能吃。"""
    base = os.path.join(data_dir, spec["file"])
    if os.path.exists(base):
        return base
    stem, _ = os.path.splitext(base)
    for ext in (".xlsx", ".csv", ".xls"):
        cand = stem + ext
        if os.path.exists(cand):
            return cand
    return None

def load_source(key, spec, data_dir):
    path = resolve_source(data_dir, spec)
    if path is None:
        stem = os.path.splitext(spec["file"])[0]
        return [], [{"source": key, "label": spec["label"], "line": 0, "column": "-",
                     "reason": f"檔案不存在：{spec['file']}（已嘗試 {stem}.xlsx / {stem}.csv / {stem}.xls）"}]
    try:
        header, rows = read_table(path)
    except ValueError as e:
        return [], [{"source": key, "label": spec["label"], "line": 1, "column": "-", "reason": str(e)}]
    missing = [c for c in spec["required"] if c not in header]
    if missing:
        return [], [{"source": key, "label": spec["label"], "line": 1, "column": ",".join(missing),
                     "reason": "缺少必要欄位"}]
    if not rows:
        return [], [{"source": key, "label": spec["label"], "line": 2, "column": "-", "reason": "來源無資料列"}]
    errs, good, seen = [], [], {}
    for ln, raw in enumerate(rows, start=2):
        rec, bad = {"_line": ln}, False
        for col in spec["required"]:
            if is_empty(raw.get(col)):
                errs.append({"source": key, "label": spec["label"], "line": ln, "column": col,
                             "reason": "必填欄位為空或有假空值（NA/-/null）"}); bad = True
        for col, typ in spec.get("types", {}).items():
            if is_empty(raw.get(col)):
                continue
            try:
                rec[col] = PARSERS[typ](raw[col])
            except ValueError as e:
                errs.append({"source": key, "label": spec["label"], "line": ln, "column": col,
                             "reason": str(e)}); bad = True
        for col in spec.get("non_negative", []):
            if isinstance(rec.get(col), Decimal) and rec[col] < 0:
                errs.append({"source": key, "label": spec["label"], "line": ln, "column": col,
                             "reason": f"不得為負數：{raw.get(col)}"}); bad = True
        for c in list(raw.keys()):
            rec.setdefault(c, (raw.get(c) or "").strip())
        keys = spec.get("keys", [])
        kt = "/".join(str(rec.get(k)) for k in keys) if keys else ""
        if kt:
            if kt in seen:
                errs.append({"source": key, "label": spec["label"], "line": ln, "column": "+".join(keys),
                             "reason": f"主鍵重複（首次出現於第 {seen[kt]} 列）：{kt}"}); bad = True
            else:
                seen[kt] = ln
        if not bad:
            good.append(rec)
    return good, errs

def parse_period(p):
    m = re.match(r"^(\d{4})[-_/]?(\d{1,2})$", str(p).strip())
    if not m:
        raise ValueError(f"期間格式無法解析：{p}（需 2026-09 或 2026-9）")
    y, mo = int(m.group(1)), int(m.group(2))
    if not 1 <= mo <= 12:
        raise ValueError(f"期間月份不合法：{p}")
    return (y, mo)

def prev_period(ym):
    y, m = ym
    return (y - 1, 12) if m == 1 else (y, m - 1)

def plabel(ym):
    return f"{ym[0]}-{ym[1]:02d}"

def agg(rows, key, val):
    out = {}
    for r in rows:
        out[r[key]] = out.get(r[key], Decimal(0)) + r[val]
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], str(kv[0]))))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--schema", default="schema.json")
    ap.add_argument("--out", default="out")
    ap.add_argument("--period", default=None)
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args()
    schema = json.load(open(a.schema, encoding="utf-8"))
    period_raw = a.period or os.path.basename(os.path.normpath(a.data))
    try:
        ym = parse_period(period_raw)
    except ValueError as e:
        print(f"PERIOD_INVALID {e}")
        return 3
    period = plabel(ym)
    run_id = a.run_id or datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")

    data, errors = {}, []
    src_hash = {}
    for key, spec in schema["sources"].items():
        rows, errs = load_source(key, spec, a.data)
        data[key], errors = rows, errors + errs
        rp = resolve_source(a.data, spec)
        src_hash[key] = (hashlib.sha256(open(rp, "rb").read()).hexdigest()[:16] if rp else None)

    os.makedirs(a.out, exist_ok=True)
    if errors:
        # 失敗語意：不得留下任何上一次成功的報表
        for stale in ("report.md", "report.csv"):
            sp = os.path.join(a.out, stale)
            if os.path.exists(sp):
                os.remove(sp)
        json.dump({"run_id": run_id, "period": period, "status": "failed",
                   "errors": len(errors), "created_utc": datetime.utcnow().isoformat() + "Z"},
                  open(os.path.join(a.out, "LATEST.json"), "w", encoding="utf-8"))
        lines = [f"# 驗證失敗：{period}", "",
                 f"共 {len(errors)} 筆錯誤，未產出報表。修正來源後重跑。", "",
                 "| 來源 | 列 | 欄位 | 原因 |", "|---|---|---|---|"]
        lines += [f"| {e['label']} | {e['line']} | {e['column']} | {e['reason']} |" for e in errors]
        open(os.path.join(a.out, "errors.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
        print(f"VALIDATION_FAILED period={period} errors={len(errors)}")
        for e in errors[:10]:
            print(f"  {e['label']} 第{e['line']}列 [{e['column']}] {e['reason']}")
        return 2

    ep = os.path.join(a.out, "errors.md")
    if os.path.exists(ep):
        os.remove(ep)

    prem = agg(data["premium"], "通路", "保費")
    claims = agg(data["claims"], "類別", "金額")
    comm = {}
    for r in data["commission"]:
        comm[r["業務員"]] = comm.get(r["業務員"], Decimal(0)) + r["保費"] * r["佣金率"]
    comm = dict(sorted(comm.items(), key=lambda kv: (-kv[1], str(kv[0]))))
    tp, tc, tcm = sum(prem.values(), Decimal(0)), sum(claims.values(), Decimal(0)), sum(comm.values(), Decimal(0))
    net = tp - tc - tcm

    md = [f"# 月報 {period}", "", "## 摘要", "",
          f"- 保費收入：{tp:,}", f"- 理賠支出：{tc:,}", f"- 佣金：{tcm:,}", f"- 淨額：{net:,}",
          "- 來源列數：" + "、".join(f"{schema['sources'][k]['label']} {len(v)}" for k, v in data.items()),
          "", "## 保費收入（依通路）", "", "| 通路 | 金額 |", "|---|---|"]
    md += [f"| {k} | {v:,} |" for k, v in prem.items()]
    md += ["", "## 理賠支出（依類別）", "", "| 類別 | 金額 |", "|---|---|"]
    md += [f"| {k} | {v:,} |" for k, v in claims.items()]
    md += ["", "## 佣金（依業務員）", "", "| 業務員 | 佣金 |", "|---|---|"]
    md += [f"| {k} | {v:,} |" for k, v in comm.items()]

    snapdir = os.path.join(a.out, "snapshots"); os.makedirs(snapdir, exist_ok=True)
    py = prev_period(ym)
    cand = []
    for f in os.listdir(snapdir):
        if not f.endswith(".json"):
            continue
        stem = f[:-5]
        try:
            cym = parse_period(stem.split("__")[0])
        except ValueError:
            continue
        if cym == py:
            cand.append((os.path.getmtime(os.path.join(snapdir, f)), f))
    if cand:
        prev = json.load(open(os.path.join(snapdir, sorted(cand)[-1][1]), encoding="utf-8"))
        def pct(x, y):
            x, y = Decimal(x), Decimal(y)
            return "n/a" if y == 0 else f"{(x - y) / y * 100:+.1f}%"
        md += ["", f"## 與 {prev['period']} 差異（相鄰前期）", "",
               "| 項目 | 本期 | 前期 | 差額 | 變動 |", "|---|---|---|---|---|"]
        for label, cur, old in (("保費收入", tp, prev["premium"]), ("理賠支出", tc, prev["claims"]),
                                ("佣金", tcm, prev["commission"]), ("淨額", net, prev["net"])):
            d = Decimal(cur) - Decimal(old)
            md.append(f"| {label} | {Decimal(cur):,} | {Decimal(old):,} | {d:+,} | {pct(cur, old)} |")
        ch = []
        for k in sorted(set(list(prem.keys()) + list(prev["by_channel"].keys()))):
            cur, old = Decimal(prem.get(k, 0)), Decimal(prev["by_channel"].get(k, "0"))
            if cur != old:
                ch.append(f"| {k} | {cur:,} | {old:,} | {cur - old:+,} | {pct(cur, old)} |")
        if ch:
            md += ["", "## 通路變動", "", "| 通路 | 本期 | 前期 | 差額 | 變動 |", "|---|---|---|---|---|"] + ch
    else:
        md += ["", "## 差異報告", "",
               f"**不做差異比對**：找不到相鄰前期 {plabel(py)} 的快照。",
               "（本版規則：只與相鄰前一期比較。跳期比較會產生因果錯置，故不執行。）"]

    out_md = os.path.join(a.out, "report.md")
    tmp = out_md + ".tmp"
    open(tmp, "w", encoding="utf-8").write("\n".join(md) + "\n")
    os.replace(tmp, out_md)
    with open(os.path.join(a.out, "report.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["section", "key", "amount"])
        w.writerow(["summary", "premium", f"{tp:.2f}"]); w.writerow(["summary", "claims", f"{tc:.2f}"])
        w.writerow(["summary", "commission", f"{tcm:.2f}"]); w.writerow(["summary", "net", f"{net:.2f}"])
        for k, v in prem.items(): w.writerow(["premium_by_channel", k, f"{v:.2f}"])
        for k, v in claims.items(): w.writerow(["claims_by_category", k, f"{v:.2f}"])
        for k, v in comm.items(): w.writerow(["commission_by_agent", k, f"{v:.2f}"])

    snap = {"period": period, "run_id": run_id, "created_utc": datetime.utcnow().isoformat() + "Z",
            "premium": str(tp), "claims": str(tc), "commission": str(tcm), "net": str(net),
            "by_channel": {k: str(v) for k, v in prem.items()},
            "source_rows": {k: len(v) for k, v in data.items()},
            "source_sha256_16": src_hash,
            "output_sha256_16": hashlib.sha256(open(out_md, "rb").read()).hexdigest()[:16]}
    snap_path = os.path.join(snapdir, f"{period}__{run_id}.json")
    if os.path.exists(snap_path):
        print(f"SNAPSHOT_EXISTS {snap_path}"); return 4
    json.dump(snap, open(snap_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, "audit.log"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"run_id": run_id, "period": period, "snapshot": os.path.basename(snap_path),
                            "sources": src_hash, "rows": snap["source_rows"],
                            "totals": {"premium": str(tp), "claims": str(tc), "commission": str(tcm), "net": str(net)}},
                           ensure_ascii=False) + "\n")
    json.dump({"run_id": run_id, "period": period, "status": "ok", "snapshot": os.path.basename(snap_path),
               "created_utc": datetime.utcnow().isoformat() + "Z"},
              open(os.path.join(a.out, "LATEST.json"), "w", encoding="utf-8"))
    print(f"OK period={period} run_id={run_id} premium={tp} claims={tc} commission={tcm} net={net}")
    print(f"snapshot={snap_path}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
