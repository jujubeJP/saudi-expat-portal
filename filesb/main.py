"""
main.py — オーケストレーター（エントリポイント）

使い方:
  python main.py                  # 即時1回実行
  python main.py --schedule       # スケジューラ起動（常駐）
  python main.py --dry-run        # DB書き込み・通知なし（テスト）
  python main.py --source mofa_anzen  # 特定ソースのみ実行
  python main.py --digest         # 週次ダイジェスト生成・送信
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import schedule
from dotenv import load_dotenv

# 自前モジュール
from collector import collect_from_source
from config.sources import SOURCES
from notifier import notify, send_weekly_digest
from generate_site import generate as generate_site
from pipeline import run_pipeline
from storage import load_articles, load_seen_hashes, save_articles

# ──────────────────────────────────────────────────────
# 初期化
# ──────────────────────────────────────────────────────

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")
Path("logs").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)

MAX_ARTICLES = int(os.getenv("MAX_ARTICLES_PER_RUN", "50"))
DRY_RUN_ENV  = os.getenv("DRY_RUN", "false").lower() == "true"


# ──────────────────────────────────────────────────────
# コア実行関数
# ──────────────────────────────────────────────────────

def run_collection(
    source_filter: str = None,
    dry_run: bool = False,
) -> list[dict]:
    """
    全（または指定）ソースから記事を収集してパイプラインを実行する。

    Returns:
        処理済み記事リスト
    """
    dry_run = dry_run or DRY_RUN_ENV
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("sk-ant-..."):
        logger.error("ANTHROPIC_API_KEY が未設定です。.env ファイルを確認してください。")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # 対象ソースを絞り込む
    targets = [s for s in SOURCES if not source_filter or s["id"] == source_filter]
    if not targets:
        logger.error(f"ソース '{source_filter}' が見つかりません。")
        return []

    logger.info(f"{'='*50}")
    logger.info(f"収集開始: {len(targets)} ソース / dry_run={dry_run}")
    logger.info(f"{'='*50}")

    # 既存ハッシュを読み込んで重複除去セットを初期化
    seen_hashes = load_seen_hashes()
    logger.info(f"既存ハッシュ読み込み: {len(seen_hashes)} 件")

    all_raw: list[dict] = []
    for source in targets:
        logger.info(f"▶ [{source['id']}] {source['name']}")
        raw_articles = collect_from_source(source)
        all_raw.extend(raw_articles)
        logger.info(f"  → 収集: {len(raw_articles)} 件")

    logger.info(f"{'─'*50}")
    logger.info(f"収集合計: {len(all_raw)} 件 → パイプライン処理開始")

    # パイプライン処理（上限あり）
    processed: list[dict] = []
    for i, article in enumerate(all_raw[:MAX_ARTICLES]):
        logger.info(f"[{i+1}/{min(len(all_raw), MAX_ARTICLES)}] {article['title'][:50]}")
        result = run_pipeline(client, article, seen_hashes)
        if result:
            processed.append(result)

    logger.info(f"{'─'*50}")
    logger.info(f"パイプライン完了: {len(processed)}/{len(all_raw[:MAX_ARTICLES])} 件通過")

    # 保存
    saved = save_articles(processed, dry_run=dry_run)
    logger.info(f"保存: {saved} 件")

    # サイト再生成（新規保存がある場合のみ）
    if saved > 0 and not dry_run:
        site_out = Path(os.getenv("SITE_OUTPUT_DIR", "site"))
        logger.info(f"サイト再生成 → {site_out}/")
        try:
            generate_site(site_out)
        except Exception as e:
            logger.error(f"サイト生成エラー: {e}", exc_info=True)

    # 通知（urgent / high）
    notify_targets = [a for a in processed if a.get("push_notify")]
    logger.info(f"通知対象: {len(notify_targets)} 件")
    for article in notify_targets:
        notify(article, dry_run=dry_run)

    # サマリーレポート
    _print_summary(processed)

    return processed


def _print_summary(articles: list[dict]) -> None:
    """処理結果のサマリーをログ出力する。"""
    if not articles:
        logger.info("処理結果: 0件")
        return

    logger.info(f"{'='*50}")
    logger.info("処理結果サマリー")
    logger.info(f"{'='*50}")

    by_level = {"urgent": [], "high": [], "medium": [], "low": []}
    for a in articles:
        by_level.get(a.get("alert_level", "low"), []).append(a)

    for level, arts in by_level.items():
        if arts:
            emoji = {"urgent":"🚨","high":"⚠️","medium":"📌","low":"ℹ️"}[level]
            logger.info(f"{emoji} {level.upper()}: {len(arts)}件")
            for a in arts:
                logger.info(f"    [{a['score']:3d}] {a['title_ja'][:45]}")

    by_cat = {}
    for a in articles:
        cat = a.get("category_main", "other")
        by_cat.setdefault(cat, 0)
        by_cat[cat] += 1

    logger.info(f"{'─'*50}")
    logger.info("カテゴリ別: " + " | ".join(f"{k}:{v}" for k, v in by_cat.items()))
    logger.info(f"{'='*50}")


# ──────────────────────────────────────────────────────
# スケジューラ設定
# ──────────────────────────────────────────────────────

def setup_schedule(dry_run: bool = False) -> None:
    """
    ソースごとの収集間隔に基づいてスケジュールを設定する。

    間隔の分類:
      ≤ 60分  → 毎時実行
      ≤ 360分 → 6時間ごと
      ≤ 720分 → 12時間ごと
      それ以上 → 24時間ごと（深夜2時）
    """
    # 間隔でグルーピング
    schedule_groups: dict[int, list[str]] = {}
    for src in SOURCES:
        interval = src.get("interval_minutes", 360)
        if interval not in schedule_groups:
            schedule_groups[interval] = []
        schedule_groups[interval].append(src["id"])

    for interval, source_ids in schedule_groups.items():
        def make_job(ids):
            def job():
                for sid in ids:
                    run_collection(source_filter=sid, dry_run=dry_run)
            return job

        if interval <= 60:
            schedule.every(interval).minutes.do(make_job(source_ids))
            logger.info(f"スケジュール: {interval}分ごと → {source_ids}")
        elif interval <= 360:
            schedule.every(6).hours.do(make_job(source_ids))
            logger.info(f"スケジュール: 6時間ごと → {source_ids}")
        elif interval <= 720:
            schedule.every(12).hours.do(make_job(source_ids))
            logger.info(f"スケジュール: 12時間ごと → {source_ids}")
        else:
            schedule.every().day.at("02:00").do(make_job(source_ids))
            logger.info(f"スケジュール: 毎日02:00 → {source_ids}")

    # 週次ダイジェスト（月曜 07:00 JST）
    def weekly_digest_job():
        articles = load_articles(limit=100, min_score=40)
        send_weekly_digest(articles, dry_run=dry_run)

    schedule.every().monday.at("07:00").do(weekly_digest_job)
    logger.info("スケジュール: 毎週月曜07:00 → 週次ダイジェスト")


def run_scheduler(dry_run: bool = False) -> None:
    """スケジューラを起動して常駐する。"""
    logger.info("スケジューラ起動")
    setup_schedule(dry_run=dry_run)

    # 起動時に即1回実行
    run_collection(dry_run=dry_run)

    logger.info("スケジューラ待機中... (Ctrl+C で停止)")
    while True:
        schedule.run_pending()
        time.sleep(30)  # 30秒ごとにスケジュールチェック


# ──────────────────────────────────────────────────────
# エントリポイント
# ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="サウジ在住邦人 情報収集エージェント")
    parser.add_argument(
        "--schedule", action="store_true",
        help="スケジューラモードで起動（常駐）"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="DB書き込み・通知なし（テスト実行）"
    )
    parser.add_argument(
        "--source", type=str, default=None,
        help="特定ソースIDのみ実行（例: mofa_anzen）"
    )
    parser.add_argument(
        "--digest", action="store_true",
        help="週次ダイジェストを即時生成・送信"
    )
    parser.add_argument(
        "--list-sources", action="store_true",
        help="設定済みソース一覧を表示"
    )
    args = parser.parse_args()

    if args.list_sources:
        print("\n設定済みソース一覧:")
        for src in SOURCES:
            print(f"  [{src['tier']}] {src['id']:25s} {src['name']} ({src['type']}, {src['interval_minutes']}分)")
        return

    if args.digest:
        articles = load_articles(limit=100, min_score=40)
        send_weekly_digest(articles, dry_run=args.dry_run)
        return

    if args.schedule:
        run_scheduler(dry_run=args.dry_run)
    else:
        run_collection(source_filter=args.source, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
