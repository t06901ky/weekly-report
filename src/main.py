"""AWS Lambda handler for daily AI news bot."""

import json
import logging
import os
import sys

import yaml

# Lambda環境でのパス設定
sys.path.insert(0, os.path.dirname(__file__))

from collectors.x_collector import XCollector
from collectors.youtube_collector import YouTubeCollector
from ai_summarizer import AISummarizer
from slack_notifier import SlackNotifier
from state_manager import StateManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "sources.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


def handler(event, context):
    """Lambda entrypoint."""
    try:
        config = load_config()

        anthropic_api_key = os.environ["ANTHROPIC_API_KEY"]
        slack_webhook_url = os.environ["SLACK_WEBHOOK_URL"]
        s3_bucket = os.environ.get("S3_BUCKET", config["aws"]["s3_bucket"])
        aws_region = os.environ.get("AWS_REGION", config["aws"]["region"])
        since_hours = int(os.environ.get("SINCE_HOURS", "24"))

        # コレクター初期化
        x_collector = XCollector(
            nitter_instances=config["nitter_instances"],
            accounts=config["x_accounts"],
        )
        yt_collector = YouTubeCollector(
            channel_ids=config["youtube_channels"],
        )

        # 投稿収集
        logger.info("Collecting posts from X and YouTube (last %dh)...", since_hours)
        x_posts = x_collector.collect(since_hours=since_hours)
        yt_posts = yt_collector.collect(since_hours=since_hours)
        all_posts = x_posts + yt_posts
        logger.info("Collected %d posts total (X: %d, YouTube: %d)", len(all_posts), len(x_posts), len(yt_posts))

        if not all_posts:
            logger.info("No posts collected, skipping.")
            return {"statusCode": 200, "body": "No posts collected"}

        # 重複排除
        state = StateManager(bucket=s3_bucket, region=aws_region)
        new_ids = state.filter_new([p.id for p in all_posts])
        new_posts = [p for p in all_posts if p.id in set(new_ids)]
        logger.info("New posts after dedup: %d / %d", len(new_posts), len(all_posts))

        if not new_posts:
            logger.info("No new posts after dedup, skipping.")
            return {"statusCode": 200, "body": "No new posts"}

        # AI要約
        summarizer = AISummarizer(api_key=anthropic_api_key)
        result = summarizer.summarize(new_posts)

        # Slack通知
        notifier = SlackNotifier(webhook_url=slack_webhook_url)
        success = notifier.send(result)

        # 送信成功したら既読マーク
        if success:
            state.mark_seen(new_ids)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "collected": len(all_posts),
                "new": len(new_posts),
                "ai_news": result.filtered_count,
                "slack_sent": success,
            })
        }

    except Exception as e:
        logger.exception("Bot failed: %s", e)
        return {"statusCode": 500, "body": str(e)}


if __name__ == "__main__":
    # ローカルテスト用
    result = handler({}, None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
