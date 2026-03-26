"""
generate_site.py — 静的サイトジェネレーター

data/articles.json と data/glossary.json を読み込み、
site/ ディレクトリに以下を生成する:

  site/
    index.html      トップページ（最新記事一覧）
    search.html     全文検索ページ（クライアントサイドJS）
    glossary.html   用語集インデックス
    articles/
      {id}.html     記事詳細ページ（出典リンク必須）
    data/
      articles.json  検索用データ（search.htmlが参照）
      glossary.json  用語データ（glossary.htmlが参照）

使い方:
  python generate_site.py              # 全ページ生成
  python generate_site.py --watch      # ファイル変更を監視して自動再生成
  python generate_site.py --output ./dist  # 出力先を指定
"""

import argparse
import json
import logging
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from html import escape

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("generate_site")

# ── パス設定 ──────────────────────────────────────────
ROOT        = Path(__file__).parent
DATA_DIR    = ROOT / "data"
ARTICLES_DB = DATA_DIR / "articles.json"
GLOSSARY_DB = DATA_DIR / "glossary.json"

# ── デザイントークン（Pythonから埋め込むCSS変数） ────────
DESIGN_TOKENS = """
  --sand:       #F4EDE0;
  --sand-2:     #EDE4D2;
  --sand-3:     #E2D6C0;
  --ink:        #1C1410;
  --ink-mid:    #4A3E30;
  --ink-muted:  #9A8E7E;
  --gold:       #8C6E3C;
  --gold-pale:  rgba(140,110,60,0.12);
  --green:      #1A4A2E;
  --green-pale: rgba(26,74,46,0.08);
  --red:        #8B2215;
  --red-pale:   rgba(139,34,21,0.08);
  --amber:      #7A5200;
  --amber-pale: rgba(122,82,0,0.08);
  --blue:       #1A3A6B;
  --blue-pale:  rgba(26,58,107,0.08);
  --border:     rgba(28,20,16,0.09);
  --border-mid: rgba(28,20,16,0.15);
  --radius:     10px;
  --radius-sm:  6px;
  --serif:      'Cormorant Garamond', 'Hiragino Mincho ProN', serif;
  --body-serif: 'Noto Serif JP', 'Hiragino Mincho ProN', serif;
  --sans:       'Noto Sans JP', -apple-system, 'Hiragino Sans', sans-serif;
  --mono:       'SF Mono', 'Courier New', monospace;
"""

# ── ヘルパー ──────────────────────────────────────────

def e(text: str) -> str:
    """HTMLエスケープのショートカット"""
    return escape(str(text or ""), quote=True)

def load_json(path: Path) -> list:
    if not path.exists():
        logger.warning(f"ファイルが存在しません: {path}")
        return []
    return json.loads(path.read_text(encoding="utf-8"))

def format_date(iso: str) -> str:
    """ISO8601をJST表記に変換"""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y年%-m月%-d日")
    except Exception:
        return iso[:10] if iso else ""

def alert_label(level: str) -> str:
    labels = {"urgent": "緊急", "high": "重要", "medium": "注目", "low": ""}
    return labels.get(level, "")

def alert_class(level: str) -> str:
    return {"urgent": "badge-light-urgent", "high": "badge-light-high",
            "medium": "badge-light-medium", "low": ""}.get(level, "")

def cat_label(cat: str) -> str:
    labels = {
        "safety": "安全・治安", "visa": "ビザ・在留",
        "healthcare": "医療・健康", "business": "ビジネス",
        "daily_life": "生活", "education": "教育",
        "culture": "文化・宗教", "news_general": "ニュース",
    }
    return labels.get(cat, cat)

def tier_label(tier: int) -> str:
    return {1: "Tier 1（公式）", 2: "Tier 2（主要メディア）",
            3: "Tier 3（コミュニティ精査済）"}.get(tier, f"Tier {tier}")

def tier_color(tier: int) -> str:
    return {1: "var(--red)", 2: "var(--amber)", 3: "var(--blue)"}.get(tier, "var(--ink-muted)")

# ── 共通HTML部品 ──────────────────────────────────────

GOOGLE_FONTS = (
    "https://fonts.googleapis.com/css2?"
    "family=Cormorant+Garamond:ital,wght@0,300;0,400;1,300;1,400"
    "&family=Noto+Serif+JP:wght@300;400"
    "&family=Noto+Sans+JP:wght@300;400;500"
    "&display=swap"
)

