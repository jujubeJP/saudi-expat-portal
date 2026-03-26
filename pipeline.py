"""
pipeline.py — Claude APIによる5ステップ処理パイプライン

STEP1: スクリーニング（在留邦人関連か判定）
STEP2: 翻訳・要約（日本語化）
STEP3: カテゴリ分類・タグ付け
STEP4: 重要度スコアリング
STEP5: 出力整形（ウェブ掲載用JSON生成）
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

# モデル設定
MODEL_FAST   = "claude-haiku-4-5-20251001"   # STEP1,3,4（軽量・高速）
MODEL_STRONG = "claude-sonnet-4-6"            # STEP2,5（翻訳・整形）


# ──────────────────────────────────────────────────────
# ユーティリティ
# ──────────────────────────────────────────────────────

def _call_claude(
    client: anthropic.Anthropic,
    system: str,
    user: str,
    model: str,
    max_tokens: int = 1024,
) -> Optional[str]:
    """Claude APIを呼び出してテキストを返す。エラー時はNone。"""
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": user}],
            system=system,
        )
        return msg.content[0].text.strip()
    except anthropic.APIError as e:
        logger.error(f"Claude API エラー: {e}")
        return None


def _parse_json(text: Optional[str], step: str) -> Optional[dict]:
    """LLMレスポンスからJSONをパースする。失敗時はNoneとログ出力。"""
    if not text:
        return None
    # コードブロック除去
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning(f"[{step}] JSON パース失敗: {e}\n原文: {text[:200]}")
        return None


# ──────────────────────────────────────────────────────
# STEP 1: スクリーニング
# ──────────────────────────────────────────────────────

SYSTEM_SCREEN = """あなたはサウジアラビア在住の日本人向け情報フィルタリングAIです。
与えられたテキストが「サウジアラビアに住む・働く日本人にとって有用な情報」かを判定してください。

判定基準（いずれか一つに該当すれば relevant=true）:
- 在留資格、ビザ、iqamaに関する情報
- 安全・治安・自然災害・感染症に関する情報
- 外国人の権利・義務・規制変更
- 生活インフラ（医療・教育・交通・住居）の変化
- ビジネス規制・税制・労働法の変更
- 宗教的習慣・文化的ルールの案内（ラマダン等）
- 日本との関係（航空路線、在外選挙、日本人コミュニティ）

コードブロックなしのJSONのみを返してください:
{"relevant": true/false, "reason": "判定理由20字以内"}"""


def step1_screen(client: anthropic.Anthropic, article: dict) -> bool:
    """在留邦人向けに関連する記事かを判定。Trueなら次ステップへ進む。"""
    user = f"以下のテキストを判定してください:\n\n{article['raw_text'][:1500]}"
    raw = _call_claude(client, SYSTEM_SCREEN, user, MODEL_FAST, max_tokens=128)
    result = _parse_json(raw, "STEP1")

    if result is None:
        logger.warning(f"[STEP1] パース失敗、通過扱い: {article['title'][:40]}")
        return True  # パース失敗時は念のため通過

    relevant = result.get("relevant", False)
    reason   = result.get("reason", "")
    logger.debug(f"[STEP1] {'✓' if relevant else '✗'} {reason} | {article['title'][:40]}")
    return bool(relevant)


# ──────────────────────────────────────────────────────
# STEP 2: 翻訳・要約
# ──────────────────────────────────────────────────────

SYSTEM_TRANSLATE = """あなたはサウジアラビア在住日本人向けニュースレターの編集者です。
与えられた原文（英語またはアラビア語）を以下の方針で日本語に翻訳・要約してください。

翻訳方針:
1. 読者は「サウジアラビアに住んでいる、または赴任予定の日本人」
2. 固有名詞（省庁名・制度名）は英語+日本語訳を併記 例: iqama（居留許可）
3. サウジのローカル文脈を知らない読者にも伝わるよう補足説明を加える
4. 「自分ごと化」できるよう、具体的影響を必ず一文で添える
5. センセーショナルな表現を避け、事実ベースで落ち着いたトーンで

コードブロックなしのJSONのみを返してください:
{
  "title_ja": "日本語タイトル（30字以内）",
  "summary_ja": "要約本文（150〜250字）",
  "impact_ja": "在留邦人への影響を1文で（60字以内）",
  "source_lang": "en/ar/ja",
  "key_dates": ["YYYY-MM-DD形式の重要日付（なければ空配列）"]
}"""


def step2_translate(client: anthropic.Anthropic, article: dict) -> Optional[dict]:
    """記事を日本語に翻訳・要約する。"""
    user = (
        f"原文（{article['lang']}）:\n{article['raw_text'][:3000]}\n\n"
        f"情報源URL: {article['url']}\n"
        f"情報源ティア: Tier {article['tier']}"
    )
    raw = _call_claude(client, SYSTEM_TRANSLATE, user, MODEL_STRONG, max_tokens=768)
    result = _parse_json(raw, "STEP2")
    if result:
        logger.debug(f"[STEP2] 翻訳完了: {result.get('title_ja', '')[:30]}")
    return result


# ──────────────────────────────────────────────────────
# STEP 3: カテゴリ分類・タグ付け
# ──────────────────────────────────────────────────────

SYSTEM_CLASSIFY = """あなたはサウジアラビア在住日本人向け情報サイトのタクソノミ管理AIです。
要約済みの記事に対して、カテゴリと詳細タグを付与してください。

