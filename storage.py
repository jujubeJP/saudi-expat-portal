"""
storage.py — 記事の保存・重複管理モジュール

・Supabase（PostgreSQL）が設定されていれば使用
・未設定ならローカルJSONファイルにフォールバック
・seen_hashes によるセッション内重複除去
・DB内の既存ハッシュとの突合でクロスセッション重複除去
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_FILE = Path("data/articles.json")  # Supabase未設定時のフォールバック先


# ──────────────────────────────────────────────────────
# Supabase クライアント（オプション）
# ──────────────────────────────────────────────────────

def _get_supabase():
    """Supabase接続を試みる。環境変数未設定ならNoneを返す。"""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key or "xxxx" in url:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception as e:
        logger.warning(f"Supabase接続失敗 → JSONフォールバック: {e}")
        return None


# ──────────────────────────────────────────────────────
# 既存ハッシュの取得（クロスセッション重複除去）
# ──────────────────────────────────────────────────────

def load_seen_hashes() -> set:
    """DBまたはJSONから既存のcontent_hashセットを返す。"""
    sb = _get_supabase()

    if sb:
        try:
            res = sb.table("articles").select("content_hash").execute()
            return {row["content_hash"] for row in res.data}
        except Exception as e:
            logger.error(f"Supabase ハッシュ取得失敗: {e}")
            return set()

    # JSONフォールバック
    if DB_FILE.exists():
        try:
            data = json.loads(DB_FILE.read_text(encoding="utf-8"))
            return {a["content_hash"] for a in data if "content_hash" in a}
        except Exception:
            return set()
    return set()


# ──────────────────────────────────────────────────────
# 記事の保存
# ──────────────────────────────────────────────────────

def save_articles(articles: list[dict], dry_run: bool = False) -> int:
    """
    記事リストをDBまたはJSONに保存する。

    Returns:
        保存成功件数
    """
    if not articles:
        return 0

    if dry_run:
        logger.info(f"[DRY RUN] 保存スキップ: {len(articles)}件")
        for a in articles:
            logger.info(f"  • [{a['alert_level']:6s}] score={a['score']:3d} | {a['title_ja'][:40]}")
        return 0

    sb = _get_supabase()

    if sb:
        return _save_to_supabase(sb, articles)
    else:
        return _save_to_json(articles)


def _save_to_supabase(sb, articles: list[dict]) -> int:
    """Supabaseへのupsert保存（content_hashで重複排除）"""
    saved = 0
    for article in articles:
        try:
            sb.table("articles").upsert(
                article,
                on_conflict="content_hash"
            ).execute()
            saved += 1
        except Exception as e:
            logger.error(f"Supabase保存失敗: {article.get('title_ja', '')[:30]} - {e}")
    logger.info(f"[Supabase] {saved}/{len(articles)} 件保存完了")
    return saved


def _save_to_json(articles: list[dict]) -> int:
    """ローカルJSONへの追記保存"""
    DB_FILE.parent.mkdir(exist_ok=True)
    existing = []
    if DB_FILE.exists():
        try:
            existing = json.loads(DB_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    # 既存ハッシュとのマージ（重複除去）
    existing_hashes = {a["content_hash"] for a in existing}
    new_articles = [a for a in articles if a["content_hash"] not in existing_hashes]

    all_articles = existing + new_articles
    # 最新1000件のみ保持（ファイルサイズ管理）
    all_articles = sorted(
        all_articles,
        key=lambda x: x.get("collected_at", ""),
        reverse=True
    )[:1000]

    DB_FILE.write_text(
        json.dumps(all_articles, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    logger.info(f"[JSON] {len(new_articles)}/{len(articles)} 件保存完了 → {DB_FILE}")
    return len(new_articles)


# ──────────────────────────────────────────────────────
# 記事の読み出し（サイト生成用）
# ──────────────────────────────────────────────────────

def load_articles(
    limit: int = 50,
    alert_level: Optional[str] = None,
    category: Optional[str] = None,
    min_score: int = 0,
) -> list[dict]:
    """
    保存済み記事を条件でフィルタして返す。

    Args:
        limit: 返す最大件数
        alert_level: フィルタするアラートレベル
        category: フィルタするカテゴリ
        min_score: スコア下限
    """
    sb = _get_supabase()

    if sb:
        try:
            q = sb.table("articles").select("*").gte("score", min_score)
            if alert_level:
                q = q.eq("alert_level", alert_level)
            if category:
                q = q.eq("category_main", category)
            res = q.order("score", desc=True).limit(limit).execute()
            return res.data
        except Exception as e:
            logger.error(f"Supabase読み出し失敗: {e}")
            return []

    # JSONフォールバック
    if not DB_FILE.exists():
        return []
    try:
        data = json.loads(DB_FILE.read_text(encoding="utf-8"))
        filtered = [
            a for a in data
            if a.get("score", 0) >= min_score
            and (not alert_level or a.get("alert_level") == alert_level)
            and (not category or a.get("category_main") == category)
        ]
        return sorted(filtered, key=lambda x: x.get("score", 0), reverse=True)[:limit]
    except Exception as e:
        logger.error(f"JSON読み出し失敗: {e}")
        return []


# ──────────────────────────────────────────────────────
# Supabaseスキーマ（初期セットアップ用）
# ──────────────────────────────────────────────────────

SUPABASE_SCHEMA = """
-- Supabase上で実行するSQL（初回のみ）

CREATE TABLE IF NOT EXISTS articles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title_ja        TEXT NOT NULL,
    lead_ja         TEXT,
    body_ja         TEXT,
    action_ja       TEXT,
    category_main   TEXT,
    alert_level     TEXT DEFAULT 'low',
    score           INTEGER DEFAULT 0,
    tags            JSONB DEFAULT '[]',
    region          JSONB DEFAULT '["all"]',
    target_reader   TEXT DEFAULT 'both',
    source_id       TEXT,
    source_name     TEXT,
    source_url      TEXT,
    source_tier     INTEGER,
    original_lang   TEXT DEFAULT 'en',
    collected_at    TIMESTAMPTZ DEFAULT NOW(),
    published_at    TIMESTAMPTZ,
    key_dates       JSONB DEFAULT '[]',
    push_notify     BOOLEAN DEFAULT FALSE,
    notify_channels JSONB DEFAULT '[]',
    content_hash    TEXT UNIQUE NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_articles_score       ON articles(score DESC);
CREATE INDEX IF NOT EXISTS idx_articles_alert_level ON articles(alert_level);
CREATE INDEX IF NOT EXISTS idx_articles_category    ON articles(category_main);
CREATE INDEX IF NOT EXISTS idx_articles_collected   ON articles(collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_hash        ON articles(content_hash);

-- Row Level Security（公開読み取り許可）
ALTER TABLE articles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read" ON articles FOR SELECT USING (true);
"""