BASE_CSS = f"""
<style>
:root {{ {DESIGN_TOKENS} }}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html{{-webkit-text-size-adjust:100%}}
body{{background:var(--sand);color:var(--ink);font-family:var(--sans);
  font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased}}
a{{color:inherit;text-decoration:none}}
button{{font-family:inherit;cursor:pointer}}
.geo-stripe{{height:3px;background:repeating-linear-gradient(90deg,
  var(--gold) 0px,var(--gold) 3px,var(--sand-3) 3px,var(--sand-3) 5px,
  var(--green) 5px,var(--green) 8px,var(--sand-3) 8px,var(--sand-3) 10px,
  var(--gold) 10px,var(--gold) 13px,var(--sand) 13px,var(--sand) 18px);opacity:0.6}}
header{{position:sticky;top:0;z-index:200;
  background:rgba(244,237,224,0.88);
  backdrop-filter:blur(20px) saturate(1.6);
  -webkit-backdrop-filter:blur(20px) saturate(1.6);
  border-bottom:0.5px solid var(--border)}}
.header-inner{{max-width:1160px;margin:0 auto;padding:0 24px;height:56px;
  display:flex;align-items:center;gap:24px}}
.logo{{display:flex;align-items:center;gap:10px;flex-shrink:0}}
.logo-icon{{width:30px;height:30px}}
.logo-ja{{font-family:var(--body-serif);font-size:14px;color:var(--ink);letter-spacing:.02em}}
.logo-ar{{font-family:var(--serif);font-size:11px;color:var(--gold);letter-spacing:.04em}}
nav.main-nav{{display:flex;gap:2px;flex:1}}
nav.main-nav a{{font-size:12px;color:var(--ink-muted);padding:5px 11px;
  border-radius:99px;transition:all .15s ease-out;white-space:nowrap}}
nav.main-nav a:hover{{color:var(--ink);background:var(--sand-2)}}
nav.main-nav a.active{{background:var(--ink);color:var(--sand)}}
.last-update{{font-size:10px;color:var(--ink-muted);flex-shrink:0}}
main{{max-width:1160px;margin:0 auto;padding:28px 24px 60px}}
.section-label{{font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-muted);margin-bottom:14px;display:flex;align-items:center;gap:8px}}
.section-label::after{{content:'';flex:1;height:0.5px;background:var(--border)}}
.badge{{font-size:10px;padding:2px 8px;border-radius:3px;letter-spacing:.04em;
  display:inline-flex;align-items:center;gap:4px}}
.badge-light-urgent{{background:var(--red-pale);color:var(--red)}}
.badge-light-high{{background:var(--amber-pale);color:var(--amber)}}
.badge-light-medium{{background:var(--blue-pale);color:var(--blue)}}
.badge-light-cat{{background:var(--gold-pale);color:var(--gold)}}
.badge-light-green{{background:var(--green-pale);color:var(--green)}}
.tier-dot{{width:4px;height:4px;border-radius:50%;flex-shrink:0;display:inline-block}}
.tier-1{{background:var(--red)}}
.tier-2{{background:var(--amber)}}
.tier-3{{background:var(--blue)}}
.source-link{{display:inline-flex;align-items:center;gap:4px;
  color:var(--green);font-size:11px;
  border-bottom:0.5px solid rgba(26,74,46,0.3);
  transition:border-color .15s}}
.source-link:hover{{border-color:var(--green)}}
footer{{border-top:0.5px solid var(--border);padding:20px 24px}}
.footer-inner{{max-width:1160px;margin:0 auto;display:flex;
  justify-content:space-between;gap:16px;flex-wrap:wrap}}
.footer-note{{font-size:10px;color:var(--ink-muted);line-height:1.6}}
.mobile-nav{{display:none;position:fixed;bottom:0;left:0;right:0;
  background:rgba(244,237,224,0.94);
  backdrop-filter:blur(20px) saturate(1.6);
  -webkit-backdrop-filter:blur(20px) saturate(1.6);
  border-top:0.5px solid var(--border);
  padding:8px 0 calc(8px + env(safe-area-inset-bottom));z-index:300}}
.mobile-nav-inner{{display:grid;grid-template-columns:repeat(5,1fr)}}
.mob-tab{{display:flex;flex-direction:column;align-items:center;gap:3px;
  padding:4px 0;background:none;border:none;color:var(--ink-muted);font-size:10px}}
.mob-tab.active{{color:var(--green)}}
.mob-tab svg{{width:22px;height:22px}}
@keyframes fadeIn{{from{{opacity:0;transform:translateY(6px)}}to{{opacity:1;transform:none}}}}
@media(max-width:600px){{
  .header-inner{{height:44px;padding:0 16px}}
  .logo-ar{{display:none}}
  nav.main-nav{{display:none}}
  .last-update{{display:none}}
  main{{padding:16px 16px 100px}}
  .mobile-nav{{display:block}}
  .geo-stripe{{height:2px}}
}}
</style>"""


def html_head(title: str, description: str = "", path_to_root: str = "") -> str:
    canon = ""
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{e(title)} — 在サウジ邦人ポータル</title>
<meta name="description" content="{e(description or title)}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="{GOOGLE_FONTS}" rel="stylesheet">
{BASE_CSS}
</head>
<body>"""


def html_header(active_page: str = "top", path_prefix: str = "") -> str:
    p = path_prefix
    pages = [
        ("top",      f"{p}index.html",    "すべて"),
        ("search",   f"{p}search.html",   "検索"),
        ("glossary", f"{p}glossary.html", "用語集"),
    ]
    nav_items = "".join(
        f'<a href="{url}" class="{"active" if key == active_page else ""}">{label}</a>'
        for key, url, label in pages
    )
    now_jst = datetime.now().strftime("%m/%d %H:%M")
    return f"""