主カテゴリ（category_main: 1つだけ選択）:
safety, visa, healthcare, business, daily_life, education, culture, news_general

詳細タグ（tags: 最大5つ）:
visa_update, iqama, exit_reentry, labor_law, saudization, vat_tax,
healthcare_hospital, infectious_disease, vaccine,
traffic_transport, housing, utility, grocery,
school_japanese, school_international, family,
ramadan, national_day, hajj, culture_rule,
emergency_alert, crime_security, natural_disaster,
driving_license, banking, telecom,
riyadh, jeddah, eastern_province, mecca, medina

地域タグ（region: 複数可）:
all, riyadh, jeddah, eastern_province, mecca, medina, other

コードブロックなしのJSONのみを返してください:
{
  "category_main": "カテゴリID",
  "tags": ["タグ1", "タグ2"],
  "region": ["地域"],
  "target_reader": "single/family/both",
  "category_reason": "分類理由15字以内"
}"""


def step3_classify(
    client: anthropic.Anthropic,
    article: dict,
    translated: dict,
) -> Optional[dict]:
    """カテゴリ分類とタグ付けを行う。"""
    user = (
        f"タイトル: {translated['title_ja']}\n"
        f"要約: {translated['summary_ja']}\n"
        f"影響: {translated['impact_ja']}\n"
        f"情報源ティア: Tier {article['tier']}\n"
        f"カテゴリヒント: {article['category_hint']}"
    )
    raw = _call_claude(client, SYSTEM_CLASSIFY, user, MODEL_FAST, max_tokens=256)
    result = _parse_json(raw, "STEP3")
    if result:
        logger.debug(f"[STEP3] 分類: {result.get('category_main')} / {result.get('tags')}")
    return result


# ──────────────────────────────────────────────────────
# STEP 4: 重要度スコアリング
# ──────────────────────────────────────────────────────

SYSTEM_SCORE = """あなたはサウジアラビア在住日本人向け情報のリスク評価AIです。
記事の重要度スコア（0〜100）とアラートレベルを判定してください。

スコアリング基準（加点方式）:
基礎点: 0
+ 30pt: カテゴリ「safety」
+ 20pt: 情報源Tier 1
+ 15pt: 即時対応が必要（7日以内の締め切り・規制施行）
+ 15pt: 全在留邦人に影響
+ 10pt: 特定グループに大きく影響
+ 10pt: 新規情報
- 10pt: 情報源Tier 3
- 15pt: 3ヶ月以上前の情報

アラートレベル:
urgent: 80以上（即時プッシュ通知）
high:   60〜79（当日ダイジェストトップ）
medium: 40〜59（通常掲載）
low:    39以下（アーカイブのみ）

コードブロックなしのJSONのみを返してください:
{
  "score": 整数,
  "alert_level": "urgent/high/medium/low",
  "push_notify": true/false,
  "notify_channels": ["line", "email", "site_top"]
}"""


def step4_score(
    client: anthropic.Anthropic,
    article: dict,
    translated: dict,
    classified: dict,
) -> Optional[dict]:
    """重要度スコアとアラートレベルを判定する。"""
    # alert_override（大使館・外務省安全情報）は強制的にスコア加算
    base_override = 30 if article.get("alert_override") else 0

    user = (
        f"タイトル: {translated['title_ja']}\n"
        f"カテゴリ: {classified['category_main']}\n"
        f"情報源ティア: Tier {article['tier']}\n"
        f"詳細タグ: {classified['tags']}\n"
        f"対象読者: {classified['target_reader']}\n"
        f"重要日付: {translated.get('key_dates', [])}\n"
        f"影響文: {translated['impact_ja']}\n"
        f"alert_override加算: +{base_override}pt（大使館・外務省情報）"
    )
    raw = _call_claude(client, SYSTEM_SCORE, user, MODEL_FAST, max_tokens=256)
    result = _parse_json(raw, "STEP4")

    if result and base_override:
        # スコアにオーバーライド加算を反映
        result["score"] = min(100, result.get("score", 0) + base_override)
        if result["score"] >= 80:
            result["alert_level"] = "urgent"
            result["push_notify"] = True

    if result:
        logger.debug(f"[STEP4] スコア: {result.get('score')} / {result.get('alert_level')}")
    return result


# ──────────────────────────────────────────────────────
# STEP 5: 出力整形
# ──────────────────────────────────────────────────────

SYSTEM_FORMAT = """あなたはサウジアラビア在住日本人向け情報サイトのコンテンツ整形AIです。
分類・スコアリング済みの記事データを、ウェブサイト掲載用の日本語本文に整形してください。

