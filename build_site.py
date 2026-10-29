# -*- coding: utf-8 -*-
"""构建发布目录 AI_News_site/（WorkBuddy 发布 + GitHub Pages 共用同一份内容）。

产物：
  AI_News_site/index.html         归档索引页（实时入口 + 日报/周报归档）
  AI_News_site/live.html          实时版（内嵌当日兜底快照）
  AI_News_site/archive/daily/*.html    日报归档
  AI_News_site/archive/weekly/*.html   周报归档

用法：
  python build_site.py            # 同步归档 + 建索引 + 建实时页（需联网拉兜底）
  python build_site.py --no-live  # 只同步归档 + 建索引（离线可用）
"""
import os
import re
import sys
import glob
import json
import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(os.path.dirname(ROOT), "AI_News_site")
ARCHIVE = os.path.join(SITE, "archive")
INDEX_TPL = os.path.join(ROOT, "archive_index_template.html")
LIVE_TPL = os.path.join(ROOT, "live_template.html")
MARK = '/*__ARCHIVE__*/{"daily":[],"weekly":[]}'
FALLBACK_MARK = '/*__FALLBACK__*/{"ts":"","items":[]}'
WD = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 国内打不开的源（X / Twitter 等）：改指 AIHOT 站内当日/当周页
BLOCKED_RE = re.compile(
    r'href="https?://(?:www\.)?(?:x|twitter)\.com[^"]*"', re.I)


def fix_links(html, date, kind):
    """归档页后处理：不可达的海外源改指 AIHOT 站内页。"""
    target = "https://aihot.news/daily/%s" % date if kind == "daily" else "https://aihot.news/weekly"
    html = BLOCKED_RE.sub('href="%s"' % target, html)
    html = html.replace("阅读原文 &rarr;", "查看详情 &rarr;")
    return html


def sync_archive():
    """根目录的日报/周报产物 → site/archive/。"""
    for kind, pattern in (("daily", "AI_News_晚报_*.html"), ("weekly", "AI_News_周报_*.html")):
        outdir = os.path.join(ARCHIVE, kind)
        os.makedirs(outdir, exist_ok=True)
        n = 0
        for src in sorted(glob.glob(os.path.join(ROOT, pattern))):
            date = os.path.splitext(os.path.basename(src))[0].split("_")[-1]
            html = open(src, encoding="utf-8").read()
            html = fix_links(html, date, kind)
            dst = os.path.join(outdir, date + ".html")
            open(dst, "w", encoding="utf-8").write(html)
            n += 1
        print("archive/%s: %d 期" % (kind, n))


def parse(path):
    """从归档页提取标题、总条数、各版块条数。"""
    html = open(path, encoding="utf-8").read()
    t = re.search(r"<title>([^<]*)</title>", html)
    tot = re.search(r"本期共 (\d+) 条", html)
    secs = [int(x) for x in re.findall(r'sec-count">(\d+)', html)]
    if len(secs) < 5:
        secs = (secs + [0] * 5)[:5]
    total = int(tot.group(1)) if tot else sum(secs)
    return (t.group(1).strip() if t else ""), total, secs


def build_index():
    """扫描 archive/ 生成索引页。"""
    data = {}
    for kind in ("daily", "weekly"):
        items = []
        for f in sorted(glob.glob(os.path.join(ARCHIVE, kind, "*.html")), reverse=True):
            date = os.path.splitext(os.path.basename(f))[0]
            try:
                d = datetime.date.fromisoformat(date)
            except ValueError:
                continue
            title, total, secs = parse(f)
            items.append({
                "date": date,
                "label": "%d 月 %d 日" % (d.month, d.day),
                "year": d.year,
                "weekday": WD[d.weekday()],
                "total": total,
                "secs": secs,
                "href": "archive/%s/%s.html" % (kind, date),
                "title": title,
            })
        data[kind] = items

    tpl = open(INDEX_TPL, encoding="utf-8").read()
    if MARK not in tpl:
        raise SystemExit("索引模板占位符未找到")
    out = tpl.replace(MARK, "/*__ARCHIVE__*/" + json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    dst = os.path.join(SITE, "index.html")
    open(dst, "w", encoding="utf-8").write(out)
    print("index.html: daily=%d weekly=%d" % (len(data["daily"]), len(data["weekly"])))


def build_live():
    """实时页：注入当日兜底快照（拉不到数据时保留旧快照，不阻塞构建）。"""
    import gen_briefing as g

    try:
        items = g.fetch_items("all", "24h", 200)
    except Exception as e:  # 网络失败不阻塞归档发布
        print("拉取兜底数据失败（沿用上次快照）:", e)
        if os.path.exists(os.path.join(SITE, "live.html")):
            return
        items = []

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

    html = open(LIVE_TPL, encoding="utf-8").read()
    if FALLBACK_MARK not in html:
        raise SystemExit("实时版模板占位符未找到")
    html = html.replace(FALLBACK_MARK, "/*__FALLBACK__*/" + payload)
    dst = os.path.join(SITE, "live.html")
    open(dst, "w", encoding="utf-8").write(html)
    print("live.html: %d 条兜底快照 · %s" % (len(keep), ts))


if __name__ == "__main__":
    os.makedirs(SITE, exist_ok=True)
    sync_archive()
    build_index()
    if "--no-live" not in sys.argv:
        build_live()
    print("完成 ->", SITE)