<header>
  <div class="header-inner">
    <a class="logo" href="{p}index.html">
      <svg class="logo-icon" viewBox="0 0 30 30" fill="none">
        <polygon points="15,2 17.9,10.6 27,10.6 19.6,15.8 22.5,24.5 15,19.3 7.5,24.5 10.4,15.8 3,10.6 12.1,10.6"
          stroke="#8C6E3C" stroke-width="0.8" fill="none"/>
        <circle cx="15" cy="15" r="4.5" stroke="#8C6E3C" stroke-width="0.6" fill="none"/>
        <circle cx="15" cy="15" r="1.5" fill="#8C6E3C" opacity="0.4"/>
      </svg>
      <div>
        <div class="logo-ja">在サウジ邦人ポータル</div>
        <div class="logo-ar">في السعودية</div>
      </div>
    </a>
    <nav class="main-nav">{nav_items}</nav>
    <span class="last-update">更新 {now_jst}</span>
  </div>
</header>
<div class="geo-stripe"></div>"""


def html_mobile_nav(active: str = "top", path_prefix: str = "") -> str:
    p = path_prefix
    tabs = [
        ("top",      f"{p}index.html",    "すべて",   '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="12" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="12" width="7" height="7" rx="1.5"/><rect x="12" y="12" width="7" height="7" rx="1.5"/>'),
        ("search",   f"{p}search.html",   "検索",     '<circle cx="10" cy="10" r="7"/><line x1="15.5" y1="15.5" x2="19" y2="19"/>'),
        ("glossary", f"{p}glossary.html", "用語集",   '<path d="M4 4h14v14H4z" rx="2"/><line x1="7" y1="8" x2="15" y2="8"/><line x1="7" y1="12" x2="12" y2="12"/>'),
        ("safety",   f"{p}index.html#safety", "安全", '<circle cx="11" cy="11" r="8"/><line x1="11" y1="7" x2="11" y2="11"/><circle cx="11" cy="15" r="0.8" fill="currentColor" stroke="none"/>'),
        ("visa",     f"{p}index.html#visa",   "ビザ",  '<rect x="5" y="2" width="12" height="18" rx="2"/><line x1="8" y1="7" x2="14" y2="7"/><line x1="8" y1="11" x2="14" y2="11"/>'),
    ]
    items = "".join(
        f'<a class="mob-tab {"active" if k==active else ""}" href="{url}">'
        f'<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round">{svg}</svg>'
        f'<span style="font-size:9px">{label}</span></a>'
        for k, url, label, svg in tabs
    )
    return f'<nav class="mobile-nav"><div class="mobile-nav-inner">{items}</div></nav>'


def html_footer() -> str:
    return """
<footer>
  <div class="footer-inner">
    <div class="footer-note">
      © 2026 在サウジ邦人ポータル — 掲載情報は参考目的です。<br>
      重要な判断は必ず出典（情報源リンク）および公式機関でご確認ください。
    </div>
    <div class="footer-note">AIエージェントによる自動収集 + 編集部による精査</div>
  </div>
</footer>"""


def article_card_html(a: dict, path_prefix: str = "") -> str:
    """記事カードHTML。出典リンクを必ず含む。"""
    lvl   = a.get("alert_level", "low")
    label = alert_label(lvl)
    badge = f'<span class="badge {alert_class(lvl)}">{e(label)}</span>' if label else ""
    cat   = cat_label(a.get("category_main", ""))
    tier  = a.get("source_tier", 2)
    url   = a.get("source_url", "") or ""
    sname = a.get("source_name", "")
    art_url = f'{path_prefix}articles/{e(a["id"])}.html'

    source_block = ""
    if url and url != "#":
        source_block = (
            f'<div style="margin-top:8px;padding-top:8px;border-top:0.5px solid var(--border);'
            f'display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
            f'<span class="tier-dot tier-{tier}" title="{e(tier_label(tier))}"></span>'
            f'<span style="font-size:10px;color:var(--ink-muted)">{e(sname)}</span>'
            f'<a href="{e(url)}" target="_blank" rel="noopener noreferrer" class="source-link">'
            f'出典を確認 ↗</a></div>'
        )

    return f"""
<article style="background:white;border:0.5px solid var(--border);border-radius:var(--radius);
  padding:15px 16px;margin-bottom:8px;animation:fadeIn .3s ease-out both">
  <div style="display:flex;align-items:center;gap:5px;margin-bottom:7px;flex-wrap:wrap">
    {badge}
    <span class="badge badge-light-cat">{e(cat)}</span>
    <span style="font-size:10px;color:var(--ink-muted);margin-left:auto">
      {format_date(a.get("published_at",""))}
    </span>
  </div>
  <h2 style="font-family:var(--body-serif);font-size:14px;font-weight:400;
    color:var(--ink);line-height:1.55;margin-bottom:5px">
    <a href="{art_url}" style="color:inherit">{e(a.get("title_ja",""))}</a>
  </h2>
  <p style="font-size:11px;color:var(--ink-muted);line-height:1.65">
    {e(a.get("lead_ja",""))}
  </p>
  {source_block}
</article>"""


# ── ページ生成関数 ────────────────────────────────────

def build_index(articles: list, out_dir: Path) -> None:
    """トップページ (index.html) を生成する。"""
    # アラートレベルでソート
    order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    sorted_arts = sorted(articles, key=lambda x: (order.get(x.get("alert_level","low"),3), -x.get("score",0)))
    top    = sorted_arts[:1]
    rest   = sorted_arts[1:9]

    # フィーチャード記事
    featured_html = ""
    if top:
        a   = top[0]
        url = a.get("source_url","") or ""
        sname = a.get("source_name","")
        src_link = (f'<a href="{e(url)}" target="_blank" rel="noopener" style="color:#A8D4B8;font-size:11px;border-bottom:0.5px solid rgba(168,212,184,0.4);">出典を確認 ↗</a>') if url and url != "#" else ""
        featured_html = f"""
