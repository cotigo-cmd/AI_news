# -*- coding: utf-8 -*-
"""AI HOT 个性化晨报 / 周报 生成器 v2
- 数据池：items?mode=all&window=24h|7d（含未入精选的公开条目，卡片会标注）
- 排序：按用户画像加权，而非纯时间；国内 / 政策协议 / AI4Science 相关优先
- 附加：去重、灵感雷达（可借鉴点）、标签过滤、北京时间人话
用法:
  python gen_briefing_v2.py daily  [YYYY-MM-DD]   当日晨报（忽略日期参数，始终取当前 24h 窗口）
  python gen_briefing_v2.py weekly [YYYY-MM-DD]   近 7 天回顾
输出: AI_News_晨报_YYYY-MM-DD.html / AI_News_周报_YYYY-MM-DD.html
"""
import json, datetime, urllib.request, urllib.error, urllib.parse, re, difflib, sys, os

BASE = "https://aihot.virxact.com/api/v1"
UA = "aihot-skill/1.2.1 (+https://aihot.virxact.com/aihot-skill/)"
OUTDIR = os.path.dirname(os.path.abspath(__file__))
BJ = datetime.timezone(datetime.timedelta(hours=8))

FIXED = ["模型发布/更新", "产品发布/更新", "行业动态", "论文研究", "技巧与观点"]
CAT2SEC = {
    "ai-models": "模型发布/更新", "ai-products": "产品发布/更新",
    "industry": "行业动态", "paper": "论文研究",
    "tip": "技巧与观点", "opinion": "技巧与观点",
}
COLORS = {
    "模型发布/更新": "#2563eb", "产品发布/更新": "#7c3aed",
    "行业动态": "#0d9488", "论文研究": "#d97706", "技巧与观点": "#db2777",
}
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# ============ 可调画像配置 ============
PROFILE = {
    # 权重合计 1.0；base=AIHOT 热度分，domain=AI4Science 硬相关，其余为增强项
    "weights": {"base": 0.25, "domain": 0.25, "policy": 0.20, "domestic": 0.20, "eco": 0.10},
    "caps": {"daily": 7, "weekly": 10},   # 每个版块最多展示条数
    "radar": {"daily": 5, "weekly": 8},
}

# 国内 / 海外：按新闻内容范围判定，不看发布者
DOM_CONTENT_RE = re.compile(
    r"中国|国内|我国|国产|人民币|工信部|网信办|发改委|科技部|信通院|国务院|央行|"
    r"教育部|国家数据局|东数西算|信创|阿里|腾讯|百度|字节|华为|小米|美团|京东|网易|快手|"
    r"拼多多|比亚迪|大疆|商汤|旷视|科大讯飞|智谱|月之暗面|DeepSeek|深度求索|"
    r"MiniMax|阶跃|零一万物|百川|面壁|智元|宇树|寒武纪|摩尔线程|壁仞|燧原|天数智芯|沐曦|"
    r"海光|飞腾|龙芯|中科曙光|浪潮|中兴|新华三|中国移动|中国电信|中国联通|"
    r"通义|千问|Qwen|豆包|文心|混元|盘古|昇腾|中科院|清华|北大|之江|智源|BAAI|"
    r"魔搭|ModelScope|火山引擎|阿里云|腾讯云|华为云|百度智能云|小红书|蚂蚁|生数|Vidu|"
    r"上海AI|上海人工智能|昆仑万维|天工|北京(?!时间)|上海|深圳|杭州|广州|成都|武汉|南京|合肥|苏州",
    re.I,
)

# 国内打不开的源，改用 AIHOT 站内页
BLOCKED_HOSTS = ("x.com", "twitter.com", "youtube.com", "youtu.be", "t.me", "telegram.org",
                 "facebook.com", "instagram.com", "reddit.com", "discord.com", "threads.net", "linkedin.com")


