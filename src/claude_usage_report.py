"""Monthly Claude API usage report — fetch from Anthropic Admin API and post to Slack."""

import json
import logging
import os
import sys
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
ANTHROPIC_API_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


class UsageFetcher:
    """Fetch per-member usage from the Anthropic Organization Admin API.

    Requires an Admin API Key (created in the Anthropic Console → API Keys → Admin keys).
    The key needs the "View Usage" or "Admin" permission.
    """

    def __init__(self, admin_key: str):
        self.headers = {
            "x-api-key": admin_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

    def fetch(self, year: int, month: int) -> list[dict]:
        """Return a list of per-member usage records for the given month."""
        start_date = date(year, month, 1).isoformat()
        end_date = date(year, month, monthrange(year, month)[1]).isoformat()

        # Anthropic Admin API: GET /v1/organizations/usage
        # https://docs.anthropic.com/en/api/admin-api/usage
        url = f"{ANTHROPIC_API_BASE}/organizations/usage"
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "granularity": "month",
            "group_by": "workspace_member",
        }

        logger.info("Fetching usage %s – %s", start_date, end_date)
        resp = requests.get(url, headers=self.headers, params=params, timeout=30)

        if resp.status_code == 401:
            logger.error(
                "Authentication failed. Make sure ANTHROPIC_ADMIN_KEY is an Admin API Key "
                "(not a regular API key). Create one in the Anthropic Console → API Keys → Admin keys."
            )
            resp.raise_for_status()

        resp.raise_for_status()

        data = resp.json()

        # Response shape: {"data": [...], "has_more": bool} or plain list
        if isinstance(data, dict) and "data" in data:
            records = data["data"]
            # Handle pagination if the API supports it
            while data.get("has_more") and data.get("last_id"):
                params["starting_after"] = data["last_id"]
                resp = requests.get(url, headers=self.headers, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                records.extend(data.get("data", []))
            return records

        if isinstance(data, list):
            return data

        # Single-object response (unexpected but handle gracefully)
        return [data]


def _extract_name(record: dict) -> str:
    """Extract a human-readable name from a usage record."""
    for path in [
        ("workspace_member", "name"),
        ("workspace_member", "email"),
        ("user", "name"),
        ("user", "email"),
    ]:
        obj = record
        for key in path:
            obj = obj.get(key) if isinstance(obj, dict) else None
        if obj:
            return obj
    return record.get("name") or record.get("email") or "Unknown"


def _token_counts(record: dict) -> tuple[int, int, int, int]:
    """Return (input, output, cache_read, cache_write) token counts."""
    inp = record.get("input_tokens", 0) or 0
    out = record.get("output_tokens", 0) or 0
    cache_read = record.get("cache_read_input_tokens", 0) or 0
    cache_write = record.get("cache_creation_input_tokens", 0) or 0
    return inp, out, cache_read, cache_write


class SlackUsageNotifier:
    """Format usage data and post to a Slack Incoming Webhook."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, year: int, month: int, records: list[dict]) -> bool:
        month_label = f"{year}年{month:02d}月"

        sorted_records = sorted(
            records,
            key=lambda r: sum(_token_counts(r)),
            reverse=True,
        )

        lines: list[str] = []
        grand_input = grand_output = grand_cache_read = grand_cache_write = 0

        for r in sorted_records:
            name = _extract_name(r)
            inp, out, cache_read, cache_write = _token_counts(r)
            total = inp + out + cache_read + cache_write

            grand_input += inp
            grand_output += out
            grand_cache_read += cache_read
            grand_cache_write += cache_write

            cost = r.get("cost_usd") or r.get("total_cost_usd") or 0
            cost_str = f"  `${cost:.4f}`" if cost else ""

            lines.append(f"• *{name}*: {total:,} tokens{cost_str}")

        if not lines:
            lines = ["利用データがありません"]

        grand_total = grand_input + grand_output + grand_cache_read + grand_cache_write
        summary_parts = [f"合計 *{grand_total:,}* tokens"]
        if grand_input:
            summary_parts.append(f"入力 {grand_input:,}")
        if grand_output:
            summary_parts.append(f"出力 {grand_output:,}")
        if grand_cache_read:
            summary_parts.append(f"キャッシュ読込 {grand_cache_read:,}")
        if grand_cache_write:
            summary_parts.append(f"キャッシュ書込 {grand_cache_write:,}")

        body = "\n".join(lines)

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f":bar_chart: Claude API 月次利用レポート — {month_label}",
                        "emoji": True,
                    },
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": body[:3000]},
                },
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": "  |  ".join(summary_parts)}],
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
                logger.info("Slack notification sent")
                return True
            logger.error("Slack webhook returned %d: %s", resp.status_code, resp.text)
            return False
        except Exception as exc:
            logger.error("Failed to send Slack notification: %s", exc)
            return False


def _report_month(now: datetime) -> tuple[int, int]:
    """Return (year, month) for the previous calendar month."""
    first_of_this = now.replace(day=1)
    last_month = first_of_this - timedelta(days=1)
    return last_month.year, last_month.month


def main() -> None:
    admin_key = os.environ.get("ANTHROPIC_ADMIN_KEY")
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL_USAGE") or os.environ.get("SLACK_WEBHOOK_URL")

    if not admin_key:
        logger.error("ANTHROPIC_ADMIN_KEY is not set. Create an Admin API Key in the Anthropic Console.")
        sys.exit(1)
    if not webhook_url:
        logger.error("SLACK_WEBHOOK_URL_USAGE (or SLACK_WEBHOOK_URL) is not set.")
        sys.exit(1)

    year, month = _report_month(datetime.now(JST))
    logger.info("Generating usage report for %d-%02d", year, month)

    fetcher = UsageFetcher(admin_key)
    records = fetcher.fetch(year, month)
    logger.info("Fetched %d member record(s)", len(records))

    notifier = SlackUsageNotifier(webhook_url)
    success = notifier.send(year, month, records)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
