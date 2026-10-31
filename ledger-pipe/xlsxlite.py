#!/usr/bin/env python3
"""xlsxlite — 純標準庫讀寫 .xlsx（不需 openpyxl）。
讀：zipfile + XML，支援 sharedStrings / inlineStr / 數字 / 日期序號 / 布林 / 空列。
寫：僅供測試造檔用。
"""
import re, zipfile
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
DATE_EPOCH = datetime(1899, 12, 30)
BUILTIN_DATE_IDS = set(range(14, 23)) | {45, 46, 47, 27, 30, 36, 50, 57}

def _col_index(ref):
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return None
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1

def _shared_strings(z):
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    out = []
    for si in root.findall("m:si", NS):
        out.append("".join(t.text or "" for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))
    return out

def _date_styles(z):
    """回傳 styleIndex -> 是否日期格式"""
    if "xl/styles.xml" not in z.namelist():
        return set()
    root = ET.fromstring(z.read("xl/styles.xml"))
    custom = {}
    nf = root.find("m:numFmts", NS)
    if nf is not None:
        for f in nf.findall("m:numFmt", NS):
            custom[int(f.get("numFmtId"))] = f.get("formatCode") or ""
    is_date = set()
    cx = root.find("m:cellXfs", NS)
    if cx is not None:
        for i, xf in enumerate(cx.findall("m:xf", NS)):
            fid = int(xf.get("numFmtId") or 0)
            if fid in BUILTIN_DATE_IDS:
                is_date.add(i); continue
            code = custom.get(fid, "")
            stripped = re.sub(r'\[[^\]]*\]|"[^"]*"|\\.', "", code)
            if stripped and re.search(r"[yYdD]", stripped) and not re.search(r"[0#]", stripped.replace("m", "M")):
                is_date.add(i)
            elif stripped and re.search(r"[yY]", stripped) and re.search(r"[dD]", stripped):
                is_date.add(i)
    return is_date

def _fmt_serial(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    if f < 1:
        return v
    dt = DATE_EPOCH + timedelta(days=f)
    return dt.strftime("%Y-%m-%d")

def read_xlsx(path, sheet_index=0):
    """回傳 rows：list[list[任何值]]，第一列為標頭。空尾欄/空尾列已修剪。"""
    if not zipfile.is_zipfile(path):
        raise ValueError("不是有效的 .xlsx（zip）檔；若是舊版 .xls，請先另存為 .xlsx")
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        sheets = wb.find("m:sheets", NS).findall("m:sheet", NS)
        if not sheets:
            raise ValueError("活頁簿內無工作表")
        if sheet_index >= len(sheets):
            raise ValueError(f"工作表索引超出範圍（共 {len(sheets)} 張）")
        rid = sheets[sheet_index].get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = None
        for rel in rels:
            if rel.get("Id") == rid:
                target = rel.get("Target")
                break
        if not target:
            raise ValueError("找不到工作表檔案路徑")
        target = target.lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        sst = _shared_strings(z)
        date_styles = _date_styles(z)
        root = ET.fromstring(z.read(target))
        rows = []
        sd = root.find("m:sheetData", NS)
        if sd is None:
            return []
        for row in sd.findall("m:row", NS):
            cells = {}
            for c in row.findall("m:c", NS):
                ci = _col_index(c.get("r"))
                if ci is None:
                    continue
                t = c.get("t") or "n"
                s = c.get("s")
                v = c.find("m:v", NS)
                is_el = c.find("m:is", NS)
                if t == "inlineStr" and is_el is not None:
                    val = "".join(x.text or "" for x in is_el.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"))
                elif t == "s":
                    idx = int(v.text) if v is not None and v.text else -1
                    val = sst[idx] if 0 <= idx < len(sst) else ""
                elif t == "b":
                    val = "TRUE" if (v is not None and v.text == "1") else "FALSE"
                elif t in ("str", "e"):
                    val = v.text if v is not None and v.text is not None else ""
                else:
                    if v is None or v.text is None:
                        val = ""
                    else:
                        if s is not None and int(s) in date_styles:
                            val = _fmt_serial(v.text)
                        else:
                            f = float(v.text)
                            val = str(int(f)) if f.is_integer() else repr(f)
                cells[ci] = val
            width = max(cells) + 1 if cells else 0
            rows.append([cells.get(i, "") for i in range(width)])
    while rows and not any(str(x).strip() for x in rows[-1]):
        rows.pop()
    for row in rows:
        while row and not str(row[-1]).strip():
            row.pop()
    return rows

def _serial(datestr):
    d = datetime.strptime(datestr, "%Y-%m-%d")
    return (d - DATE_EPOCH).days


def write_xlsx(path, rows, sheet_name="Sheet1", shared=False, date_cols=()):
    """測試用最小寫入器。shared=True 走 sharedStrings；date_cols 指定以日期序號寫入的欄索引。"""
    def esc(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    body = []
    sst = []
    for r, row in enumerate(rows, start=1):
        cs = []
        for c, val in enumerate(row):
            ref = ""
            n = c + 1
            while n:
                n, rem = divmod(n - 1, 26)
                ref = chr(65 + rem) + ref
            ref += str(r)
            if r > 1 and c in date_cols:
                cs.append(f'<c r="{ref}" s="1"><v>{_serial(val)}</v></c>')
            elif isinstance(val, (int, float)):
                cs.append(f'<c r="{ref}"><v>{val}</v></c>')
            elif shared:
                if val not in sst:
                    sst.append(val)
                cs.append(f'<c r="{ref}" t="s"><v>{sst.index(val)}</v></c>')
            else:
                cs.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{esc(val)}</t></is></c>')
        body.append(f'<row r="{r}">{"".join(cs)}</row>')
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             f'<sheetData>{"".join(body)}</sheetData></worksheet>')
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          f'<sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets></workbook>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>')
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
          '</Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                 '</Relationships>')
    extra = {}
    if date_cols:
        styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                  '<cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14" applyNumberFormat="1"/></cellXfs>'
                  '</styleSheet>')
        extra["xl/styles.xml"] = styles
        ct = ct.replace("</Types>", '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
        rels = rels.replace("</Relationships>", '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        wb = wb.replace('</sheets>', '</sheets>')
    if shared:
        sstxml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(sst)}" uniqueCount="{len(sst)}">'
                  + "".join(f'<si><t xml:space="preserve">{esc(x)}</t></si>' for x in sst) + '</sst>')
        extra["xl/sharedStrings.xml"] = sstxml
        ct = ct.replace("</Types>", '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>')
        rels = rels.replace("</Relationships>", '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        for k, v in extra.items():
            z.writestr(k, v)

if __name__ == "__main__":
    import sys, json
    print(json.dumps(read_xlsx(sys.argv[1])[:5], ensure_ascii=False))
