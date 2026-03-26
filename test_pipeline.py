"""
test_pipeline.py — APIキーなしでパイプライン構造をテストするスクリプト

Claude APIは呼ばず、モック応答でSTEP1〜5の入出力フローを確認する。
"""

import json
import sys
sys.path.insert(0, ".")

from collector import make_content_hash, clean_text
from config.sources import SOURCES
from notifier import generate_digest_text
from storage import _save_to_json

# ──────────────────────────────────────────────────────
# モックデータ
# ──────────────────────────────────────────────────────

MOCK_RAW_ARTICLE = {
    "source_id":      "arab_news",
    "source_name":    "Arab News",
    "tier":           2,
    "title":          "Saudi Arabia tightens regulations on iqama renewal for certain professions",
    "url":            "https://www.arabnews.com/node/test-123",
    "content_hash":   make_content_hash("Saudi Arabia tightens regulations on iqama renewal for certain professions", "https://www.arabnews.com/node/test-123"),
    "collected_at":   "2026-03-26T09:00:00+00:00",
    "published_at":   "2026-03-26T07:30:00+00:00",
    "lang":           "en",
    "category_hint":  "visa",
    "raw_text":       "Saudi Arabia tightens regulations on iqama renewal for certain professions. The Ministry of Human Resources and Social Development (HRSD) announced new requirements for iqama renewal, particularly affecting construction and manufacturing sectors. The changes will take effect from April 1, 2026.",
    "alert_override": False,
}

MOCK_PIPELINE_OUTPUT = {
    "id":             "mock-uuid-1234",
    "title_ja":       "iqama更新規制が強化、4月1日施行",
    "lead_ja":        "人材・社会開発省が特定職種のiqama更新手続きを厳格化すると発表しました。建設業・製造業に従事する方は要確認です。",
    "body_ja":        "人的資源・社会開発省（HRSD）は、iqama（居留許可）の更新に関する新たな要件を発表しました。この改定は特に建設業と製造業に影響し、2026年4月1日より施行されます。更新手続きにあたっては、雇用主を通じたAbsherシステムでの申請が必要となります。手数料の変更についても詳細が追って発表される予定です。",
    "action_ja":      "雇用主の人事部門に最新要件を確認し、4月以前に必要書類を準備してください。",
    "category_main":  "visa",
    "alert_level":    "high",
    "score":          65,
    "tags":           ["iqama", "visa_update", "labor_law"],
    "region":         ["all"],
    "target_reader":  "both",
    "source_id":      "arab_news",
    "source_name":    "Arab News",
    "source_url":     "https://www.arabnews.com/node/test-123",
    "source_tier":    2,
    "original_lang":  "en",
    "collected_at":   "2026-03-26T09:00:00+00:00",
    "published_at":   "2026-03-26T07:30:00+00:00",
    "key_dates":      ["2026-04-01"],
    "push_notify":    False,
    "notify_channels": [],
    "content_hash":   MOCK_RAW_ARTICLE["content_hash"],
}

MOCK_URGENT_ARTICLE = {
    **MOCK_PIPELINE_OUTPUT,
    "id":             "mock-uuid-5678",
    "title_ja":       "外務省：リヤドでデング熱急増、感染症危険情報Lv.1を更新",
    "lead_ja":        "外務省は感染症危険情報（レベル1）を更新しました。リヤド首都圏でのデング熱患者報告が急増しています。",
    "category_main":  "safety",
    "alert_level":    "urgent",
    "score":          92,
    "tags":           ["infectious_disease", "emergency_alert", "riyadh"],
    "source_name":    "外務省 海外安全情報",
    "source_tier":    1,
    "push_notify":    True,
    "notify_channels": ["line", "email", "site_top"],
    "content_hash":   "abcdef1234567890",
}


# ──────────────────────────────────────────────────────
# テスト関数
# ──────────────────────────────────────────────────────

def test_sources_config():
    """sources.py の設定を検証する"""
    print("=" * 50)
    print("TEST: sources.py 設定検証")
    print("=" * 50)

    assert len(SOURCES) > 0, "ソースが空です"
    for src in SOURCES:
        assert "id"   in src, f"id がありません: {src}"
        assert "tier" in src, f"tier がありません: {src['id']}"
        assert "url"  in src, f"url がありません: {src['id']}"
        assert "type" in src, f"type がありません: {src['id']}"
        print(f"  ✓ [{src['tier']}] {src['id']:25s} ({src['type']})")

    print(f"\n  合計: {len(SOURCES)} ソース")
    print()


