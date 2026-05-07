# AI News Bot

X (Twitter) と YouTube を毎日巡回し、AIニュースをまとめて Slack に送る Bot。

## アーキテクチャ

```
EventBridge (毎朝8時JST)
    → Lambda
        → Nitter RSS (X投稿収集)
        → YouTube RSS (動画収集)
        → Claude API (AIニュースフィルタ + 日本語要約)
        → Slack Webhook (通知)
        → S3 (既読管理)
```

## セットアップ

### 1. 監視対象の設定

`config/sources.yaml` を編集してXアカウントとYouTubeチャンネルを設定:

```yaml
x_accounts:
  - sama          # Sam Altman
  - karpathy      # Andrej Karpathy
  # ...

youtube_channels:
  - UCbmNph6atAoGfqLoCL_duAg  # Two Minute Papers
  # ...
```

**YouTubeチャンネルIDの調べ方:**
チャンネルページを開き、URLの `/channel/UC...` 部分をコピー。
または `https://www.youtube.com/@チャンネル名/about` を右クリック → ページのソースから `channelId` を検索。

### 2. Slack Incoming Webhook の設定

1. Slack App を作成: https://api.slack.com/apps
2. "Incoming Webhooks" を有効化
3. ワークスペースに追加してWebhook URLを取得

### 3. Anthropic API Key の取得

https://console.anthropic.com/ でAPIキーを発行。

### 4. AWS へのデプロイ

```bash
# AWS SAM CLI のインストール
pip install aws-sam-cli

# 依存パッケージをsrcにコピー
pip install -r requirements.txt -t src/vendor/

# ビルド & デプロイ
sam build
sam deploy --guided \
  --parameter-overrides \
    AnthropicApiKey=sk-ant-... \
    SlackWebhookUrl=https://hooks.slack.com/services/...
```

### 5. ローカルテスト

```bash
cp .env.example .env
# .env を編集して各APIキーを設定

pip install -r requirements.txt
cd src
python main.py
```

## 注意事項

### X (Twitter) について
- X公式APIは使用していません。Nitter (OSSミラー) のRSSを利用します
- Nitterインスタンスの可用性に依存します。`config/sources.yaml` の `nitter_instances` を複数設定することで自動フォールバックします
- 「フォロー全体」の取得はAPIなしでは困難なため、監視したいアカウントを明示的にリストアップしてください

### コスト目安 (月額)
- Lambda: 無料枠内 (月30回実行)
- S3: ~$0.01
- Claude Haiku API: ~$0.10〜$0.50 (投稿数による)
- 合計: ほぼ無料〜数十円

## ファイル構成

```
.
├── src/
│   ├── collectors/
│   │   ├── x_collector.py        # X投稿収集 (Nitter RSS)
│   │   └── youtube_collector.py  # YouTube動画収集 (RSS)
│   ├── ai_summarizer.py          # Claude APIで要約
│   ├── slack_notifier.py         # Slack通知
│   ├── state_manager.py          # S3で既読管理
│   └── main.py                   # Lambdaハンドラー
├── config/
│   └── sources.yaml              # 監視対象・設定
├── template.yaml                 # AWS SAM テンプレート
├── requirements.txt
└── .env.example
```