フォーマット要件:
- lead_ja: 冒頭2文（読者が続きを読みたくなる導入、70字以内）
- body_ja: 本文（300〜500字。箇条書きは使わず文章形式）
- action_ja: 読者がとるべき具体的アクション（なければ空文字）

コードブロックなしのJSONのみを返してください:
{"lead_ja": "...", "body_ja": "...", "action_ja": "..."}"""


def step5_format(
    client: anthropic.Anthropic,
    article: dict,
    translated: dict,
    classified: dict,
    scored: dict,
) -> Optional[dict]:
    """ウェブ掲載用の整形本文を生成する。"""
    user = (
        f"タイトル: {translated['title_ja']}\n"
        f"要約: {translated['summary_ja']}\n"
        f"影響: {translated['impact_ja']}\n"
        f"カテゴリ: {classified['category_main']}\n"
        f"アラートレベル: {scored['alert_level']}\n"
        f"元テキスト: {article['raw_text'][:2000]}"
    )
    raw = _call_claude(client, SYSTEM_FORMAT, user, MODEL_STRONG, max_tokens=1024)
    return _parse_json(raw, "STEP5")


# ──────────────────────────────────────────────────────
# メインパイプライン
# ──────────────────────────────────────────────────────

def run_pipeline(
    client: anthropic.Anthropic,
    article: dict,
    seen_hashes: set,
) -> Optional[dict]:
    """
    1件の記事に対してSTEP1〜5を実行し、掲載用データを返す。

    Args:
        client: Anthropic APIクライアント
        article: collector.pyが返すraw記事辞書
        seen_hashes: 既処理のcontent_hashセット（重複除去用）

    Returns:
        掲載用article辞書 or None（スキップ）
    """
    title = article["title"]
    h     = article["content_hash"]

    # 重複チェック
    if h in seen_hashes:
        logger.debug(f"[SKIP] 重複: {title[:40]}")
        return None
    seen_hashes.add(h)

    # STEP 1: スクリーニング
    if not step1_screen(client, article):
        logger.info(f"[STEP1 ✗] 非関連: {title[:50]}")
        return None

    # STEP 2: 翻訳・要約
    translated = step2_translate(client, article)
    if not translated or not translated.get("title_ja"):
        logger.warning(f"[STEP2 ✗] 翻訳失敗: {title[:50]}")
        return None

    # STEP 3: 分類
    classified = step3_classify(client, article, translated)
    if not classified:
        classified = {
            "category_main": article["category_hint"],
            "tags": [],
            "region": ["all"],
            "target_reader": "both",
        }

    # STEP 4: スコアリング
    scored = step4_score(client, article, translated, classified)
    if not scored:
        scored = {"score": 30, "alert_level": "low", "push_notify": False, "notify_channels": []}

    # score が低すぎる記事はSTEP5をスキップ
    if scored["score"] < 30:
        logger.info(f"[STEP4 ✗] スコア低すぎ({scored['score']}): {translated['title_ja'][:40]}")
        return None

    # STEP 5: 整形
    formatted = step5_format(client, article, translated, classified, scored)
    if not formatted:
        # フォールバック
        formatted = {
            "lead_ja":   translated["summary_ja"][:70],
            "body_ja":   translated["summary_ja"],
            "action_ja": translated.get("impact_ja", ""),
        }

    # 最終記事辞書を組み立て
    output = {
        "id":             str(uuid.uuid4()),
        "title_ja":       translated["title_ja"],
        "lead_ja":        formatted["lead_ja"],
        "body_ja":        formatted["body_ja"],
        "action_ja":      formatted.get("action_ja", ""),
        "category_main":  classified["category_main"],
        "alert_level":    scored["alert_level"],
        "score":          scored["score"],
        "tags":           classified.get("tags", []),
        "region":         classified.get("region", ["all"]),
        "target_reader":  classified.get("target_reader", "both"),
        "source_id":      article["source_id"],
        "source_name":    article["source_name"],
        "source_url":     article["url"],
        "source_tier":    article["tier"],
        "original_lang":  article["lang"],
        "collected_at":   article["collected_at"],
        "published_at":   article.get("published_at", article["collected_at"]),
        "key_dates":      translated.get("key_dates", []),
        "push_notify":    scored.get("push_notify", False),
        "notify_channels": scored.get("notify_channels", []),
        "content_hash":   article["content_hash"],
    }

    logger.info(
        f"[DONE] {scored['alert_level'].upper():6s} score={scored['score']:3d} "
        f"| {translated['title_ja'][:40]}"
    )
    return output