<a href="articles/{e(a['id'])}.html" style="display:block;text-decoration:none">
<article style="background:var(--ink);border-radius:var(--radius);padding:22px;
  margin-bottom:10px;position:relative;overflow:hidden;cursor:pointer">
  <svg style="position:absolute;top:-16px;right:-16px;opacity:.04;pointer-events:none"
    width="140" height="140" viewBox="0 0 140 140" fill="none">
    <polygon points="70,5 83,47 126,47 92,72 105,114 70,89 35,114 48,72 14,47 57,47"
      stroke="white" stroke-width="0.6"/>
    <circle cx="70" cy="70" r="22" stroke="white" stroke-width="0.4"/>
  </svg>
  <div style="display:flex;gap:5px;margin-bottom:11px">
    <span class="badge" style="background:rgba(255,120,100,.18);color:#FF8A78">{e(alert_label(a.get("alert_level","low")))}</span>
    <span class="badge" style="background:rgba(255,255,255,.35);color:#FFFFFF">{e(cat_label(a.get("category_main","")))}</span>
  </div>
  <h2 style="font-family:var(--body-serif);font-size:17px;font-weight:300;
    color:var(--sand);line-height:1.55;margin-bottom:9px">{e(a.get("title_ja",""))}</h2>
  <p style="font-size:12px;color:#F0E6CC;line-height:1.7;margin-bottom:14px">
    {e(a.get("lead_ja",""))}</p>
  <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
    <span style="font-size:11px;color:#7FDBA0;letter-spacing:.04em">詳細を読む →</span>
    <div style="display:flex;align-items:center;gap:6px">
      <span class="tier-dot tier-{a.get('source_tier',2)}"
        style="width:5px;height:5px" title="{e(tier_label(a.get('source_tier',2)))}"></span>
      <span style="font-size:10px;color:#C8BAA0">{e(sname)}</span>
      {src_link}
    </div>
  </div>
</article>
</a>"""

    rest_html = "".join(article_card_html(a) for a in rest)

    # 統計
    total   = len(articles)
    urgent  = sum(1 for a in articles if a.get("alert_level") == "urgent")
    high    = sum(1 for a in articles if a.get("alert_level") == "high")

    html = (
        html_head("在サウジ邦人ポータル", "サウジアラビア在住日本人向けの情報ポータル")
        + html_header("top")
        + f"""
<main>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:24px">
    <div style="background:white;border:0.5px solid var(--border);border-radius:var(--radius);padding:13px 16px">
      <div style="font-size:10px;color:var(--ink-muted);letter-spacing:.06em;text-transform:uppercase;margin-bottom:4px">総記事数</div>
      <div style="font-family:var(--serif);font-size:24px;font-weight:300">{total}</div>
    </div>
    <div style="background:white;border:0.5px solid var(--border);border-radius:var(--radius);padding:13px 16px">
      <div style="font-size:10px;color:var(--ink-muted);letter-spacing:.06em;text-transform:uppercase;margin-bottom:4px">緊急情報</div>
      <div style="font-family:var(--serif);font-size:24px;font-weight:300;color:var(--red)">{urgent}</div>
    </div>
    <div style="background:white;border:0.5px solid var(--border);border-radius:var(--radius);padding:13px 16px">
      <div style="font-size:10px;color:var(--ink-muted);letter-spacing:.06em;text-transform:uppercase;margin-bottom:4px">重要情報</div>
      <div style="font-family:var(--serif);font-size:24px;font-weight:300;color:var(--amber)">{high}</div>
    </div>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:16px">
    <a href="search.html" style="display:inline-flex;align-items:center;gap:6px;
      background:white;border:0.5px solid var(--border-mid);border-radius:99px;
      padding:6px 16px;font-size:12px;color:var(--ink-muted);transition:all .15s">
      <svg width="12" height="12" viewBox="0 0 22 22" fill="none" stroke="currentColor"
        stroke-width="1.5" stroke-linecap="round">
        <circle cx="10" cy="10" r="7"/><line x1="15.5" y1="15.5" x2="19" y2="19"/>
      </svg>過去の記事を検索</a>
    <a href="glossary.html" style="display:inline-flex;align-items:center;gap:6px;
      background:white;border:0.5px solid var(--border-mid);border-radius:99px;
      padding:6px 16px;font-size:12px;color:var(--ink-muted);transition:all .15s">
      📖 用語を調べる</a>
  </div>
  <div style="display:grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:20px">
    <div>
      <div class="section-label">最新・重要記事</div>
      {featured_html}
      {"".join(article_card_html(a) for a in rest[:3])}
    </div>
    <div>
      <div class="section-label">生活・実務情報</div>
      {"".join(article_card_html(a) for a in rest[3:])}
    </div>
  </div>