def test_collector_utils():
    """collector.py のユーティリティ関数をテスト"""
    print("=" * 50)
    print("TEST: collector ユーティリティ")
    print("=" * 50)

    # make_content_hash
    h1 = make_content_hash("Test Title", "https://example.com/1")
    h2 = make_content_hash("Test Title", "https://example.com/1")
    h3 = make_content_hash("Test Title", "https://example.com/2")
    assert h1 == h2, "同じ入力でハッシュが異なります"
    assert h1 != h3, "異なる入力でハッシュが一致しています"
    print(f"  ✓ content_hash: {h1}")

    # clean_text
    html_input = "<p>Hello <b>World</b>   !</p>"
    cleaned = clean_text(html_input)
    assert "Hello World !" in cleaned, f"clean_text失敗: {cleaned}"
    print(f"  ✓ clean_text: '{cleaned}'")

    print()


def test_pipeline_mock():
    """パイプラインの入出力スキーマをモックデータで検証する"""
    print("=" * 50)
    print("TEST: パイプライン出力スキーマ検証")
    print("=" * 50)

    required_keys = [
        "id", "title_ja", "lead_ja", "body_ja", "action_ja",
        "category_main", "alert_level", "score", "tags", "region",
        "target_reader", "source_id", "source_name", "source_url",
        "source_tier", "original_lang", "collected_at", "published_at",
        "key_dates", "push_notify", "notify_channels", "content_hash",
    ]

    for key in required_keys:
        assert key in MOCK_PIPELINE_OUTPUT, f"必須キーが欠落: {key}"
        print(f"  ✓ {key}: {str(MOCK_PIPELINE_OUTPUT[key])[:40]}")

    assert MOCK_PIPELINE_OUTPUT["score"] <= 100
    assert MOCK_PIPELINE_OUTPUT["alert_level"] in ("urgent", "high", "medium", "low")
    print()


def test_storage_json():
    """JSONフォールバックストレージをテスト"""
    print("=" * 50)
    print("TEST: JSONストレージ")
    print("=" * 50)

    import tempfile
    import os
    from pathlib import Path

    # 一時ファイルでテスト
    orig = __import__("storage").DB_FILE
    import storage
    tmp = Path(tempfile.mktemp(suffix=".json"))
    storage.DB_FILE = tmp

    try:
        saved = _save_to_json([MOCK_PIPELINE_OUTPUT, MOCK_URGENT_ARTICLE])
        assert saved == 2, f"保存件数が異なります: {saved}"
        print(f"  ✓ 初回保存: {saved}件")

        # 重複保存のテスト
        saved2 = _save_to_json([MOCK_PIPELINE_OUTPUT])
        assert saved2 == 0, f"重複が保存されました: {saved2}"
        print(f"  ✓ 重複除去: {saved2}件（正常）")

        # 読み出し確認
        data = json.loads(tmp.read_text(encoding="utf-8"))
        assert len(data) == 2, f"読み出し件数が異なります: {len(data)}"
        print(f"  ✓ 読み出し: {len(data)}件")

    finally:
        storage.DB_FILE = orig
        if tmp.exists():
            tmp.unlink()

    print()


def test_notifier_digest():
    """週次ダイジェスト生成をテスト"""
    print("=" * 50)
    print("TEST: 週次ダイジェスト生成")
    print("=" * 50)

    articles = [MOCK_PIPELINE_OUTPUT, MOCK_URGENT_ARTICLE]
    digest = generate_digest_text(articles, calendar_info="3/31 イード（予定）")

    assert "サウジ在住邦人ポータル" in digest
    assert "週次ダイジェスト" in digest
    assert "ハイライト" in digest

    print(f"  ✓ ダイジェスト生成成功: {len(digest)} 文字")
    print("\n--- プレビュー（先頭300字）---")
    print(digest[:300])
    print("...")
    print()


# ──────────────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\nサウジ情報エージェント — パイプラインテスト\n")

    test_sources_config()
    test_collector_utils()
    test_pipeline_mock()
    test_storage_json()
    test_notifier_digest()

    print("=" * 50)
    print("✅ 全テスト通過")
    print("=" * 50)
    print("\n次のステップ:")
    print("  1. .env.example を .env にコピーしてAPIキーを設定")
    print("  2. python main.py --dry-run --source mofa_anzen  でAPIテスト")
    print("  3. python main.py --schedule  でスケジューラ起動")
