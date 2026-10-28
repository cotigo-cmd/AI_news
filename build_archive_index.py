# -*- coding: utf-8 -*-
"""扫描 archive/daily 与 archive/weekly，生成根索引页 index.html。
用法：python build_archive_index.py
"""
import json, re, os, glob, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(ROOT, "archive_index_template.html")
OUT = os.path.join(ROOT, "index.html")
MARK = '/*__ARCHIVE__*/{"daily":[],"weekly":[]}'
WD = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def parse(path):
    html = open(path, encoding="utf-8").read()
    t = re.search(r"<title>([^<]*)</title>", html)
    tot = re.search(r"本期共 (\d+) 条", html)
    secs = [int(x) for x in re.findall(r'sec-count">(\d+)', html)]
    if len(secs) < 5:
        secs = (secs + [0] * 5)[:5]
    total = int(tot.group(1)) if tot else sum(secs)
    return (t.group(1).strip() if t else ""), total, secs


def build(kind):
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, "archive", kind, "*.html")), reverse=True):
        date = os.path.splitext(os.path.basename(f))[0]
        try:
            d = datetime.date.fromisoformat(date)
        except ValueError:
            continue
        title, total, secs = parse(f)
        out.append({
            "date": date,
            "label": "%d 月 %d 日" % (d.month, d.day),
            "year": d.year,
            "weekday": WD[d.weekday()],
            "total": total,
            "secs": secs,
            "href": "archive/%s/%s.html" % (kind, date),
            "title": title,
        })
    return out


data = {"daily": build("daily"), "weekly": build("weekly")}
tpl = open(TPL, encoding="utf-8").read()
if MARK not in tpl:
    raise SystemExit("placeholder not found")
html = tpl.replace(MARK, "/*__ARCHIVE__*/" + json.dumps(data, ensure_ascii=False, separators=(",", ":")))
open(OUT, "w", encoding="utf-8").write(html)
print("daily=%d weekly=%d -> %s" % (len(data["daily"]), len(data["weekly"]), OUT))