def pick_href(it):
    links = it.get("links") or {}
    orig = links.get("original") or ""
    host = urllib.parse.urlparse(orig).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if any(host == h or host.endswith("." + h) for h in BLOCKED_HOSTS):
        return links.get("aihot") or orig or "#"
    return orig or links.get("aihot") or "#"

POLICY_KW = [
    "政策", "监管", "法规", "立法", "备案", "标准", "白皮书", "指导意见", "管理办法",
    "合规", "许可证", "开源协议", "license", "协议", "mcp", "a2a", "agent protocol",
    "互联互通", "互操作", "数据要素", "算力", "智算", "信通院", "工信部", "网信办",
    "科技部", "发改委", "国务院", "欧盟", "eu ai act", "ai act", "版权", "著作权",
    "隐私", "数据安全", "出口管制", "制裁", "反垄断",
]
ECO_KW = [
    "开源", "社区", "生态", "开发者", "插件", "工具链", "sdk", "api", "开放平台",
    "共建", "联盟", "基金会", "github", "hugging face", "modelscope", "魔搭", "gitee",
    "贡献者", "maintainer", "release", "版本发布",
]
# 硬相关：只收 AI4Science / 计算数学 / 芯片散热 / 并行 / 数学形式化
DOMAIN = {
    "theory": ["论文", "理论", "预训练", "后训练", "蒸馏", "rlhf", "dpo", "scaling law", "世界模型",
               "可解释", "自监督", "对比学习", "表征学习", "检索增强", "rag", "transformer",
               "diffusion", "moe", "稀疏", "幻觉", "推理模型"],
}
INSP = {
    "theory": "理论 / 方法线索，可跟踪其假设、评测方式与可复现性。",
}


def has_kw(text, kw):
    """中文用子串；含 ASCII 的 token 加词边界，避免 mesh 命中 Meshy、rom 命中 ROM。"""
    if re.search(r"[a-z0-9]", kw):
        return re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", text) is not None
    return kw in text

# ============ 基础工具 ============
def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8")), r.status
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, 404
        raise


def fetch_items(mode, window, max_items):
    out, cursor = [], None
    while len(out) < max_items:
        url = f"{BASE}/items?mode={mode}&window={window}&limit=100"
        if cursor:
            url += "&cursor=" + urllib.parse.quote(cursor, safe="")
        d, _ = fetch(url)
        if not d:
            break
        out.extend(d.get("items", []))
        pg = d.get("page") or {}
        cursor = pg.get("nextCursor")
        if not pg.get("hasMore") or not cursor:
            break
    return out[:max_items]


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def truncate(s, n=59):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "\u2026"


def norm(s):
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", (s or "").lower())


def bj_time(it):
    iso = it.get("publishedAt") or it.get("discoveredAt")
    if not iso:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(BJ)
    except Exception:
        return ""
    now = datetime.datetime.now(BJ)
    if dt.date() == now.date():
        return f"今天 {dt:%H:%M}"
    if dt.date() == now.date() - datetime.timedelta(days=1):
        return f"昨天 {dt:%H:%M}"
    return f"{dt.month} 月 {dt.day} 日 {dt:%H:%M}"


# ============ 画像打分 ============
W = PROFILE["weights"]
# 雷达按「灵感价值」加权：与课题直接相关的方法/数学类优先于泛基建
RADAR_BONUS = {"theory": 15}


def radar_score(it):
    return it["_rel"] + RADAR_BONUS.get(it["_dgroup"], 0)