</main>"""
        + html_mobile_nav("top")
        + html_footer()
        + "</body></html>"
    )

    (out_dir / "index.html").write_text(html, encoding="utf-8")
    logger.info("生成: index.html")


def build_article(a: dict, out_dir: Path) -> None:
    """記事詳細ページ (articles/{id}.html) を生成する。"""
    art_dir = out_dir / "articles"
    art_dir.mkdir(exist_ok=True)

    lvl   = a.get("alert_level","low")
    label = alert_label(lvl)
    badge = f'<span class="badge {alert_class(lvl)}">{e(label)}</span>' if label else ""
    cat   = cat_label(a.get("category_main",""))
    tier  = a.get("source_tier", 2)
    url   = a.get("source_url","") or ""
    sname = a.get("source_name","")
    tags  = a.get("tags",[])

    # 出典リンクブロック（記事詳細では強調表示）
    source_block = f"""
<div style="background:white;border:0.5px solid var(--border);border-radius:var(--radius);
  padding:16px;margin-top:24px">
  <div style="font-size:10px;letter-spacing:.1em;text-transform:uppercase;
    color:var(--ink-muted);margin-bottom:10px">情報源・出典</div>
  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
    <span class="tier-dot tier-{tier}" style="width:6px;height:6px"
      title="{e(tier_label(tier))}"></span>
    <span style="font-size:13px;color:var(--ink-mid)">{e(sname)}</span>
    <span style="font-size:11px;color:var(--ink-muted)">（{e(tier_label(tier))}）</span>
  </div>
  {f'<div style="margin-top:10px"><a href="{e(url)}" target="_blank" rel="noopener noreferrer" '
    f'class="source-link" style="font-size:13px">出典ページを開く ↗</a></div>'
    if url and url != "#" else
    '<div style="margin-top:6px;font-size:11px;color:var(--ink-muted)">この記事の出典URLは記録されていません。</div>'}
  <div style="margin-top:8px;font-size:10px;color:var(--ink-muted)">
    収集日時: {e(a.get("collected_at","")[:16])}
  </div>
</div>"""

    # アクション
    action_html = ""
    if a.get("action_ja"):
        action_html = f"""
<div style="margin-top:20px;padding:14px 16px;background:var(--green-pale);
  border-left:2px solid var(--green);border-radius:0 var(--radius-sm) var(--radius-sm) 0;
  font-size:13px;color:var(--green);line-height:1.6">
  {e(a.get("action_ja",""))}
</div>"""

    # タグ
    tags_html = ""
    if tags:
        tags_html = '<div style="display:flex;gap:5px;flex-wrap:wrap;margin-top:16px">' + \
            "".join(f'<span class="badge badge-light-cat">{e(t)}</span>' for t in tags) + \
            "</div>"

    html = (
        html_head(a.get("title_ja",""), a.get("lead_ja",""), "../")
        + html_header("top", "../")
        + f"""
<main style="max-width:720px;margin:0 auto;padding:28px 24px 60px">
  <a href="../index.html" style="display:inline-flex;align-items:center;gap:5px;
    font-size:11px;color:var(--ink-muted);margin-bottom:20px;
    transition:color .15s" onmouseover="this.style.color='var(--ink)'"
    onmouseout="this.style.color='var(--ink-muted)'">← 一覧に戻る</a>

  <div style="display:flex;gap:5px;margin-bottom:12px;flex-wrap:wrap">
    {badge}
    <span class="badge badge-light-cat">{e(cat)}</span>
    <span style="font-size:10px;color:var(--ink-muted)">
      {format_date(a.get("published_at",""))}
    </span>
  </div>

  <h1 style="font-family:var(--body-serif);font-size:22px;font-weight:400;
    color:var(--ink);line-height:1.5;margin-bottom:12px">
    {e(a.get("title_ja",""))}</h1>

  <p style="font-size:15px;color:var(--ink-mid);line-height:1.75;
    font-family:var(--body-serif);margin-bottom:20px;
    border-bottom:0.5px solid var(--border);padding-bottom:20px">
    {e(a.get("lead_ja",""))}</p>

  <div style="font-size:14px;color:var(--ink-mid);line-height:1.85;
    white-space:pre-line">
    {e(a.get("body_ja",""))}</div>

  {action_html}
  {tags_html}
  {source_block}

  <div style="margin-top:24px;padding-top:16px;border-top:0.5px solid var(--border)">
    <a href="../glossary.html" style="font-size:12px;color:var(--gold);
      border-bottom:0.5px solid rgba(140,110,60,.3)">
      分からない用語は用語集で調べる →</a>
  </div>
</main>"""
        + html_mobile_nav("top", "../")
        + html_footer()
        + "</body></html>"
    )

    (art_dir / f"{a['id']}.html").write_text(html, encoding="utf-8")


def build_search(articles: list, out_dir: Path) -> None:
    """検索ページ (search.html) を生成する。全記事データをJSONとして埋め込む。"""

    # 検索用データ（出典URLを含む）
    search_data = [
        {
            "id":          a["id"],
            "title":       a.get("title_ja",""),
            "lead":        a.get("lead_ja",""),
            "body":        a.get("body_ja","")[:300],
            "category":    cat_label(a.get("category_main","")),
            "level":       a.get("alert_level","low"),
            "level_label": alert_label(a.get("alert_level","low")),
            "date":        format_date(a.get("published_at","")),
            "source_name": a.get("source_name",""),
            "source_url":  a.get("source_url","") or "",
            "source_tier": a.get("source_tier",2),
            "tags":        a.get("tags",[]),
            "score":       a.get("score",0),
        }
        for a in articles
    ]
    data_js = json.dumps(search_data, ensure_ascii=False)

    html = (
        html_head("過去記事検索", "サウジ在住邦人ポータル — 記事検索")
        + html_header("search")
        + f"""
