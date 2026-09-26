#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NeuroDaily —— 每日脑科学资讯聚合（单文件，零依赖，只用 Python 标准库）

主题：MEG / EEG / MRI / fMRI / 脑机接口 / 神经科学
来源：
  论文  PubMed、bioRxiv / medRxiv、arXiv
  新闻  Google News（英文 + 中文）——只聚合正规媒体的真实报道
分区：中国 / 全球
输出：<out>/index.html（手机可看的静态网页）+ 每日存档 + 可选微信推送（Server酱）

用法：
  python neurodaily.py              # 抓最近 2 天，已看过的自动去重
  python neurodaily.py --days 3 --out docs
"""
import argparse
import datetime as dt
import email.utils
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# ======================= 配置区（按需修改） =======================

# 主题 -> 关键词。规则：全大写缩写（EEG、MEG…）区分大小写并按整词匹配；
# 其他英文不区分大小写、按词首匹配；中文直接包含即可。
TOPICS = {
    "MEG":  ["MEG", "magnetoencephalograph", "脑磁图", "脑磁"],
    "EEG":  ["EEG", "electroencephalograph", "脑电"],
    "fMRI": ["fMRI", "functional MRI", "functional magnetic resonance", "功能磁共振", "功能性磁共振"],
    "MRI":  ["MRI", "magnetic resonance imaging", "磁共振", "核磁"],
    "BCI":  ["BCI", "brain-computer interface", "brain–computer interface", "brain computer interface",
             "brain-machine interface", "brain implant", "Neuralink", "脑机接口", "脑机"],
}
FALLBACK_TOPIC = "神经科学"   # 没命中上面任何主题的，归入这一类

# 新闻检索词（Google News）
NEWS_EN = [
    'magnetoencephalography OR "MEG brain"',
    'EEG brain',
    'fMRI brain',
    '"brain MRI" study',
    '"brain-computer interface" OR Neuralink OR "brain implant"',
    'neuroscience study',
]
NEWS_ZH = ['脑磁图', '脑电 研究', '功能磁共振', '磁共振 脑', '脑机接口', '脑科学 OR 神经科学']

# 标题含这些词的新闻直接丢弃（过滤炒股类噪音）
NEWS_EXCLUDE = ["概念股", "涨停", "跌停", "股价", "A股", "板块", "龙头股", "个股", "stock", "Stock", "shares"]

# 判断“中国”的规则 —— 论文看第一/通讯（末位）作者单位，英文新闻看标题
CN_AFFIL = ["China", "中国"]   # 可按需加入其他地名
CN_TEXT = re.compile(r"\bChin(a|ese)\b|Beijing|Shanghai|Shenzhen|Hangzhou|Wuhan|Tianjin|Guangzhou|Nanjing|中国")
# 中文新闻默认算“中国”，但标题明显讲国外的归“全球”
FOREIGN_ZH = re.compile(r"马斯克|Neuralink|美国|英国|日本|韩国|欧洲|德国|法国|海外|国外|斯坦福|哈佛|麻省|牛津|剑桥|Meta|谷歌|OpenAI|Synchron")

PUBMED_QUERY = (
    '(magnetoencephalograph*[tiab] OR MEG[tiab] OR EEG[tiab] OR electroencephalograph*[tiab] '
    'OR fMRI[tiab] OR "functional MRI"[tiab] OR "functional magnetic resonance"[tiab] '
    'OR "brain computer interface"[tiab] OR "brain computer interfaces"[tiab] '
    'OR "brain machine interface"[tiab] '
    'OR ((MRI[tiab] OR "magnetic resonance"[tiab]) AND (brain[tiab] OR cerebral[tiab] OR neuro*[tiab])))'
)
PUBMED_MAX = 150

RXIV_CATS = {
    "biorxiv": {"neuroscience"},
    "medrxiv": {"neurology", "radiology and imaging"},
}

ARXIV_QUERY = (
    '(cat:q-bio.NC OR cat:eess.SP OR cat:eess.IV OR cat:cs.HC OR cat:cs.LG) AND '
    '(abs:EEG OR abs:MEG OR abs:magnetoencephalography OR abs:fMRI OR '
    'abs:"brain-computer interface" OR abs:"brain computer interface")'
)
ARXIV_MAX = 80

KEEP_SEEN_DAYS = 30   # 去重记录保留天数

# ---- 过滤心脏相关内容：标题讲心脏、且标题里没有脑/神经相关词，就丢弃 ----
HEART = re.compile(
    r"\b(heart|hearts|cardiac|cardio\w*|cardiovascular|myocard\w*|coronary|aortic|aorta|"
    r"atrial fibrillation|arrhythmi\w*|echocardiograph\w*)\b"
    r"|心脏|心肌|心血管|冠脉|冠状动脉|冠心病|心衰|心力衰竭|心房|心室|心律|房颤|主动脉|心电", re.I)
BRAIN = re.compile(
    r"brain|cerebr|cortic|neur|cognit|mental|psychiatr|stroke|dementia|alzheimer|epilep|"
    r"\bEEG\b|\bMEG\b|fMRI|\bBCI\b|脑|神经|认知|卒中|痴呆|癫痫|精神", re.I)

# ---- 脑图像处理相关会议 ----
# 已结束的会议自动隐藏；每年看一下官网，把下一届的日期补进来即可。
# 日期格式 YYYY-MM-DD；deadlines 为 (名称, 日期) 列表，可为空。（信息核对于 2026-09-26）
CONFERENCES = [
    # region: "global" 或 "cn"
    dict(name="MICCAI 2026", full="医学图像计算与计算机辅助介入", region="global",
         start="2026-09-27", end="2026-10-01", city="法国 斯特拉斯堡", url="https://miccai.org/upcoming-conferences/"),
    dict(name="SfN Neuroscience 2026", full="美国神经科学学会年会", region="global",
         start="2026-11-14", end="2026-11-18", city="美国 华盛顿", url="https://www.sfn.org/meetings/neuroscience-2026"),
    dict(name="SPIE Medical Imaging 2027", full="含 Image Processing 分会", region="global",
         start="2027-02-14", end="2027-02-18", city="加拿大 温哥华", url="https://spie.org/conferences-and-exhibitions/medical-imaging"),
    dict(name="ISMRM 2027", full="国际医学磁共振学会年会", region="global",
         start="2027-05-08", end="2027-05-13", city="加拿大 温哥华", url="https://www.ismrm.org/27m/",
         deadlines=[("摘要截止", "2026-10-28")]),
    dict(name="ISBI 2027", full="IEEE 国际生物医学成像研讨会", region="global",
         start="2027-05-25", end="2027-05-28", city="瑞士 洛桑", url="https://biomedicalimaging.org/2027/",
         deadlines=[("4页论文截止", "2026-10-26"), ("1页摘要截止", "2027-02-01")]),
    dict(name="International BCI Meeting 2027", full="第12届国际脑机接口大会", region="global",
         start="2027-06-07", end="2027-06-10", city="克罗地亚 希贝尼克", url="https://bcisociety.org/bci-meeting/",
         deadlines=[("摘要截止", "2027-01-15")]),
    dict(name="OHBM 2027", full="人脑图谱组织年会", region="global",
         start="2027-06-26", end="2027-06-30", city="加拿大 多伦多", url="https://www.humanbrainmapping.org/ohbm-2027/",
         deadlines=[("摘要截止（约）", "2026-12-15")]),
    dict(name="IPMI 2027", full="医学影像信息处理", region="global",
         start="2027-06-27", end="2027-07-02", city="加拿大 魁北克 Orford", url="https://2027.ipmi-conf.org/",
         deadlines=[("论文截止", "2026-12-07")]),
    dict(name="MIDL 2027", full="医学影像深度学习", region="global",
         start="2027-07-14", end="2027-07-16", city="葡萄牙 波尔图", url="https://2027.midl.io/"),
    dict(name="MICCAI 2027", full="医学图像计算与计算机辅助介入", region="global",
         start="2027-09-26", end="2027-10-01", city="新西兰 奥克兰", url="https://miccai.org/upcoming-conferences/"),
    dict(name="CCR 2026", full="中华医学会第33次放射学学术大会", region="cn",
         start="2026-11-19", end="2026-11-22", city="北京", url="https://ccr2026.sciconf.cn/"),
]

# 会议动态（自动抓新闻：征稿、召开、获奖等）
CONF_NEWS_EN = [
    'OHBM OR MICCAI OR ISMRM OR "ISBI 2027" OR BIOMAG conference',
    '"BCI Meeting" OR "brain-computer interface conference" OR "neuroimaging conference"',
]
CONF_NEWS_ZH = ['脑成像 学术会议 OR 神经影像 学术会议 OR 医学影像 大会', '脑机接口 大会 OR 脑科学 大会 OR 神经科学 学术会议']

# ================================================================

UA = "Mozilla/5.0 (compatible; NeuroDaily/1.0)"
BJT = dt.timezone(dt.timedelta(hours=8))


def log(msg):
    print(msg, flush=True)


def get(url, data=None, timeout=40, retries=2):
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if i == retries:
                log(f"  ! 获取失败 {url[:90]} … {e}")
                return None
            time.sleep(2 * (i + 1))


def get_json(url, **kw):
    raw = get(url, **kw)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _kw_regex(kw):
    if re.fullmatch(r"[A-Za-z]{2,5}", kw) and sum(c.isupper() for c in kw) >= 2:
        return re.compile(rf"(?<![A-Za-z]){re.escape(kw)}(?![A-Za-z])")
    if kw.isascii():
        return re.compile(rf"(?<![A-Za-z]){re.escape(kw)}", re.I)   # 紧挨汉字也能匹配
    return re.compile(re.escape(kw))


TOPIC_RE = {t: [_kw_regex(k) for k in kws] for t, kws in TOPICS.items()}


def tag(text):
    return [t for t, pats in TOPIC_RE.items() if any(p.search(text) for p in pats)]


def is_cn_affil(s):
    return any(m in (s or "") for m in CN_AFFIL)


def item(kind, region, title, url, source, date="", summary="", topics=None):
    return {
        "kind": kind, "region": region, "title": clean(title), "url": url or "",
        "source": clean(source), "date": date, "summary": clean(summary)[:700],
        "topics": topics or [FALLBACK_TOPIC],
    }


# ----------------------------- 新闻 -----------------------------

def is_heart(title):
    return bool(HEART.search(title)) and not BRAIN.search(title)


def fetch_news(days, en=None, zh=None, kind="news"):
    out = []
    en = NEWS_EN if en is None else en
    zh = NEWS_ZH if zh is None else zh
    feeds = [("en", q, "hl=en-US&gl=US&ceid=US:en") for q in en] + \
            [("zh", q, "hl=zh-CN&gl=CN&ceid=CN:zh-Hans") for q in zh]
    for lang, q, loc in feeds:
        url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{q} when:{days}d") + "&" + loc
        raw = get(url)
        if not raw:
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            continue
        for it in root.iter("item"):
            title = it.findtext("title") or ""
            src = it.findtext("source") or ""
            if src and title.endswith(" - " + src):
                title = title[: -len(src) - 3]
            if any(x in title for x in NEWS_EXCLUDE) or is_heart(clean(title)):
                continue
            if lang == "zh":
                region = "global" if FOREIGN_ZH.search(title) else "cn"
            else:
                region = "cn" if CN_TEXT.search(title) else "global"
            date = ""
            try:
                date = email.utils.parsedate_to_datetime(it.findtext("pubDate")).astimezone(BJT).strftime("%m-%d %H:%M")
            except Exception:  # noqa: BLE001
                pass
            topics = ["会议"] if kind == "confnews" else tag(title)
            out.append(item(kind, region, title, it.findtext("link"), src, date, topics=topics))
        time.sleep(1)
    return out


# ----------------------------- 论文 -----------------------------

def fetch_conf_news(days):
    return fetch_news(max(days, 7), CONF_NEWS_EN, CONF_NEWS_ZH, kind="confnews")


def fetch_pubmed(days):
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    key = os.getenv("NCBI_API_KEY")
    p = dict(db="pubmed", term=PUBMED_QUERY, reldate=days, datetype="edat", retmax=PUBMED_MAX, retmode="json")
    if key:
        p["api_key"] = key
    js = get_json(base + "esearch.fcgi?" + urllib.parse.urlencode(p))
    ids = (js or {}).get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    p2 = dict(db="pubmed", id=",".join(ids), retmode="xml")
    if key:
        p2["api_key"] = key
    raw = get(base + "efetch.fcgi", data=urllib.parse.urlencode(p2).encode())
    if not raw:
        return []
    out = []
    for art in ET.fromstring(raw).iter("PubmedArticle"):
        pmid = art.findtext(".//PMID")
        a = art.find(".//Article")
        if a is None or a.find("ArticleTitle") is None:
            continue
        title = "".join(a.find("ArticleTitle").itertext())
        journal = a.findtext("Journal/ISOAbbreviation") or a.findtext("Journal/Title") or "PubMed"
        abstract = " ".join("".join(x.itertext()) for x in a.findall(".//AbstractText"))
        affs = [" ".join(x.text or "" for x in au.findall("AffiliationInfo/Affiliation"))
                for au in a.findall("AuthorList/Author")]
        region = "cn" if affs and (is_cn_affil(affs[0]) or is_cn_affil(affs[-1])) else "global"
        out.append(item("paper", region, title, f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        f"PubMed · {journal}", summary=abstract, topics=tag(title + " " + abstract)))
    return out


def fetch_rxiv(days):
    end = dt.datetime.now(BJT).date()
    start = end - dt.timedelta(days=days)
    out = []
    for server, cats in RXIV_CATS.items():
        cursor = 0
        while cursor < 5000:
            js = get_json(f"https://api.biorxiv.org/details/{server}/{start}/{end}/{cursor}")
            coll = (js or {}).get("collection", [])
            for p in coll:
                if p.get("category", "").strip().lower() not in cats or str(p.get("version")) != "1":
                    continue
                text = p.get("title", "") + " " + p.get("abstract", "")
                topics = tag(text)
                if not topics:          # 预印本量大，只保留命中具体主题的
                    continue
                region = "cn" if is_cn_affil(p.get("author_corresponding_institution")) else "global"
                out.append(item("paper", region, p.get("title"),
                                f"https://www.{server}.org/content/{p.get('doi')}v1",
                                f"{'bioRxiv' if server == 'biorxiv' else 'medRxiv'} · {p.get('category')}",
                                p.get("date", ""), p.get("abstract", ""), topics))
            if len(coll) < 100:
                break
            cursor += len(coll)
            time.sleep(0.5)
    return out


def fetch_arxiv(days):
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(dict(
        search_query=ARXIV_QUERY, sortBy="submittedDate", sortOrder="descending", max_results=ARXIV_MAX))
    raw = get(url)
    if not raw:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days + 1)).strftime("%Y-%m-%d")
    out = []
    for e in ET.fromstring(raw).findall("a:entry", ns):
        pub = (e.findtext("a:published", "", ns) or "")[:10]
        if pub < since:
            continue
        title = e.findtext("a:title", "", ns)
        summ = e.findtext("a:summary", "", ns)
        affs = " ".join(x.text or "" for x in e.findall(".//x:affiliation", ns))
        out.append(item("paper", "cn" if is_cn_affil(affs) else "global", title,
                        e.findtext("a:id", "", ns), "arXiv", pub, summ, tag(title + " " + summ)))
    return out


# ----------------------------- 输出 -----------------------------

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--fg:#1d1d1f;--mute:#6b6b70;--line:#e4e4e0;--acc:#2b59c3;--chip:#eef2fb}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1e1e21;--fg:#ececef;--mute:#9a9aa2;--line:#2e2e33;--acc:#7ea2ff;--chip:#24293a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif}
.wrap{max-width:820px;margin:0 auto;padding:16px}
h1{font-size:22px;margin:4px 0 2px}.sub{color:var(--mute);font-size:13px;margin-bottom:14px}
.bar{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
button{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;padding:6px 14px;font-size:14px;cursor:pointer}
button.on{background:var(--acc);border-color:var(--acc);color:#fff}
.tabs button{font-size:16px;padding:8px 20px;font-weight:600}
h2{font-size:16px;margin:22px 0 8px;color:var(--mute)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:8px 0}
.card a{color:var(--fg);text-decoration:none;font-weight:600}.card a:hover{color:var(--acc)}
.meta{color:var(--mute);font-size:12.5px;margin-top:4px}
.chips{margin-bottom:4px}.chip{display:inline-block;background:var(--chip);color:var(--acc);font-size:11.5px;border-radius:6px;padding:1px 7px;margin-right:4px}
details{margin-top:6px;font-size:13.5px;color:var(--mute)}summary{cursor:pointer}
h3{font-size:14px;margin:14px 0 6px;color:var(--mute)}.full{color:var(--mute);font-size:13px}
.meta b{color:var(--fg)}.meta b.hot,b.hot{color:#d9480f}
.empty{color:var(--mute);font-size:14px;padding:6px 2px}
footer{margin:30px 0 10px;color:var(--mute);font-size:13px}footer a{color:var(--acc);margin-right:10px}
[hidden]{display:none!important}
"""