def enrich(it):
    text = ((it.get("title") or "") + " " + (it.get("summary") or "")).lower()
    dom = bool(DOM_CONTENT_RE.search(text))
    pol = any(has_kw(text, k) for k in POLICY_KW)
    eco = any(has_kw(text, k) for k in ECO_KW)
    dgroup = "theory" if (it.get("category") == "paper"
                          or any(has_kw(text, k) for k in DOMAIN["theory"])) else None
    domain = dgroup is not None
    score = it.get("score") or 0
    raw = (W["base"] * (score / 100.0) + W["domain"] * domain
           + W["policy"] * pol + W["domestic"] * dom + W["eco"] * eco)
    it["_dom"], it["_pol"], it["_eco"] = dom, pol, eco
    it["_domain"], it["_dgroup"] = domain, dgroup
    it["_rel"] = round(max(0.0, min(1.0, raw)) * 100)
    it["_time"] = bj_time(it)
    it["_insp"] = INSP.get(dgroup) or ("政策 / 协议信号，可能影响选题方向与合规边界。" if pol
                                       else ("开源 / 生态动向，影响后续工具链选型。" if eco
                                             else "可作为选题或技术选型的背景参考。"))
    return it


VER_RE = re.compile(r"[A-Za-z][A-Za-z0-9.\-]{1,}\s?\d+(?:\.\d+)?")


def vkeys(it):
    return {x.lower().replace(" ", "") for x in VER_RE.findall(it.get("title") or "")}


def dedupe(items):
    items = sorted(items, key=lambda x: (-x["_rel"], -(x.get("score") or 0)))
    kept = []
    for it in items:
        t = norm(it.get("title"))
        vk = vkeys(it)
        dup = False
        for k in kept:
            ratio = difflib.SequenceMatcher(None, t, norm(k.get("title"))).ratio()
            if ratio > 0.72:
                dup = True
                break
            # 同一版块内共享版本号（如 Genie 4）视为同一事件，避免同段重复占位
            if it.get("category") == k.get("category") and vk and (vk & vkeys(k)):
                dup = True
                break
        if dup:
            continue
        kept.append(it)
    return kept


def cap_event(pool, limit=2):
    """同一事件（共享版本号）全站最多保留 limit 条，兼顾不同角度但防止刷屏。"""
    cnt, out = {}, []
    for it in pool:  # pool 已按相关度降序
        ks = vkeys(it)
        key = min(ks) if ks else None
        if key is None:
            out.append(it)
            continue
        if cnt.get(key, 0) < limit:
            cnt[key] = cnt.get(key, 0) + 1
            out.append(it)
    return out


def build_sections(pool, mode):
    cap = PROFILE["caps"][mode]
    sec = {l: [] for l in FIXED}
    for it in pool:
        sec[CAT2SEC.get(it.get("category"), "技巧与观点")].append(it)
    for l in FIXED:
        sec[l] = sorted(sec[l], key=lambda x: -x["_rel"])[:cap]
    return sec


# ============ 渲染 ============
def tag_html(it):
    t = [f'<span class="tag {"dom" if it["_dom"] else "ovs"}">{"国内" if it["_dom"] else "海外"}</span>']
    if it["_pol"]:
        t.append('<span class="tag pol">政策/协议</span>')
    if it["_eco"]:
        t.append('<span class="tag eco">开源/生态</span>')
    if it["_domain"]:
        t.append('<span class="tag rel">★ AI4Science</span>')
    if not it.get("selected"):
        t.append('<span class="tag muted">未入精选</span>')
    t.append(f'<span class="tag score">相关 {it["_rel"]}</span>')
    return "".join(t)


def card_html(idx, it):
    href = pick_href(it)
    return f'''    <a class="card" id="c{idx}" href="{esc(href)}" target="_blank" rel="noopener noreferrer"
       data-dom="{1 if it["_dom"] else 0}" data-pol="{1 if it["_pol"] else 0}" data-rel="{1 if it["_domain"] else 0}">
      <div class="card-top"><span class="num">{idx}</span><span class="src-chip">{esc((it.get("source") or {}).get("name",""))}</span></div>
      <div class="card-meta"><span class="time">{esc(it["_time"])}</span>{tag_html(it)}</div>
      <h3 class="card-title">{esc(it.get("title",""))}</h3>
      <p class="card-sum">{esc(truncate(it.get("summary","")))}</p>
      <span class="card-link">查看详情 &rarr;</span>
    </a>'''