<main>
  <div class="section-label">過去記事を検索</div>

  <div style="display:flex;gap:8px;margin-bottom:20px">
    <input id="q" type="search" placeholder="キーワード（例：iqama、ビザ、医療）"
      style="flex:1;padding:10px 14px;border:0.5px solid var(--border-mid);
        border-radius:var(--radius);font-size:14px;background:white;
        color:var(--ink);font-family:var(--sans);outline:none;
        -webkit-appearance:none"
      oninput="doSearch(this.value)"
      onfocus="this.style.borderColor='var(--gold)'"
      onblur="this.style.borderColor='var(--border-mid)'">
    <select id="catFilter" onchange="doSearch(document.getElementById('q').value)"
      style="padding:10px 12px;border:0.5px solid var(--border-mid);
        border-radius:var(--radius);font-size:12px;background:white;
        color:var(--ink-mid);font-family:var(--sans);outline:none;-webkit-appearance:none">
      <option value="">すべてのカテゴリ</option>
      <option value="安全・治安">安全・治安</option>
      <option value="ビザ・在留">ビザ・在留</option>
      <option value="医療・健康">医療・健康</option>
      <option value="ビジネス">ビジネス</option>
      <option value="生活">生活</option>
      <option value="教育">教育</option>
      <option value="文化・宗教">文化・宗教</option>
    </select>
  </div>

  <div id="stats" style="font-size:11px;color:var(--ink-muted);margin-bottom:14px"></div>
  <div id="results"></div>
</main>

<script>
const DATA = {data_js};

const LEVEL_CLASS = {{
  urgent:'badge-light-urgent', high:'badge-light-high',
  medium:'badge-light-medium', low:''
}};