JS = """
let region='cn',topic='全部';
function apply(){
 document.querySelectorAll('.panel').forEach(p=>p.hidden=p.id!==region);
 document.querySelectorAll('.card').forEach(c=>c.hidden=topic!=='全部'&&!c.dataset.topics.split(' ').includes(topic));
 document.querySelectorAll('[data-region]').forEach(b=>b.classList.toggle('on',b.dataset.region===region));
 document.querySelectorAll('[data-topic]').forEach(b=>b.classList.toggle('on',b.dataset.topic===topic));
}
document.querySelectorAll('[data-region]').forEach(b=>b.onclick=()=>{region=b.dataset.region;apply()});
document.querySelectorAll('[data-topic]').forEach(b=>b.onclick=()=>{topic=b.dataset.topic;apply()});
apply();
"""


def esc(s):
    return html.escape(s or "", quote=True)


def card(it):
    chips = "".join(f'<span class="chip">{esc(t)}</span>' for t in it["topics"])
    meta = " · ".join(x for x in (it["source"], it["date"]) if x)
    summ = f'<details><summary>摘要</summary><p>{esc(it["summary"])}</p></details>' if it["summary"] else ""
    return (f'<article class="card" data-topics="{esc(" ".join(it["topics"]))}"><div class="chips">{chips}</div>'
            f'<a href="{esc(it["url"])}" target="_blank" rel="noopener">{esc(it["title"])}</a>'
            f'<div class="meta">{esc(meta)}</div>{summ}</article>')