def radar_html(rows):
    out = []
    for n, it in enumerate(rows, 1):
        href = ("#c%d" % it["_idx"]) if it.get("_idx") else pick_href(it)
        out.append(f'''    <div class="radar-row" data-dom="{1 if it["_dom"] else 0}" data-pol="{1 if it["_pol"] else 0}" data-rel="{1 if it["_domain"] else 0}">
      <div class="r-rank">{n:02d}</div>
      <div class="r-body">
        <a class="r-title" href="{esc(href)}" title="跳到下方第 {it.get("_idx","")} 条">{esc(it.get("title",""))}</a>
        <div class="r-meta">{esc((it.get("source") or {}).get("name",""))} · {esc(it["_time"])} · 相关 {it["_rel"]}</div>
        <div class="r-insp">可借鉴：{esc(it["_insp"])}</div>
      </div>
    </div>''')
    return "".join(out)


CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:#f5f7fa;color:#1f2937;line-height:1.6}
.wrap{max-width:1100px;margin:0 auto;padding:0 18px 60px}
.hero{background:linear-gradient(135deg,#1e3a8a 0%,#4338ca 55%,#6d28d9 100%);color:#fff;padding:42px 18px 34px;border-radius:0 0 22px 22px}
.hero .inner{max-width:1100px;margin:0 auto}
.eyebrow{font-size:13px;letter-spacing:3px;opacity:.85;text-transform:uppercase}
.hero h1{font-size:30px;margin:8px 0 4px;font-weight:800}
.hero .sub{opacity:.9;font-size:15px}
.stat-row{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}
.stat{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.22);border-radius:12px;padding:9px 13px;font-size:13px}
.stat b{font-size:20px;display:block}
.sec-line{margin-top:10px;font-size:13px;opacity:.9}
.profile{margin-top:12px;font-size:12.5px;opacity:.82;border-top:1px solid rgba(255,255,255,.2);padding-top:10px}
.lead{margin-top:16px;background:rgba(255,255,255,.1);border-left:3px solid #fbbf24;padding:12px 16px;border-radius:8px;font-size:15px}
.lead .lt{font-weight:700;color:#fde68a}
.nav{position:sticky;top:0;z-index:20;background:#fff;border-bottom:1px solid #e5e7eb;padding:10px 0;box-shadow:0 2px 8px rgba(0,0,0,.04)}
.nav .inner{max-width:1100px;margin:0 auto;padding:0 18px}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}
.filters button{border:1px solid #e5e7eb;background:#f8fafc;color:#374151;border-radius:999px;padding:5px 12px;font-size:13px;cursor:pointer;transition:.15s}
.filters button:hover{border-color:#94a3b8}
.filters button.on{background:#111827;color:#fff;border-color:#111827}
.anchors{display:flex;gap:8px;flex-wrap:wrap}
.nav-pill{--c:#333;text-decoration:none;color:#374151;background:#f3f4f6;border:1px solid #e5e7eb;border-radius:999px;padding:5px 11px;font-size:12.5px;display:inline-flex;align-items:center;gap:6px}
.nav-pill:hover{border-color:var(--c);color:var(--c)}
.nav-pill b{background:var(--c);color:#fff;border-radius:999px;padding:0 7px;font-size:12px}
.radar{margin-top:30px;background:#fff;border:1px solid #e8ecf3;border-radius:16px;padding:18px;box-shadow:0 2px 10px rgba(15,23,42,.05)}
.radar-head{display:flex;align-items:center;gap:10px;font-size:20px;font-weight:800;color:#111827;margin-bottom:4px}
.radar-head .badge{font-size:12px;font-weight:600;color:#7c3aed;background:#f3e8ff;border-radius:999px;padding:2px 9px}
.radar-desc{font-size:13px;color:#64748b;margin-bottom:12px}
.radar-row{display:flex;gap:14px;padding:12px 0;border-top:1px dashed #e8ecf3}
.radar-row:first-of-type{border-top:0}
.r-rank{font-size:22px;font-weight:800;color:#c7d2fe;min-width:34px}
.r-body{flex:1;min-width:0}
.r-title{font-size:15.5px;font-weight:700;color:#0f172a;text-decoration:none;display:block}
.r-title:hover{color:#2563eb}
.r-meta{font-size:12.5px;color:#64748b;margin:3px 0}
.r-jump{color:#2563eb;text-decoration:none;margin-left:6px}
.r-insp{font-size:13px;color:#7c3aed;background:#faf5ff;border-left:2px solid #c4b5fd;padding:5px 10px;border-radius:0 6px 6px 0;margin-top:5px}
.section{margin-top:34px}
.sec-head{display:flex;align-items:center;gap:10px;font-size:21px;color:#111827;padding-bottom:8px;border-bottom:2px solid var(--c);margin-bottom:16px}
.sec-head .dot{width:12px;height:12px;border-radius:50%;display:inline-block}
.sec-count{margin-left:auto;background:var(--c);color:#fff;font-size:13px;border-radius:999px;padding:2px 10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.card{background:#fff;border:1px solid #eceef1;border-radius:14px;padding:16px;text-decoration:none;color:inherit;display:flex;flex-direction:column;gap:9px;transition:.18s;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.card:hover{transform:translateY(-3px);box-shadow:0 8px 22px rgba(0,0,0,.1);border-color:#cbd5e1}
.card-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.num{background:#111827;color:#fff;font-weight:700;font-size:13px;min-width:26px;height:26px;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;padding:0 6px}
.src-chip{font-size:12px;color:#475569;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:999px;padding:3px 10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:78%}
.card-meta{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.time{font-size:12px;color:#94a3b8}
.tag{font-size:11.5px;border-radius:999px;padding:1px 7px;border:1px solid transparent}
.tag.dom{background:#dcfce7;color:#15803d;border-color:#bbf7d0}
.tag.ovs{background:#f1f5f9;color:#64748b;border-color:#e2e8f0}
.tag.pol{background:#fef3c7;color:#b45309;border-color:#fde68a}
.tag.eco{background:#e0f2fe;color:#0369a1;border-color:#bae6fd}
.tag.rel{background:#ede9fe;color:#6d28d9;border-color:#ddd6fe}
.tag.muted{background:#f8fafc;color:#94a3b8;border-color:#eef2f7}
.tag.score{background:#111827;color:#fff}
.card-title{font-size:16px;font-weight:700;line-height:1.45;color:#0f172a}
.card-sum{font-size:14px;color:#475569;flex:1}
.card-link{font-size:13px;color:#2563eb;font-weight:600}
.empty{grid-column:1/-1;text-align:center;color:#94a3b8;padding:28px;border:1px dashed #d8dee6;border-radius:12px;background:#fafbfc}
footer{margin-top:46px;padding-top:18px;border-top:1px solid #e5e7eb;font-size:13px;color:#64748b;text-align:center}
footer a{color:#2563eb;text-decoration:none}
@media(max-width:520px){.hero h1{font-size:23px}.grid{grid-template-columns:1fr}.r-rank{min-width:26px;font-size:18px}}
"""

JS = """
document.querySelectorAll('.filters button').forEach(function(b){
  b.onclick=function(){
    document.querySelectorAll('.filters button').forEach(function(x){x.classList.remove('on')});
    b.classList.add('on');
    var f=b.dataset.f;
    document.querySelectorAll('.card,.radar-row').forEach(function(c){
      var ok=true;
      if(f==='dom')ok=c.dataset.dom==='1';
      if(f==='pol')ok=c.dataset.pol==='1';
      if(f==='rel')ok=c.dataset.rel==='1';
      c.style.display=ok?'':'none';
    });
    document.querySelectorAll('.section').forEach(function(s){
      var any=Array.prototype.some.call(s.querySelectorAll('.card'),function(c){return c.style.display!=='none'});
      s.style.display=any?'':'none';
    });
    var rd=document.querySelector('.radar');
    if(rd){var any2=Array.prototype.some.call(rd.querySelectorAll('.radar-row'),function(c){return c.style.display!=='none'});
      rd.style.display=any2?'':'none';}
  };
});
"""


def render(mode_label, title_human, subtitle, stats, total, dom_n, pol_n, rel_n,
           sec, radar, lead_title, lead_para, gen_human, attrib_name, attrib_url):
    # 全局连续编号
    gi, nav, sections_html = 0, [], []
    for li, label in enumerate(FIXED):
        sec_id = "sec-" + str(li)
        color = COLORS[label]
        items = sec[label]
        nav.append(f'<a class="nav-pill" href="#{sec_id}" style="--c:{color}">{esc(label)}<b>{len(items)}</b></a>')
        if not items:
            body = '<div class="empty">本期暂无该版块条目</div>'
        else:
            cards = []
            for it in items:
                gi += 1
                it["_idx"] = gi
                cards.append(card_html(gi, it))
            body = "".join(cards)
        sections_html.append(
            f'<section id="{sec_id}" class="section">'
            f'<h2 class="sec-head" style="--c:{color}"><span class="dot" style="background:{color}"></span>{esc(label)}'
            f'<span class="sec-count">{len(items)}</span></h2><div class="grid">{body}</div></section>')

    radar_html_str = radar_html(radar)
    lead_block = (f'<div class="lead"><span class="lt">编辑头条 · </span>{esc(lead_title)}<br>{esc(lead_para)}</div>'
                  if lead_title else "")
    sec_line = " · ".join(f"{esc(l)} {stats[l]}" for l in FIXED)

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI {mode_label} · {title_human}</title>
<style>{CSS}</style>
</head>
<body>
<header class="hero"><div class="inner">
  <div class="eyebrow">AI HOT · 个性化{mode_label}</div>
  <h1>{title_human}</h1>
  <div class="sub">{subtitle}</div>
  <div class="stat-row">
    <div class="stat">总条数<b>{total}</b></div>
    <div class="stat">国内<b>{dom_n}</b></div>
    <div class="stat">政策/协议<b>{pol_n}</b></div>
    <div class="stat">★ AI4Science<b>{rel_n}</b></div>
  </div>
  <div class="sec-line">{sec_line}</div>
  {lead_block}
  <div class="profile">加权画像：AI4Science 相关性 &gt; 政策/协议 &gt; 国内 &gt; 热度 · 已去重，含未入精选条目（标签标注）</div>
</div></header>

<nav class="nav"><div class="inner">
  <div class="filters">
    <button data-f="all" class="on">全部</button>
    <button data-f="dom">只看国内</button>
    <button data-f="pol">政策 / 协议</button>
    <button data-f="rel">★ 与我相关</button>
  </div>
  <div class="anchors"><a class="nav-pill" href="#radar" style="--c:#7c3aed">灵感雷达<b>{len(radar)}</b></a>{''.join(nav)}</div>
</div></nav>

<main class="wrap">
  <section id="radar" class="radar">
    <div class="radar-head">灵感雷达 <span class="badge">按你的画像加权</span></div>
    <div class="radar-desc">从本期条目中挑出与你最相关、或最可能触发项目灵感的前 {len(radar)} 条，附规则化「可借鉴」提示。</div>
    {radar_html_str}
  </section>

  {''.join(sections_html)}

  <footer>
    <p>本期共 {total} 条 · 数据源：<a href="{esc(attrib_url)}" target="_blank" rel="noopener noreferrer">{esc(attrib_name)}</a>（{esc(attrib_url)}）</p>
    <p>生成时间：{gen_human} · 排序为本地加权结果，不代表 AI HOT 官方排序；引用数字/政策请以原文为准</p>
  </footer>
</main>
<script>{JS}</script>
</body>
</html>'''


# ============ 入口 ============
def get_lead(today_str):
    try:
        d, _ = fetch(f"{BASE}/dailies/latest")
        if not d:
            return "", ""
        r = d["report"]
        if r.get("date") == today_str:
            lead = r.get("lead") or {}
            return lead.get("title", ""), lead.get("leadParagraph", "")
    except Exception:
        pass
    return "", ""


def gen_daily(_arg=None):
    now = datetime.datetime.now(BJ)
    date_str = now.date().isoformat()
    pool = [enrich(i) for i in fetch_items("all", "24h", 200)]
    pool = cap_event(dedupe(pool))
    sec = build_sections(pool, "daily")
    stats = {l: len(sec[l]) for l in FIXED}
    total = sum(stats.values())
    displayed = [it for l in FIXED for it in sec[l]]
    dom_n = sum(1 for i in displayed if i["_dom"])
    pol_n = sum(1 for i in displayed if i["_pol"])
    rel_n = sum(1 for i in displayed if i["_domain"])
    # 先编号再从展示条目里挑雷达（保证锚点有效）
    gi = 0
    for l in FIXED:
        for it in sec[l]:
            gi += 1
            it["_idx"] = gi
    radar = sorted(displayed, key=lambda x: -radar_score(x))[:PROFILE["radar"]["daily"]]
    lead_t, lead_p = get_lead(date_str)
    title_human = f"{now.year} 年 {now.month} 月 {now.day} 日 {WEEKDAY_CN[now.weekday()]}"
    subtitle = f"过去 24 小时 · 共 {total} 条（已去重）· 国内 {dom_n} 条"
    html = render("晨报", title_human, subtitle, stats, total, dom_n, pol_n, rel_n, sec, radar,
                  lead_t, lead_p, now.strftime("%Y 年 %m 月 %d 日 %H:%M（北京时间）"),
                  "AIHOT", "https://aihot.news/")
    out = os.path.join(OUTDIR, f"AI_News_晨报_{date_str}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[daily] {date_str} total={total} dom={dom_n} pol={pol_n} rel={rel_n} -> {out}")
    return out


def gen_weekly(_arg=None):
    now = datetime.datetime.now(BJ)
    base_str = now.date().isoformat()
    start = now.date() - datetime.timedelta(days=6)
    pool = [enrich(i) for i in fetch_items("all", "7d", 300)]
    pool = cap_event(dedupe(pool))
    sec = build_sections(pool, "weekly")
    stats = {l: len(sec[l]) for l in FIXED}
    total = sum(stats.values())
    displayed = [it for l in FIXED for it in sec[l]]
    dom_n = sum(1 for i in displayed if i["_dom"])
    pol_n = sum(1 for i in displayed if i["_pol"])
    rel_n = sum(1 for i in displayed if i["_domain"])
    gi = 0
    for l in FIXED:
        for it in sec[l]:
            gi += 1
            it["_idx"] = gi
    radar = sorted(displayed, key=lambda x: -radar_score(x))[:PROFILE["radar"]["weekly"]]
    title_human = f"{now.year} 年 {now.month} 月 {now.day} 日（周回顾）"
    subtitle = f"滚动聚合近 7 天（{start.month} 月 {start.day} 日 ~ {now.month} 月 {now.day} 日）· 共 {total} 条（已去重）· 国内 {dom_n} 条"
    html = render("周报", title_human, subtitle, stats, total, dom_n, pol_n, rel_n, sec, radar,
                  "", "", now.strftime("%Y 年 %m 月 %d 日 %H:%M（北京时间）"),
                  "AIHOT", "https://aihot.news/")
    out = os.path.join(OUTDIR, f"AI_News_周报_{base_str}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[weekly] {base_str} total={total} dom={dom_n} pol={pol_n} rel={rel_n} -> {out}")
    return out


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if mode == "daily":
        gen_daily(arg)
    elif mode == "weekly":
        gen_weekly(arg)
    else:
        print("usage: gen_briefing_v2.py [daily|weekly] [YYYY-MM-DD]")
        sys.exit(1)
