"""Send AI news summary to Slack via Incoming Webhook."""

import json
import logging
from datetime import datetime, timezone, timedelta

import requests

from ai_summarizer import SummaryResult

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


class SlackNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def _markdown_to_slack(self, text: str) -> str:
        """Convert basic markdown to Slack mrkdwn format."""
        import re
        # ## Heading -> *Heading*
        text = re.sub(r"^## (.+)$", r"*\1*", text, flags=re.MULTILINE)
        # ### Heading -> *Heading*
        text = re.sub(r"^### (.+)$", r"*\1*", text, flags=re.MULTILINE)
        # **bold** -> *bold*
        text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
        # [text](url) -> <url|text>
        text = re.sub(r"\[(.+?)\]\((.+?)\)", r"<\2|\1>", text)
        return text

    def send(self, result: SummaryResult) -> bool:
        now_jst = datetime.now(JST)
        date_str = now_jst.strftime("%Y年%m月%d日")
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        weekday = weekdays[now_jst.weekday()]

        slack_text = self._markdown_to_slack(result.markdown)

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"AIニュース日報 - {date_str}({weekday})",
                        "emoji": True,
                    }
                },
                {
                    "type": "context",
                    "elements": [{
                        "type": "mrkdwn",
                        "text": f"収集: {result.post_count}件 | AI関連: {result.filtered_count}件"
                    }]
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": slack_text[:3000],
                    }
                },
            ]
        }

        try:
            resp = requests.post(
                self.webhook_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info("Slack notification sent successfully")
                return True
            else:
                logger.error("Slack webhook returned %d: %s", resp.status_code, resp.text)
                return False
        except Exception as e:
            logger.error("Failed to send Slack notification: %s", e)
            return False
