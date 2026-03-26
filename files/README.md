# 在サウジ邦人ポータル — セットアップガイド

自動収集 → AI処理 → サイト生成 → デプロイの全自動ループを構築する手順です。

---

## 全体フロー

```
GitHub Actions (cron)
  └─ main.py --source {id}     ← 収集 + Claude API処理
       └─ data/articles.json   ← 記事DB（Gitで管理 or Supabase）
       └─ generate_site.py     ← 静的HTML生成
            └─ site/           ← GitHub Pages へデプロイ
                 ├─ index.html
                 ├─ search.html
                 ├─ glossary.html
                 └─ articles/{id}.html
```

---

## Step 1: リポジトリの準備

```bash
# リポジトリ作成後
git clone https://github.com/あなたのアカウント/saudi-expat-portal.git
cd saudi-expat-portal

# このプロジェクトのファイルをすべてコピー
cp -r /path/to/saudi_agent/* .

# 必要ディレクトリを作成
mkdir -p data site

# データファイルを初期化
echo '[]' > data/articles.json

# .gitignoreを設定
cat > .gitignore << 'EOF'
.env
__pycache__/
*.pyc
logs/
.DS_Store
EOF

git add .
git commit -m "init: プロジェクト初期化"
git push
```

---

## Step 2: GitHub Secrets の設定

リポジトリの **Settings → Secrets and variables → Actions → New repository secret** で以下を登録。

### 必須
| Secret名 | 内容 | 取得方法 |
|----------|------|---------|
| `ANTHROPIC_API_KEY` | Claude APIキー | [console.anthropic.com](https://console.anthropic.com) |

### Supabase使用時（推奨）
| Secret名 | 内容 |
|----------|------|
| `SUPABASE_URL` | `https://xxxx.supabase.co` |
| `SUPABASE_KEY` | anon/service role key |

> **Supabaseを使わない場合:** `data/articles.json` がGitリポジトリに直接コミットされます。
> 記事が増えると容量が大きくなるため、長期運用にはSupabaseを推奨します。

### 通知（任意）
| Secret名 | 内容 |
|----------|------|
| `LINE_NOTIFY_TOKEN` | LINE Notify トークン（[notify-bot.line.me](https://notify-bot.line.me/ja/)）|
| `SMTP_HOST` | 例: `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | Gmailアドレス |
| `SMTP_PASS` | Googleアプリパスワード（16文字） |
| `NOTIFY_EMAIL` | 通知送信先メールアドレス |

---

## Step 3: GitHub Pages の有効化

1. リポジトリ **Settings → Pages**
2. Source: **GitHub Actions** を選択（または `gh-pages` ブランチ）
3. 保存

初回デプロイ後、`https://あなたのアカウント.github.io/saudi-expat-portal/` でアクセス可能になります。

---

## Step 4: Supabase のセットアップ（任意・推奨）

```sql
-- Supabase SQL Editor で実行

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

CREATE INDEX idx_articles_score       ON articles(score DESC);
CREATE INDEX idx_articles_alert_level ON articles(alert_level);
CREATE INDEX idx_articles_category    ON articles(category_main);
CREATE INDEX idx_articles_collected   ON articles(collected_at DESC);
CREATE INDEX idx_articles_hash        ON articles(content_hash);

ALTER TABLE articles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read" ON articles FOR SELECT USING (true);
```

---

## Step 5: 初回動作確認

### ローカルでテスト（APIキー不要）
```bash
python test_pipeline.py
python generate_site.py --output site
open site/index.html
```

### ローカルで実収集テスト
```bash
cp .env.example .env
# .env を編集してAPIキーを設定

# 外務省RSSを1件だけドライランで確認
python main.py --dry-run --source mofa_anzen
```

### GitHub Actionsで手動実行
1. **Actions タブ → 収集 Tier1 → Run workflow**
2. `dry_run: true` でまず確認
3. 問題なければ `dry_run: false` で本番実行

---

## 自動実行スケジュール

| ワークフロー | 実行タイミング | 対象 |
|------------|--------------|------|
| `collect-tier1.yml` | **毎時15分** | 大使館・外務省・MOH |
| `collect-tier2.yml` | **6時間ごと** | Arab News・Saudi Gazette・Expatica |
| `collect-daily.yml` | **毎日 JST 02:00** | HRSD・省庁スクレイプ |
| 週次ダイジェスト | **毎週月曜 JST 02:00** | メール配信 |
| `ci.yml` | **push時** | 構造テスト |
| `deploy.yml` | **手動** | 緊急再デプロイ |

> GitHub Actions の無料枠：パブリックリポジトリは**無制限**。
> プライベートリポジトリは月2,000分。本プロジェクトは月約 300〜400分の見込み。

---

## カスタマイズ

### 情報源を追加する
`config/sources.py` にエントリを追加するだけで次回収集から反映されます。

```python
{
    "id":               "jacci",
    "name":             "JACCI（日本商工会議所リヤド）",
    "tier":             2,
    "type":             "scrape",
    "url":              "https://jacci.or.jp/news/",
    "category_hint":    "business",
    "interval_minutes": 1440,
    "lang":             "ja",
    "scrape_config": {
        "news_list_selector": ".news-list li",
        "title_selector":     "a",
        "link_attr":          "href",
        "base_url":           "https://jacci.or.jp",
    },
},
```

### 用語を追加する
`data/glossary.json` に JSON オブジェクトを追加して `deploy.yml` を手動実行。

### カテゴリを追加する
1. `config/sources.py` の `CATEGORIES` リストに追記
2. `pipeline.py` の `SYSTEM_CLASSIFY` プロンプトに追記
3. `generate_site.py` の `cat_label()` 関数に追記

---

## トラブルシューティング

### Actions が失敗する
- **Secret未設定**: `ANTHROPIC_API_KEY` が設定されているか確認
- **タイムアウト**: `timeout-minutes` を延長（スクレイプが遅いサイトが原因のことが多い）
- **ファイルが変更されない**: Supabaseに保存している場合は `articles.json` は変更されない（正常）

### サイトが更新されない
- `gh-pages` ブランチが存在するか確認
- **Actions → deploy** を手動実行

### 記事が増えすぎる
`data/articles.json` のサイズが大きくなる場合は Supabase に移行するか、
`storage.py` の保持件数上限（現在1000件）を調整してください。

---

## ディレクトリ構成（最終）

```
saudi-expat-portal/
├── .github/
│   └── workflows/
│       ├── ci.yml
│       ├── collect-tier1.yml
│       ├── collect-tier2.yml
│       ├── collect-daily.yml
│       └── deploy.yml
├── config/
│   └── sources.py          ← 情報源定義
├── data/
│   ├── articles.json       ← 記事DB
│   └── glossary.json       ← 用語集データ
├── site/                   ← 生成済みサイト（GitHub Pages）
│   ├── index.html
│   ├── search.html
│   ├── glossary.html
│   └── articles/
├── collector.py
├── generate_site.py
├── main.py
├── notifier.py
├── pipeline.py
├── storage.py
├── test_pipeline.py
├── requirements.txt
├── .env.example
└── README.md
```
