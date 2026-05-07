"""Weekly ISMS compliance report - research via Claude web search, post to Slack."""

import json
import logging
import os
import sys
from datetime import date, timedelta

import anthropic
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def get_report_period() -> tuple[date, date]:
    """Return the previous Monday-to-Sunday date range."""
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    prev_monday = this_monday - timedelta(weeks=1)
    prev_sunday = this_monday - timedelta(days=1)
    return prev_monday, prev_sunday


def generate_report(client: anthropic.Anthropic, start: date, end: date) -> str:
    """Use Claude with web search to research last week's security/compliance updates."""

    start_str = start.strftime("%Y年%-m月%-d日")
    end_str = end.strftime("%Y年%-m月%-d日")

    prompt = f"""\
あなたは情報セキュリティ・ISMS担当者向けの法令規制Weeklyレポートを作成するアシスタントです。

{start_str}（月）から{end_str}（日）の期間に発表・公表・報告されたニュースをウェブ検索で調査し、以下のカテゴリに絞ってSlack投稿用レポートを作成してください。

調査カテゴリ:
1. 個人情報保護・プライバシー（個人情報保護委員会の発表、個人情報保護法関連）
2. サイバーセキュリティ規制・ガイドライン（経産省・IPA・NISC・警察庁の発表）
3. 主要なセキュリティインシデント・脆弱性（国内企業の情報漏洩、重大な脆弱性公表）
4. 国際的な規制動向（EU CRA・NIS2・米国規制など）

以下のフォーマットでSlack mrkdwn形式のレポートを作成してください。
実際にその期間に発表されたニュースのみ記載し、見つからない場合は「該当ニュースなし」と記載してください。
各トピックには必ず出典URLをリンク形式（<URL|リンク名>）で付けてください。

---
📋 *情報セキュリティ 法令規制 Weeklyレポート*　{end_str}
対象期間：{start_str}（月）〜 {end_str}（日）

---

*🔔 今週のハイライト*
>（3〜4行で先週の重要トピックを簡潔に要約）

---

*① [トピックタイトル]（月日）*
[概要説明]
- 箇条書きで要点

📎 <URL|参考リンク>

（トピックが複数あれば②③と続ける）

---

*📌 来週の注目ポイント*
- 来週以降に予定される重要な動向・施行予定
---"""

    messages = [{"role": "user", "content": prompt}]
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 10}]

    for attempt in range(15):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8000,
            tools=tools,
            messages=messages,
        )

        logger.info("Claude response stop_reason=%s, content blocks=%d", response.stop_reason, len(response.content))

        if response.stop_reason == "end_turn":
            texts = [b.text for b in response.content if hasattr(b, "text")]
            return "\n".join(texts)

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = [
                {"type": "tool_result", "tool_use_id": b.id, "content": ""}
                for b in response.content
                if b.type == "tool_use"
            ]
            messages.append({"role": "user", "content": tool_results})
        else:
            texts = [b.text for b in response.content if hasattr(b, "text")]
            if texts:
                return "\n".join(texts)
            break

    logger.error("Failed to generate report after max iterations")
    return "レポートの生成に失敗しました。"


def post_to_slack(webhook_url: str, report: str) -> bool:
    payload = {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": report[:3000]},
            }
        ]
    }
    if len(report) > 3000:
        payload["blocks"].append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": report[3000:6000]},
        })

    try:
        resp = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Slack message sent successfully")
            return True
        logger.error("Slack webhook returned %d: %s", resp.status_code, resp.text)
        return False
    except Exception as e:
        logger.error("Failed to send Slack message: %s", e)
        return False


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    webhook_url = os.environ.get("ISMS_SLACK_WEBHOOK_URL")

    if not api_key:
        logger.error("ANTHROPIC_API_KEY is not set")
        sys.exit(1)
    if not webhook_url:
        logger.error("ISMS_SLACK_WEBHOOK_URL is not set")
        sys.exit(1)

    start, end = get_report_period()
    logger.info("Generating report for %s - %s", start, end)

    client = anthropic.Anthropic(api_key=api_key)
    report = generate_report(client, start, end)

    if not post_to_slack(webhook_url, report):
        sys.exit(1)

    logger.info("Done")


if __name__ == "__main__":
    main()
