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

    # Search query templates: law name + update keywords
    # Each tuple is (display_name, search_terms)
    laws = [
        # 情報保護
        ("個人情報保護法",               "個人情報保護法 改正 施行 パブコメ"),
        ("個人情報保護法ガイドライン（通則編）",        "個人情報保護法 ガイドライン 通則編 改正 更新"),
        ("個人情報保護法ガイドライン（外国第三者提供編）", "個人情報保護法 ガイドライン 外国 第三者提供 改正"),
        ("個人情報保護法ガイドライン（第三者提供確認・記録義務編）", "個人情報保護法 ガイドライン 第三者提供 確認 記録 改正"),
        ("個人情報保護法ガイドライン（匿名加工情報編）",  "個人情報保護法 ガイドライン 匿名加工情報 改正"),
        ("マイナンバー法",               "マイナンバー法 番号利用法 改正 施行 パブコメ"),
        ("特定個人情報ガイドライン（事業者編）",       "特定個人情報 ガイドライン 事業者 改正 更新"),
        ("労働安全衛生法",               "労働安全衛生法 改正 施行 健康診断 秘密"),
        ("労働者派遣法",                 "労働者派遣法 改正 施行 個人情報"),
        # コンピュータ犯罪
        ("不正アクセス禁止法",            "不正アクセス禁止法 改正 施行 パブコメ"),
        ("刑法（電磁的記録・不正指令電磁的記録等）", "刑法 電磁的記録 不正指令 改正 施行"),
        # 知的財産
        ("著作権法",                     "著作権法 改正 施行 パブコメ"),
        ("不正競争防止法",               "不正競争防止法 改正 施行 パブコメ"),
        # 情報セキュリティ
        ("サイバーセキュリティ基本法",    "サイバーセキュリティ基本法 改正 施行 パブコメ"),
        ("電子署名法",                   "電子署名法 改正 施行 ガイドライン"),
        ("電波法",                       "電波法 改正 施行 秘密保護 パブコメ"),
        ("有線電気通信法",               "有線電気通信法 改正 施行 パブコメ"),
        ("迷惑メール防止法（特定電子メール法）", "特定電子メール法 迷惑メール 改正 施行 パブコメ"),
        ("電気通信事業法",               "電気通信事業法 改正 施行 パブコメ ガイドライン"),
        ("電子帳簿保存法施行規則",        "電子帳簿保存法 施行規則 改正 施行 パブコメ"),
        # その他
        ("電子書面法",                   "電子書面法 民間事業者 書面保存 改正 施行"),
        ("会社法",                       "会社法 改正 施行 パブコメ"),
        ("下請代金支払遅延等防止法",      "下請代金支払遅延等防止法 下請法 改正 施行"),
        ("プロバイダ責任制限法",          "プロバイダ責任制限法 改正 施行 発信者情報"),
        ("IT基本法（高度情報通信ネットワーク社会形成基本法）", "IT基本法 高度情報通信 改正 施行"),
    ]

    law_list = "\n".join(
        f'{i+1:2}. {name}　→ 検索クエリ例: 「{query} {end.year}年{end.month}月」'
        for i, (name, query) in enumerate(laws)
    )

    prompt = f"""\
あなたは情報セキュリティ・ISMS担当者向けの法令規制Weeklyレポートを作成するアシスタントです。

以下の25法令について、{start_str}（月）〜{end_str}（日）の期間内に
「改正」「施行」「ガイドライン更新」「パブリックコメント募集・締切」「重要な行政発表」
があったかどうかを、各法令の検索クエリ例を使ってウェブ検索で調査してください。

{law_list}

【検索の進め方】
- 各法令ごとに検索クエリ例（法令名＋「改正」「施行」「ガイドライン」「パブコメ」等の組み合わせ）で検索する
- ヒットした情報の日付が{start_str}〜{end_str}の範囲内であることを確認する
- 範囲外の古い情報は除外する

【出力ルール】
- 期間内に動きがあった法令のみ出力する（動きがない法令・カテゴリは丸ごと省略する）
- 全法令に動きがない場合はヘッダーと「今週は対象法令のアップデートはありませんでした。」のみ出力する
- 各トピックには必ず出典URLをリンク形式（<URL|リンク名>）で付ける
- Slack mrkdwn形式で出力する（*bold*、>引用、箇条書きなど）

【出力フォーマット】

📋 *情報セキュリティ 法令規制 Weeklyレポート*　{end_str}
対象期間：{start_str}（月）〜 {end_str}（日）

---

*🔔 今週のハイライト*
>（動きがあったトピックを3〜4行で要約）

---

（動きがあったカテゴリのみ以下を出力。カテゴリ内に動きがなければそのカテゴリブロックごと省略）

*■ [カテゴリ名]*

*① [法令名]：[アップデート内容のタイトル]（月日）*
[概要を2〜3文で説明]
- 要点を箇条書き
📎 <URL|参考リンク>

（複数あれば②③と続ける）

---

*📌 来週以降の注目ポイント*
- 今後予定されている施行・改正・パブコメ締切などがあれば記載（なければ省略）"""

    messages = [{"role": "user", "content": prompt}]
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 30}]

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