function esc(s){{
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

function highlight(text, q) {{
  if (!q) return esc(text);
  const re = new RegExp('(' + q.replace(/[.*+?^${{}}()|[\\]\\\\]/g,'\\\\$&') + ')', 'gi');
  return esc(text).replace(re, '<mark style="background:#fef3cd;border-radius:2px">$1</mark>');
}}

function renderCard(a, q) {{
  const levelLabel = a.level_label ? `<span class="badge ${{LEVEL_CLASS[a.level]}}">${{esc(a.level_label)}}</span>` : '';
  const srcLink = a.source_url
    ? `<a href="${{esc(a.source_url)}}" target="_blank" rel="noopener" class="source-link">出典 ↗</a>`
    : '';
  return `
<article style="background:white;border:0.5px solid var(--border);border-radius:var(--radius);
  padding:15px 16px;margin-bottom:8px">
  <div style="display:flex;align-items:center;gap:5px;margin-bottom:7px;flex-wrap:wrap">
    ${{levelLabel}}
    <span class="badge badge-light-cat">${{esc(a.category)}}</span>
    <span style="font-size:10px;color:var(--ink-muted);margin-left:auto">${{esc(a.date)}}</span>
  </div>
  <h2 style="font-family:var(--body-serif);font-size:14px;font-weight:400;
    color:var(--ink);line-height:1.55;margin-bottom:5px">
    <a href="articles/${{esc(a.id)}}.html">${{highlight(a.title, q)}}</a>
  </h2>
  <p style="font-size:11px;color:var(--ink-muted);line-height:1.65;margin-bottom:8px">
    ${{highlight(a.lead, q)}}
  </p>
  <div style="display:flex;align-items:center;gap:8px;padding-top:8px;border-top:0.5px solid var(--border)">
    <span class="tier-dot tier-${{a.source_tier}}" title="Tier ${{a.source_tier}}"></span>
    <span style="font-size:10px;color:var(--ink-muted)">${{esc(a.source_name)}}</span>
    ${{srcLink}}
  </div>
</article>`;
}}

function doSearch(raw) {{
  const q    = raw.trim();
  const cat  = document.getElementById('catFilter').value;
  const ql   = q.toLowerCase();
  const re   = ql ? new RegExp(ql.replace(/[.*+?^${{}}()|[\\]\\\\]/g,'\\\\$&'),'i') : null;

  const hits = DATA.filter(a => {{
    if (cat && a.category !== cat) return false;
    if (!re) return true;
    return re.test(a.title) || re.test(a.lead) || re.test(a.body) ||
           re.test(a.category) || (a.tags||[]).some(t => re.test(t));
  }}).sort((x,y) => y.score - x.score);

  const stats = document.getElementById('stats');
  const res   = document.getElementById('results');

  if (!q && !cat) {{
    stats.textContent = `全 ${{DATA.length}} 件`;
    res.innerHTML = hits.slice(0,30).map(a => renderCard(a, '')).join('');
  }} else {{
    stats.textContent = `${{hits.length}} 件ヒット`;
    res.innerHTML = hits.length
      ? hits.slice(0,50).map(a => renderCard(a, q)).join('')
      : '<p style="color:var(--ink-muted);font-size:13px;padding:20px 0">該当する記事が見つかりませんでした。</p>';
  }}
}}

doSearch('');
</script>"""
        + html_mobile_nav("search")
        + html_footer()
        + "</body></html>"
    )

    (out_dir / "search.html").write_text(html, encoding="utf-8")
    logger.info("生成: search.html")


def build_glossary(terms: list, out_dir: Path) -> None:
    """用語集ページ (glossary.html) を生成する。"""

    cats = sorted(set(t.get("category","") for t in terms))

    # カテゴリ別にグループ化
    by_cat: dict[str, list] = {}
    for t in sorted(terms, key=lambda x: x.get("reading","")):
        c = t.get("category","その他")
        by_cat.setdefault(c, []).append(t)

    # 索引リンク（あ行など）
    readings = sorted(set(t.get("reading","")[0] for t in terms if t.get("reading")))

    sections_html = ""
    for cat, cat_terms in by_cat.items():
        items_html = ""
        for t in cat_terms:
            src_link = (
                f'<a href="{e(t["source_url"])}" target="_blank" rel="noopener" class="source-link">'
                f'{e(t["source_name"])} で確認 ↗</a>'
            ) if t.get("source_url") and t.get("source_name") else ""

            related_html = ""
            if t.get("related"):
                related_html = (
                    '<div style="margin-top:8px;font-size:11px;color:var(--ink-muted)">'
                    '関連: ' +
                    " / ".join(
                        f'<a href="#{e(r)}" style="color:var(--gold);'
                        f'border-bottom:0.5px solid rgba(140,110,60,.3)">{e(r)}</a>'
                        for r in t["related"]
                    ) + "</div>"
                )

            items_html += f"""
<div id="{e(t['id'])}" style="padding:16px 0;border-bottom:0.5px solid var(--border)">
  <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:6px;flex-wrap:wrap">
    <span style="font-family:var(--body-serif);font-size:16px;font-weight:400;color:var(--ink)">{e(t['term'])}</span>
    {f'<span style="font-family:var(--serif);font-size:15px;color:var(--gold);font-style:italic">{e(t["term_ar"])}</span>' if t.get("term_ar") else ""}
    <span style="font-size:11px;color:var(--ink-muted)">{e(t.get("reading",""))}</span>
  </div>
  <p style="font-size:12px;color:var(--ink-muted);line-height:1.6;margin-bottom:6px">{e(t.get("short",""))}</p>
  <p style="font-size:13px;color:var(--ink-mid);line-height:1.75">{e(t.get("full",""))}</p>
  {related_html}
  {f'<div style="margin-top:8px">{src_link}</div>' if src_link else ""}
</div>"""

        sections_html += f"""
<section style="margin-bottom:32px">
  <div class="section-label">{e(cat)}</div>
  {items_html}
</section>"""

    data_js = json.dumps(
        [{"id":t["id"],"term":t["term"],"term_ar":t.get("term_ar",""),
          "reading":t.get("reading",""),"short":t.get("short",""),
          "category":t.get("category","")} for t in terms],
        ensure_ascii=False
    )

    html = (
        html_head("用語集", "サウジ在住邦人向け用語・略語インデックス")
        + html_header("glossary")
        + f"""
<main style="max-width:800px;margin:0 auto;padding:28px 24px 60px">
  <div class="section-label">アラビア語・略語・制度用語インデックス</div>

  <div style="margin-bottom:20px">
    <input id="gq" type="search" placeholder="用語を検索（例：iqama、ビザ、礼拝）"
      style="width:100%;padding:10px 14px;border:0.5px solid var(--border-mid);
        border-radius:var(--radius);font-size:14px;background:white;
        color:var(--ink);font-family:var(--sans);outline:none;-webkit-appearance:none"
      oninput="gSearch(this.value)"
      onfocus="this.style.borderColor='var(--gold)'"
      onblur="this.style.borderColor='var(--border-mid)'">
  </div>

  <div id="g-results" style="display:none;margin-bottom:24px"></div>
  <div id="g-main">
    {sections_html}
  </div>
</main>

<script>
const GDATA = {data_js};

function gSearch(raw) {{
  const q  = raw.trim().toLowerCase();
  const rm = document.getElementById('g-results');
  const gm = document.getElementById('g-main');
  if (!q) {{ rm.style.display='none'; gm.style.display=''; return; }}
  const hits = GDATA.filter(t =>
    t.term.toLowerCase().includes(q) ||
    (t.term_ar||'').includes(q) ||
    (t.reading||'').toLowerCase().includes(q) ||
    t.short.toLowerCase().includes(q)
  );
  rm.style.display = '';
  gm.style.display = 'none';
  rm.innerHTML = hits.length
    ? hits.map(t =>
        `<div style="padding:12px 0;border-bottom:0.5px solid var(--border)">
          <a href="#${{t.id}}" onclick="clearSearch()" style="display:block">
            <span style="font-family:var(--body-serif);font-size:15px;color:var(--ink)">${{t.term}}</span>
            ${{t.term_ar ? `<span style="font-family:serif;font-size:13px;color:var(--gold);margin-left:8px">${{t.term_ar}}</span>` : ''}}
            <span style="font-size:11px;color:var(--ink-muted);margin-left:6px">${{t.reading}}</span>
          </a>
          <p style="font-size:12px;color:var(--ink-muted);line-height:1.6;margin-top:3px">${{t.short}}</p>
        </div>`
      ).join('')
    : '<p style="color:var(--ink-muted);font-size:13px;padding:16px 0">該当する用語が見つかりませんでした。</p>';
}}
function clearSearch() {{
  document.getElementById('gq').value = '';
  document.getElementById('g-results').style.display = 'none';
  document.getElementById('g-main').style.display = '';
}}
</script>"""
        + html_mobile_nav("glossary")
        + html_footer()
        + "</body></html>"
    )

    (out_dir / "glossary.html").write_text(html, encoding="utf-8")
    logger.info("生成: glossary.html")


def copy_data_files(out_dir: Path) -> None:
    """検索用データJSONをサイトのdataディレクトリにコピーする。"""
    data_out = out_dir / "data"
    data_out.mkdir(exist_ok=True)
    for src in [ARTICLES_DB, GLOSSARY_DB]:
        if src.exists():
            shutil.copy2(src, data_out / src.name)
    logger.info("データファイルをコピーしました")


# ── メイン ────────────────────────────────────────────

def generate(out_dir: Path) -> None:
    """全ページを生成する。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "articles").mkdir(exist_ok=True)

    articles = load_json(ARTICLES_DB)
    glossary = load_json(GLOSSARY_DB)

    if not articles:
        logger.warning("記事データが空です。デモデータを使用します。")
        articles = _demo_articles()

    logger.info(f"記事数: {len(articles)} / 用語数: {len(glossary)}")

    build_index(articles, out_dir)
    build_search(articles, out_dir)
    build_glossary(glossary, out_dir)

    for a in articles:
        build_article(a, out_dir)

    copy_data_files(out_dir)

    logger.info(f"サイト生成完了 → {out_dir}/")
    logger.info(f"  index.html    トップページ")
    logger.info(f"  search.html   全文検索")
    logger.info(f"  glossary.html 用語集（{len(glossary)}語）")
    logger.info(f"  articles/     記事詳細 {len(articles)}ページ")


def _demo_articles() -> list:
    """デモ用記事データ（articles.json が空の場合のフォールバック）"""
    import uuid
    from datetime import datetime, timezone
    return [
        {
            "id":            str(uuid.uuid4()),
            "title_ja":      "外務省が感染症危険情報（レベル1）を更新",
            "lead_ja":       "外務省は感染症危険情報（レベル1）を更新しました。在留者・渡航者は最新情報を確認してください。",
            "body_ja":       "外務省より感染症危険情報が発出されました。感染症への対策を講じたうえで行動するよう求めるものです。手洗い・うがいの徹底、症状が出た場合は速やかに医療機関へ相談してください。",
            "action_ja":     "外務省「たびレジ」に登録し最新情報を受信する。症状がある場合はSehhatyアプリまたは医療機関に連絡する。",
            "category_main": "safety",
            "alert_level":   "urgent",
            "score":         88,
            "tags":          ["emergency_alert", "infectious_disease"],
            "region":        ["all"],
            "target_reader": "both",
            "source_id":     "mofa_anzen",
            "source_name":   "外務省 海外安全情報",
            "source_url":    "https://anzen.mofa.go.jp",
            "source_tier":   1,
            "original_lang": "ja",
            "collected_at":  datetime.now(timezone.utc).isoformat(),
            "published_at":  datetime.now(timezone.utc).isoformat(),
            "key_dates":     [],
            "push_notify":   True,
            "notify_channels": ["line","email","site_top"],
            "content_hash":  "demo001",
        },
        {
            "id":            str(uuid.uuid4()),
            "title_ja":      "iqama更新手数料が改定、4月1日より特定職種で引き上げ",
            "lead_ja":       "人材・社会開発省（HRSD）が建設業・製造業の居留許可更新手数料を改定。4月1日施行です。",
            "body_ja":       "HRSDは特定職種におけるiqama更新手数料を改定すると発表しました。建設業・製造業・物流業の一部職種が対象です。手続きはAbsherまたはMOLポータルから行えます。",
            "action_ja":     "雇用主の人事部門に最新要件を確認し、4月以前に必要書類を準備してください。",
            "category_main": "visa",
            "alert_level":   "high",
            "score":         72,
            "tags":          ["iqama","visa_update","labor_law"],
            "region":        ["all"],
            "target_reader": "both",
            "source_id":     "hrsd_gov",
            "source_name":   "HRSD（人材・社会開発省）",
            "source_url":    "https://www.hrsd.gov.sa/en",
            "source_tier":   1,
            "original_lang": "en",
            "collected_at":  datetime.now(timezone.utc).isoformat(),
            "published_at":  datetime.now(timezone.utc).isoformat(),
            "key_dates":     ["2026-04-01"],
            "push_notify":   False,
            "notify_channels": [],
            "content_hash":  "demo002",
        },
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="在サウジ邦人ポータル 静的サイトジェネレーター")
    parser.add_argument("--output", default="site", help="出力ディレクトリ（デフォルト: site/）")
    parser.add_argument("--watch", action="store_true", help="ファイル変更を監視して自動再生成")
    args = parser.parse_args()

    out = Path(args.output)

    if args.watch:
        logger.info("監視モード起動（60秒ごとに再生成）")
        last_mtime = 0.0
        while True:
            try:
                mtime = max(
                    (p.stat().st_mtime for p in [ARTICLES_DB, GLOSSARY_DB] if p.exists()),
                    default=0.0
                )
                if mtime > last_mtime:
                    generate(out)
                    last_mtime = mtime
                time.sleep(60)
            except KeyboardInterrupt:
                logger.info("監視モード終了")
                break
    else:
        generate(out)
