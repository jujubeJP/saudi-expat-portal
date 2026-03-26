"""
情報源設定ファイル
Tier / URL / カテゴリヒント / 収集間隔 を一元管理
"""

SOURCES = [
    # ──────────────────────────────────────────────
    # Tier 1: 公式・政府系（収集間隔: 60分）
    # ──────────────────────────────────────────────
    {
        "id": "mofa_anzen",
        "name": "外務省 海外安全情報（サウジ）",
        "tier": 1,
        "type": "rss",
        "url": "https://www.anzen.mofa.go.jp/rss/anzen_spot.xml",
        "category_hint": "safety",
        "interval_minutes": 60,
        "lang": "ja",
        "filter_keywords": ["サウジ", "Saudi"],  # 絞り込みキーワード
        "alert_override": True,  # Tier1安全情報は強制的にalert_level=urgent候補
    },
    {
        "id": "embassy_riyadh",
        "name": "在サウジアラビア日本国大使館",
        "tier": 1,
        "type": "scrape",
        "url": "https://www.sa.emb-japan.go.jp/itprtop_ja/index.html",
        "category_hint": "safety",
        "interval_minutes": 60,
        "lang": "ja",
        "scrape_config": {
            "news_list_selector": ".news-list li, .information-list li",
            "title_selector": "a",
            "link_attr": "href",
            "base_url": "https://www.sa.emb-japan.go.jp",
        },
        "alert_override": True,
    },

    # ──────────────────────────────────────────────
    # Tier 2: 主要英字メディア（収集間隔: 6時間）
    # ──────────────────────────────────────────────
    {
        "id": "arab_news",
        "name": "Arab News",
        "tier": 2,
        "type": "rss",
        "url": "https://www.arabnews.com/rss.xml",
        "category_hint": "news_general",
        "interval_minutes": 360,
        "lang": "en",
        "filter_keywords": [],  # 空=全件取得
    },
    {
        "id": "arab_news_saudi",
        "name": "Arab News - Saudi Arabia",
        "tier": 2,
        "type": "rss",
        "url": "https://www.arabnews.com/taxonomy/term/2/feed",
        "category_hint": "news_general",
        "interval_minutes": 360,
        "lang": "en",
    },
    {
        "id": "saudi_gazette",
        "name": "Saudi Gazette",
        "tier": 2,
        "type": "rss",
        "url": "https://saudigazette.com.sa/feed",
        "category_hint": "news_general",
        "interval_minutes": 360,
        "lang": "en",
    },
    {
        "id": "expatica_sa",
        "name": "Expatica Saudi Arabia",
        "tier": 2,
        "type": "scrape",
        "url": "https://www.expatica.com/sa/",
        "category_hint": "daily_life",
        "interval_minutes": 720,  # 12時間
        "lang": "en",
        "scrape_config": {
            "news_list_selector": "article.article-card",
            "title_selector": "h2, h3",
            "link_selector": "a.article-card__link",
            "link_attr": "href",
            "base_url": "https://www.expatica.com",
        },
    },

    # ──────────────────────────────────────────────
    # Tier 1追加: 政府ポータル（週次チェック）
    # ──────────────────────────────────────────────
    {
        "id": "hrsd_gov",
        "name": "HRSD（人的資源・社会開発省）",
        "tier": 1,
        "type": "scrape",
        "url": "https://www.hrsd.gov.sa/en/news",
        "category_hint": "business",
        "interval_minutes": 1440,  # 24時間
        "lang": "en",
        "scrape_config": {
            "news_list_selector": ".news-item, .media-list li",
            "title_selector": "h3, h4, a",
            "link_attr": "href",
            "base_url": "https://www.hrsd.gov.sa",
        },
    },
    {
        "id": "moh_sehhaty",
        "name": "MOH / Sehhaty",
        "tier": 1,
        "type": "scrape",
        "url": "https://www.moh.gov.sa/en/Ministry/MediaCenter/News/Pages/default.aspx",
        "category_hint": "healthcare",
        "interval_minutes": 1440,
        "lang": "en",
        "scrape_config": {
            "news_list_selector": ".news-item a, .ms-listviewtable td a",
            "title_selector": "a",
            "link_attr": "href",
            "base_url": "https://www.moh.gov.sa",
        },
    },
]

# 主カテゴリ定義
CATEGORIES = [
    "safety", "visa", "healthcare", "business",
    "daily_life", "education", "culture", "news_general"
]

# 表示用日本語タグ名
TAGS_DISPLAY_JA = {
    "visa_update": "ビザ改定",
    "iqama": "iqama",
    "exit_reentry": "出国・再入国",
    "labor_law": "労働法",
    "saudization": "Saudization",
    "vat_tax": "VAT・税制",
    "healthcare_hospital": "病院",
    "infectious_disease": "感染症",
    "vaccine": "ワクチン",
    "traffic_transport": "交通",
    "housing": "住居",
    "grocery": "食料品",
    "school_japanese": "日本人学校",
    "school_international": "インター校",
    "family": "家族帯同",
    "ramadan": "ラマダン",
    "national_day": "建国記念日",
    "hajj": "ハッジ",
    "culture_rule": "文化ルール",
    "emergency_alert": "緊急情報",
    "crime_security": "治安",
    "natural_disaster": "自然災害",
    "driving_license": "運転免許",
    "banking": "銀行・金融",
    "telecom": "通信",
    "riyadh": "リヤド",
    "jeddah": "ジッダ",
    "eastern_province": "東部州",
}
