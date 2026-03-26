"""
notifier.py — プッシュ通知モジュール

対応チャネル:
  • LINE Notify（個人トークン方式）
  • メール（SMTP）
  • コンソール出力（デバッグ・フォールバック）
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

ALERT_EMOJI = {
    "urgent": "🚨",
    "high":   "⚠️",
    "medium": "📌",
    "low":    "ℹ️",
}


# ──────────────────────────────────────────────────────
# LINE Notify
# ──────────────────────────────────────────────────────

def send_line(article: dict) -> bool:
    """
    LINE Notifyで緊急記事を通知する。
    トークンは LINE_NOTIFY_TOKEN 環境変数から取得。
    """
    token = os.getenv("LINE_NOTIFY_TOKEN", "")
    if not token or token == "your_line_notify_token":
        logger.warning("[LINE] トークン未設定 → スキップ")
        return False

    emoji  = ALERT_EMOJI.get(article["alert_level"], "📋")
    level  = article["alert_level"].upper()
    title  = article["title_ja"]
    lead   = article.get("lead_ja", "")
    action = article.get("action_ja", "")
    url    = article.get("source_url", "")

    message_parts = [
        f"\n{emoji} [{level}] {title}",
        lead,
    ]
    if action:
        message_parts.append(f"▶ {action}")
    if url and url != "#":
        message_parts.append(f"🔗 {url}")

    message = "\n\n".join(p for p in message_parts if p)

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                "https://notify-api.line.me/api/notify",
                headers={"Authorization": f"Bearer {token}"},
                data={"message": message},
            )
            resp.raise_for_status()
        logger.info(f"[LINE] 通知送信成功: {title[:40]}")
        return True
    except httpx.HTTPError as e:
        logger.error(f"[LINE] 送信失敗: {e}")
        return False


# ──────────────────────────────────────────────────────
# メール通知
# ──────────────────────────────────────────────────────

def send_email_alert(article: dict) -> bool:
    """緊急記事をSMTPメールで通知する。"""
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    to_email  = os.getenv("NOTIFY_EMAIL", "")

    if not all([smtp_host, smtp_user, smtp_pass, to_email]):
        logger.warning("[EMAIL] SMTP設定不完全 → スキップ")
        return False

    emoji = ALERT_EMOJI.get(article["alert_level"], "📋")
    subject = f"{emoji} 【サウジ情報】{article['title_ja']}"

    body_html = f"""
<html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;">
<div style="background:#1A1510;color:#F5EFE0;padding:20px;border-radius:8px 8px 0 0;">
  <div style="font-size:12px;opacity:0.6;">サウジ在住邦人ポータル</div>
  <h2 style="margin:8px 0 0;font-size:18px;">{emoji} {article['title_ja']}</h2>
</div>
<div style="padding:20px;border:1px solid #ddd;border-top:none;border-radius:0 0 8px 8px;">
  <p style="color:#666;font-size:12px;">
    アラートレベル: <strong>{article['alert_level'].upper()}</strong> |
    スコア: {article['score']} |
    情報源: {article['source_name']} (Tier {article['source_tier']})
  </p>
  <p style="font-size:15px;line-height:1.7;">{article.get('lead_ja','')}</p>
  <p style="font-size:14px;line-height:1.7;color:#333;">{article.get('body_ja','')}</p>
  {"<div style='background:#E8F3EC;border-left:3px solid #1F6B4A;padding:12px;border-radius:4px;font-size:13px;'><strong>▶ とるべき行動:</strong><br>" + article['action_ja'] + "</div>" if article.get('action_ja') else ''}
  <hr style="border:0;border-top:1px solid #eee;margin:16px 0;">
  <p style="font-size:11px;color:#999;">
    情報源: <a href="{article.get('source_url','#')}">{article['source_name']}</a> |
    収集: {article['collected_at'][:16]}
  </p>
</div>
</body></html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = smtp_user
        msg["To"]      = to_email
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_email, msg.as_string())

        logger.info(f"[EMAIL] 送信成功: {article['title_ja'][:40]}")
        return True
    except Exception as e:
        logger.error(f"[EMAIL] 送信失敗: {e}")
        return False


# ──────────────────────────────────────────────────────
# 週次ダイジェスト生成
# ──────────────────────────────────────────────────────

