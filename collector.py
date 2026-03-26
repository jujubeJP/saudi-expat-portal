"""
collector.py — RSS取得・スクレイピングモジュール

各情報源からRaw記事を収集し、正規化された辞書リストを返す。
"""

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

import feedparser
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SaudiJapanExpat-Bot/1.0; "
        "+https://saudi-expat-jp.example.com/bot)"
    ),
    "Accept-Language": "ja,en;q=0.9,ar;q=0.8",
}

REQUEST_TIMEOUT = 20  # seconds
REQUEST_DELAY = 1.5   # 連続リクエスト間の待機秒数


# ──────────────────────────────────────────────────────
# ユーティリティ
# ──────────────────────────────────────────────────────

def make_content_hash(title: str, url: str) -> str:
    """タイトル+URLのSHA256ハッシュ（重複検知用）"""
    raw = f"{title.strip().lower()}|{url.strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def normalize_date(entry) -> str:
    """feedparserのtime_structをISO8601文字列に変換"""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        return dt.isoformat()
    return datetime.now(timezone.utc).isoformat()


def clean_text(text: str) -> str:
    """HTMLタグ除去・空白正規化"""
    if not text:
        return ""
    soup = BeautifulSoup(text, "lxml")
    return " ".join(soup.get_text(separator=" ").split())


# ──────────────────────────────────────────────────────
# RSSフェッチャー
# ──────────────────────────────────────────────────────

def fetch_rss(source: dict, max_items: int = 20) -> list[dict]:
    """
    RSSフィードを取得して記事リストを返す。

    Returns:
        List of raw article dicts with keys:
        source_id, source_name, tier, title, url,
        content_hash, collected_at, lang, category_hint,
        raw_text, alert_override
    """
    results = []
    url = source["url"]

    logger.info(f"[RSS] 取得開始: {source['name']} ({url})")

    try:
        # feedparserはrequests非対応なのでhttpxで取得後に渡す
        with httpx.Client(headers=HEADERS, timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            feed_text = resp.content.decode('shift_jis', errors='replace')
            feed_text = feed_text.replace('encoding="shift_jis"', 'encoding="utf-8"')

        feed = feedparser.parse(url)

        if feed.bozo:
            logger.warning(f"[RSS] フィード解析警告: {feed.bozo_exception}")

        filter_kws = [k.lower() for k in source.get("filter_keywords", [])]

        for entry in feed.entries[:max_items]:
            title = clean_text(getattr(entry, "title", ""))
            link  = getattr(entry, "link", "")
            summary = clean_text(
                getattr(entry, "summary", "") or
                getattr(entry, "description", "")
            )

            if not title or not link:
                continue

            # フィルタリング（キーワードが設定されている場合）
            if filter_kws:
                combined = (title + " " + summary).lower()
                if not any(k in combined for k in filter_kws):
                    continue

            raw_text = f"{title}\n\n{summary}"

            results.append({
                "source_id":      source["id"],
                "source_name":    source["name"],
                "tier":           source["tier"],
                "title":          title,
                "url": source.get("source_url_override") or link or source["url"],
                "content_hash":   make_content_hash(title, link),
                "collected_at":   datetime.now(timezone.utc).isoformat(),
                "published_at":   normalize_date(entry),
                "lang":           source.get("lang", "en"),
                "category_hint":  source.get("category_hint", "news_general"),
                "raw_text":       raw_text,
                "alert_override": source.get("alert_override", False),
            })

        logger.info(f"[RSS] 取得完了: {len(results)}件 / {source['name']}")

    except httpx.HTTPError as e:
        logger.error(f"[RSS] HTTP エラー: {source['name']} - {e}")
    except Exception as e:
        logger.error(f"[RSS] 予期しないエラー: {source['name']} - {e}", exc_info=True)

    return results


# ──────────────────────────────────────────────────────
# Webスクレイパー
# ──────────────────────────────────────────────────────

def fetch_scrape(source: dict, max_items: int = 15) -> list[dict]:
    """
    HTMLページをスクレイピングして記事リストを返す。
    scrape_config に基づいてセレクタを適用する。
    """
    results = []
    cfg = source.get("scrape_config", {})
    base_url = cfg.get("base_url", "")

    logger.info(f"[SCRAPE] 取得開始: {source['name']} ({source['url']})")

    try:
        with httpx.Client(headers=HEADERS, timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(source["url"])
            resp.raise_for_status()
            html = resp.text

        soup = BeautifulSoup(html, "lxml")

        # ニュースリストの要素を取得
        list_selector = cfg.get("news_list_selector", "article")
        items = soup.select(list_selector)[:max_items]

        if not items:
            logger.warning(f"[SCRAPE] セレクタ一致なし: {list_selector} @ {source['url']}")
            return results

        for item in items:
            # タイトル取得
            title_sel = cfg.get("title_selector", "a")
            title_el = item.select_one(title_sel)
            title = title_el.get_text(strip=True) if title_el else ""

            # リンク取得
            link_sel = cfg.get("link_selector", "a")
            link_attr = cfg.get("link_attr", "href")
            link_el = item.select_one(link_sel) or item.select_one("a")
            link = ""
            if link_el:
                link = link_el.get(link_attr, "")
                if link and not link.startswith("http"):
                    link = urljoin(base_url, link)

            if not title or not link:
                continue

            # 本文テキスト（リスト要素から取れる範囲で）
            raw_text = clean_text(item.get_text(separator=" "))

            results.append({
                "source_id":      source["id"],
                "source_name":    source["name"],
                "tier":           source["tier"],
                "title":          title,
                "url":            link,
                "content_hash":   make_content_hash(title, link),
                "collected_at":   datetime.now(timezone.utc).isoformat(),
                "published_at":   datetime.now(timezone.utc).isoformat(),
                "lang":           source.get("lang", "en"),
                "category_hint":  source.get("category_hint", "news_general"),
                "raw_text":       raw_text,
                "alert_override": source.get("alert_override", False),
            })

        logger.info(f"[SCRAPE] 取得完了: {len(results)}件 / {source['name']}")
        time.sleep(REQUEST_DELAY)

    except httpx.HTTPError as e:
        logger.error(f"[SCRAPE] HTTP エラー: {source['name']} - {e}")
    except Exception as e:
        logger.error(f"[SCRAPE] 予期しないエラー: {source['name']} - {e}", exc_info=True)

    return results


# ──────────────────────────────────────────────────────
# ディスパッチャー（メインエントリポイント）
# ──────────────────────────────────────────────────────

def collect_from_source(source: dict) -> list[dict]:
    """ソース設定に基づいてRSSまたはスクレイプを選択して実行"""
    src_type = source.get("type", "rss")
    if src_type == "rss":
        return fetch_rss(source)
    elif src_type == "scrape":
        return fetch_scrape(source)
    else:
        logger.warning(f"未対応の収集タイプ: {src_type}")
        return []
