# -*- coding: utf-8 -*-
"""构建实时版 index.html：把当日数据作为离线兜底注入模板。
实时页面本身会在浏览器直连 AI HOT 接口；此兜底仅在接口不可用时展示。
"""
import json, datetime, os, re, sys
import gen_briefing as g

OUTDIR = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(OUTDIR, "live_template.html")
OUT_NAME = sys.argv[1] if len(sys.argv) > 1 else "index.html"
OUT = os.path.join(OUTDIR, OUT_NAME)
MARK = '/*__FALLBACK__*/{"ts":"","items":[]}'

items = g.fetch_items("all", "24h", 200)
keep = []
for it in items:
    links = it.get("links") or {}
    keep.append({
        "title": it.get("title"),
        "summary": it.get("summary"),
        "source": {"name": (it.get("source") or {}).get("name", "")},
        "category": it.get("category"),
        "score": it.get("score"),
        "publishedAt": it.get("publishedAt"),
        "discoveredAt": it.get("discoveredAt"),
        "selected": it.get("selected"),
        "links": {"aihot": links.get("aihot"), "original": links.get("original")},
    })

now = datetime.datetime.now(g.BJ)
ts = now.strftime("%Y 年 %m 月 %d 日 %H:%M（北京时间）")
payload = json.dumps({"ts": ts, "items": keep}, ensure_ascii=False, separators=(",", ":"))

with open(TPL, encoding="utf-8") as f:
    html = f.read()
if MARK not in html:
    raise SystemExit("placeholder not found")
html = html.replace(MARK, "/*__FALLBACK__*/" + payload)

with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)

print("items=%d  ts=%s" % (len(keep), ts))
print("written: %s  (%.0f KB)" % (OUT, os.path.getsize(OUT) / 1024))
