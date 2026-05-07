"""Daily AI news bot - collect from X/YouTube, summarize with Claude, post to Slack."""

import logging
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(__file__))

from collectors.x_collector import XCollector
from collectors.youtube_collector import YouTubeCollector
from ai_summarizer import AISummarizer
from slack_notifier import SlackNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "sources.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


def main() -> None:
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    slack_webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    since_hours = int(os.environ.get("SINCE_HOURS", "24"))

    if not anthropic_api_key:
        logger.error("ANTHROPIC_API_KEY is not set")
        sys.exit(1)
    if not slack_webhook_url:
        logger.error("SLACK_WEBHOOK_URL is not set")
        sys.exit(1)

    config = load_config()

    x_collector = XCollector(
        nitter_instances=config["nitter_instances"],
        accounts=config["x_accounts"],
    )
    yt_collector = YouTubeCollector(
        channel_ids=config["youtube_channels"],
    )

    logger.info("Collecting posts (last %dh)...", since_hours)
    x_posts = x_collector.collect(since_hours=since_hours)
    yt_posts = yt_collector.collect(since_hours=since_hours)
    all_posts = x_posts + yt_posts
    logger.info("Collected %d posts (X: %d, YouTube: %d)", len(all_posts), len(x_posts), len(yt_posts))

    summarizer = AISummarizer(api_key=anthropic_api_key)
    result = summarizer.summarize(all_posts)

    notifier = SlackNotifier(webhook_url=slack_webhook_url)
    success = notifier.send(result)

    if not success:
        logger.error("Failed to send Slack notification")
        sys.exit(1)

    logger.info("Done. Collected: %d, AI news: %d", result.post_count, result.filtered_count)


if __name__ == "__main__":
    main()