def generate_digest_text(articles: list[dict], calendar_info: str = "") -> str:
    """
    週次ダイジェストのメール本文（プレーンテキスト）を生成する。
    Claude APIを使うのが理想だが、フォールバックとして自動生成も可。
    """
    now = __import__("datetime").datetime.now()
    week_str = now.strftime("%Y年%m月%d日")

    lines = [
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"サウジ在住邦人ポータル 週次ダイジェスト",
        f"{week_str} 号",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "【今週のハイライト】",
        "",
    ]

    # urgent / high の記事を最大3件
    top = [a for a in articles if a.get("alert_level") in ("urgent", "high")][:3]
    for i, a in enumerate(top, 1):
        emoji = ALERT_EMOJI.get(a["alert_level"], "📌")
        lines.append(f"{i}. {emoji} {a['title_ja']}")
        lines.append(f"   {a.get('lead_ja', '')[:80]}")
        if a.get("action_ja"):
            lines.append(f"   ▶ {a['action_ja'][:60]}")
        lines.append("")

    # カテゴリ別まとめ
    cat_labels = {
        "safety":      "🚨 安全・治安",
        "visa":        "🛂 ビザ・在留",
        "healthcare":  "🏥 医療・健康",
        "business":    "💼 ビジネス",
        "daily_life":  "🏠 生活情報",
        "education":   "📚 教育",
        "culture":     "🕌 文化・宗教",
        "news_general":"📰 一般ニュース",
    }
    lines.append("【カテゴリ別まとめ】")
    lines.append("")

    for cat_id, cat_label in cat_labels.items():
        cat_articles = [a for a in articles if a.get("category_main") == cat_id][:3]
        if cat_articles:
            lines.append(f"◆ {cat_label}")
            for a in cat_articles:
                lines.append(f"  • {a['title_ja']}")
            lines.append("")

    if calendar_info:
        lines.append("【翌週の重要日程】")
        lines.append(calendar_info)
        lines.append("")

    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "本メールはサウジ在住邦人ポータルから自動送信されています。",
        "重要な判断は必ず公式情報源でご確認ください。",
        "配信停止: (配信停止URLをここに挿入)",
    ]

    return "\n".join(lines)


def send_weekly_digest(articles: list[dict], dry_run: bool = False) -> bool:
    """週次ダイジェストをメール送信する。"""
    smtp_user = os.getenv("SMTP_USER", "")
    to_email  = os.getenv("NOTIFY_EMAIL", "")

    digest_text = generate_digest_text(articles)

    if dry_run:
        logger.info("[DRY RUN] 週次ダイジェスト（送信せず出力）:\n" + digest_text[:500] + "...")
        return True

    if not smtp_user or not to_email:
        logger.warning("[EMAIL] 週次ダイジェスト: SMTP未設定")
        return False

    # メール送信はsend_email_alertと同じSMTP設定を流用
    try:
        now = __import__("datetime").datetime.now()
        subject = f"【週次】サウジ在住邦人ポータル {now.strftime('%m/%d')}号"
        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"]    = smtp_user
        msg["To"]      = to_email
        msg.attach(MIMEText(digest_text, "plain", "utf-8"))

        with smtplib.SMTP(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT", 587))) as s:
            s.starttls()
            s.login(smtp_user, os.getenv("SMTP_PASS", ""))
            s.sendmail(smtp_user, to_email, msg.as_string())

        logger.info("[EMAIL] 週次ダイジェスト送信完了")
        return True
    except Exception as e:
        logger.error(f"[EMAIL] 週次ダイジェスト失敗: {e}")
        return False


# ──────────────────────────────────────────────────────
# ディスパッチャー
# ──────────────────────────────────────────────────────

def notify(article: dict, dry_run: bool = False) -> None:
    """
    記事のnotify_channelsに基づいて通知を発火する。
    dry_run=Trueの場合はログ出力のみ。
    """
    channels = article.get("notify_channels", [])
    if not channels or not article.get("push_notify"):
        return

    emoji = ALERT_EMOJI.get(article["alert_level"], "📋")
    logger.info(
        f"{emoji} 通知発火: [{article['alert_level'].upper()}] {article['title_ja'][:40]}"
        f" → {channels}"
    )

    if dry_run:
        return

    if "line" in channels:
        send_line(article)
    if "email" in channels:
        send_email_alert(article)