MANIFEST = {
    "name": "NeuroDaily 脑科学日报", "short_name": "脑科学日报",
    "start_url": "./", "scope": "./", "display": "standalone",
    "background_color": "#f7f7f5", "theme_color": "#2b59c3",
    "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
              {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"}],
}


def conf_cards(reg, today):
    t = dt.date.fromisoformat(today)
    rows = []
    for c in CONFERENCES:
        if c["region"] != reg:
            continue
        s, e = dt.date.fromisoformat(c["start"]), dt.date.fromisoformat(c["end"])
        if e < t:
            continue
        if s <= t:
            when = '<b class="hot">正在召开</b>'
        else:
            when = f'还有 <b>{(s - t).days}</b> 天'
        dls = [(n, dt.date.fromisoformat(d)) for n, d in c.get("deadlines", [])]
        dls = [f'{esc(n)} {d:%m-%d}（{"<b class=hot>" if (d - t).days <= 30 else "<b>"}{(d - t).days}</b> 天）'
               for n, d in dls if d >= t]
        dl = f'<div class="meta">⏰ {"；".join(dls)}</div>' if dls else ""
        rows.append((s, f'<article class="card" data-topics="会议"><div class="chips"><span class="chip">会议</span></div>'
                        f'<a href="{esc(c["url"])}" target="_blank" rel="noopener">{esc(c["name"])}</a>'
                        f'<span class="full"> · {esc(c["full"])}</span>'
                        f'<div class="meta">📅 {s:%Y-%m-%d} ~ {e:%m-%d} · 📍 {esc(c["city"])} · {when}</div>{dl}</article>'))
    rows.sort(key=lambda r: r[0])
    return "".join(r[1] for r in rows)


def render(items, day, archive_dates, link_prefix, asset=""):
    order = list(TOPICS) + [FALLBACK_TOPIC, "会议"]
    tabs, panels = [], []
    for reg, name in (("cn", "中国"), ("global", "全球")):
        mine = [i for i in items if i["region"] == reg]
        tabs.append(f'<button data-region="{reg}">{name} ({len(mine)})</button>')
        body = []
        for kind, label in (("news", "新闻"), ("paper", "论文 / 预印本")):
            lst = [i for i in mine if i["kind"] == kind]
            if kind == "news":
                lst.sort(key=lambda i: i["date"], reverse=True)
            else:
                lst.sort(key=lambda i: order.index(i["topics"][0]) if i["topics"][0] in order else 99)
            body.append(f"<h2>{label}（{len(lst)}）</h2>")
            body.append("".join(card(i) for i in lst) or '<div class="empty">今天没有新内容</div>')
        confs = conf_cards(reg, day)
        cnews = sorted((i for i in mine if i["kind"] == "confnews"), key=lambda i: i["date"], reverse=True)
        body.append("<h2>会议 · 脑图像处理 / 神经影像</h2>")
        body.append(confs or '<div class="empty">暂无即将召开的会议（可在脚本配置区 CONFERENCES 中补充）</div>')
        if cnews:
            body.append(f'<h3>会议动态（{len(cnews)}）</h3>' + "".join(card(i) for i in cnews))
        panels.append(f'<section class="panel" id="{reg}">{"".join(body)}</section>')
    topic_btns = "".join(f'<button data-topic="{esc(t)}">{esc(t)}</button>' for t in ["全部"] + order)
    arch = "".join(f'<a href="{link_prefix}{d}.html">{d}</a>' for d in archive_dates)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>脑科学日报</title>
<link rel="manifest" href="{asset}manifest.json"><link rel="apple-touch-icon" href="{asset}icon-192.png">
<link rel="icon" href="{asset}icon-192.png"><meta name="theme-color" content="#2b59c3">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="脑科学日报">
<style>{CSS}</style></head><body><div class="wrap">
<h1>NeuroDaily 脑科学日报</h1>
<div class="sub">{day} · MEG / EEG / MRI / fMRI / 脑机接口 / 神经科学 / 会议 · 共 {len(items)} 条新内容</div>
<div class="bar tabs">{"".join(tabs)}</div>
<div class="bar">{topic_btns}</div>
{"".join(panels)}
<footer>往期：{arch or "暂无"}<br><br>来源：Google News · PubMed · bioRxiv · medRxiv · arXiv。中国/全球为自动判断，仅供参考。</footer>
</div><script>{JS}</script></body></html>"""


def push_wechat(items, day):
    key = os.getenv("SERVERCHAN_KEY")
    if not key:
        return
    page = os.getenv("PAGE_URL", "")
    lines = []
    for reg, name in (("cn", "中国"), ("global", "全球")):
        news = [i for i in items if i["region"] == reg and i["kind"] == "news"]
        papers = [i for i in items if i["region"] == reg and i["kind"] == "paper"]
        lines.append(f"### {name}：新闻 {len(news)} 条 · 论文 {len(papers)} 篇")
        lines += [f"- [{i['title']}]({i['url']})" for i in news[:8]]
        lines.append("")
    t = dt.date.fromisoformat(day)
    up = sorted((c for c in CONFERENCES if dt.date.fromisoformat(c["end"]) >= t), key=lambda c: c["start"])[:3]
    if up:
        lines.append("### 近期会议")
        lines += [f"- {c['name']}（{c['start']}，{c['city']}）" for c in up]
        lines.append("")
    if page:
        lines.append(f"[查看完整日报]({page})")
    data = urllib.parse.urlencode({"title": f"NeuroDaily {day}", "desp": "\n".join(lines)}).encode()
    get(f"https://sctapi.ftqq.com/{key}.send", data=data)
    log("已推送到微信")


def norm_key(title):
    return re.sub(r"[\W_]+", "", title.lower())[:60]


def main():
    ap = argparse.ArgumentParser(description="NeuroDaily 脑科学日报")
    ap.add_argument("--days", type=int, default=2, help="回看天数（配合去重，默认 2）")
    ap.add_argument("--out", default="docs", help="输出目录（默认 docs，可直接给 GitHub Pages 用）")
    args = ap.parse_args()

    out = Path(args.out)
    (out / "archive").mkdir(parents=True, exist_ok=True)
    (out / "data").mkdir(parents=True, exist_ok=True)
    today = dt.datetime.now(BJT).strftime("%Y-%m-%d")

    items = []
    for name, fn in (("Google News", fetch_news), ("PubMed", fetch_pubmed),
                     ("bioRxiv/medRxiv", fetch_rxiv), ("arXiv", fetch_arxiv), ("会议动态", fetch_conf_news)):
        log(f"抓取 {name} …")
        try:
            got = fn(args.days)
        except Exception as e:  # noqa: BLE001  单个来源失败不影响其他来源
            log(f"  ! {name} 出错：{e}")
            got = []
        n0 = len(got)
        got = [i for i in got if not is_heart(i["title"])]
        log(f"  {len(got)} 条" + (f"（剔除心脏相关 {n0 - len(got)} 条）" if n0 > len(got) else ""))
        items += got

    seen_file = out / "data" / "seen.json"
    seen = json.loads(seen_file.read_text("utf-8")) if seen_file.exists() else {}
    fresh, keys = [], set()
    for it in items:
        k = norm_key(it["title"])
        if not k or k in keys:
            continue
        keys.add(k)
        if k in seen and seen[k] != today:   # 以前日报里出现过
            continue
        seen[k] = today
        fresh.append(it)
    cutoff = (dt.datetime.now(BJT) - dt.timedelta(days=KEEP_SEEN_DAYS)).strftime("%Y-%m-%d")
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    seen_file.write_text(json.dumps(seen, ensure_ascii=False), "utf-8")

    (out / "data" / f"{today}.json").write_text(json.dumps(fresh, ensure_ascii=False, indent=1), "utf-8")
    dates = sorted((p.stem for p in (out / "archive").glob("*.html")), reverse=True)
    dates = sorted(set(dates) | {today}, reverse=True)[:30]
    (out / "archive" / f"{today}.html").write_text(render(fresh, today, dates, "", "../"), "utf-8")
    (out / "manifest.json").write_text(json.dumps(MANIFEST, ensure_ascii=False, indent=1), "utf-8")
    (out / "index.html").write_text(render(fresh, today, dates, "archive/"), "utf-8")

    cn = sum(i["region"] == "cn" for i in fresh)
    log(f"完成：{len(fresh)} 条新内容（中国 {cn} / 全球 {len(fresh) - cn}）→ {out / 'index.html'}")
    push_wechat(fresh, today)


if __name__ == "__main__":
    main()
