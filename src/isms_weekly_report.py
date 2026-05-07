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

以下の【監視対象法令一覧】に記載されている25の法令・ガイドラインについて、
{start_str}（月）から{end_str}（日）の期間に発表・公表された
「改正」「施行」「ガイドライン更新」「パブリックコメント募集」「重要な行政発表」
をウェブ検索で調査してください。

【監視対象法令一覧】

■ 情報保護に関する法令
1.  個人情報の保護に関する法律（個人情報保護法）
2.  個人情報保護法ガイドライン（通則編）
3.  個人情報保護法ガイドライン（外国にある第三者への提供編）
4.  個人情報保護法ガイドライン（第三者提供時の確認・記録義務編）
5.  個人情報保護法ガイドライン（匿名加工情報編）
6.  マイナンバー法（行政手続における特定の個人を識別するための番号の利用等に関する法律）
7.  特定個人情報の適正な取扱いに関するガイドライン（事業者編）
8.  労働安全衛生法（第105条：健康診断等の秘密保持）
9.  労働者派遣法（第24条の3・4：個人情報取扱・秘密保持）

■ コンピュータ犯罪に関する法令
10. 不正アクセス行為の禁止等に関する法律（不正アクセス禁止法）
11. 刑法（電磁的記録不正作出、不正指令電磁的記録、名誉棄損、電子計算機損壊等業務妨害、詐欺等）

■ 知的財産権に関する法令
12. 著作権法
13. 不正競争防止法

■ 情報セキュリティに関する法令
14. サイバーセキュリティ基本法
15. 電子署名及び認証業務に関する法律（電子署名法）
16. 電波法（第59条・第109条）
17. 有線電気通信法
18. 特定電子メールの送信の適正化等に関する法律（迷惑メール防止法）
19. 電気通信事業法（第4条・第179条）
20. 電子計算機を使用して作成する国税関係帳簿書類の保存方法等の特例に関する法律施行規則（電子帳簿保存法施行規則）

■ その他
21. 民間事業者等が行う書面の保存等における情報通信の技術の利用に関する法律（電子書面法）
22. 会社法
23. 下請代金支払遅延等防止法
24. 特定電気通信役務提供者の損害賠償責任の制限及び発信者情報の開示に関する法律（プロバイダ責任制限法）
25. 高度情報通信ネットワーク社会形成基本法（IT基本法）

【出力ルール】
- 上記期間内に実際に動きがあった法令のみ記載する（動きがないものは省略）
- 動きが1件もない場合は「今週は対象法令に関するアップデートはありませんでした。」とだけ出力する
- 各トピックには必ず出典URLをリンク形式（<URL|リンク名>）で付ける
- Slack mrkdwn形式で出力する

【出力フォーマット】

📋 *情報セキュリティ 法令規制 Weeklyレポート*　{end_str}
対象期間：{start_str}（月）〜 {end_str}（日）

---

*🔔 今週のハイライト*
>（動きがあったトピックを3〜4行で要約。なければ「今週は主要な動きはありませんでした。」）

---

*① [法令名]：[アップデート内容のタイトル]（月日）*
[概要を2〜3文で説明]
- 要点を箇条書き

📎 <URL|参考リンク>

（動きがある法令ごとに②③と続ける）

---

*📌 来週以降の注目ポイント*
- 今後予定されている施行・改正・パブリックコメント締切などがあれば記載"""

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
