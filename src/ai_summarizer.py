"""Filter and summarize AI news posts using Claude API."""

import logging
from dataclasses import dataclass

import anthropic

from collectors.x_collector import Post

logger = logging.getLogger(__name__)

FILTER_PROMPT = """\
以下の投稿リストを確認して、AIニュースとして価値のある投稿だけを選んでください。

選ぶ基準:
- AI・機械学習・LLM・生成AIに関する重要なニュースや発表
- 研究成果、新モデルのリリース、製品発表
- 業界の重要な動向や考察

除外する基準:
- 単なる宣伝・PR
- AI以外のトピック
- リツイート/引用で既出の情報

投稿リスト:
{posts}

レスポンスはJSON配列で返してください。各要素は以下の形式:
{{
  "id": "投稿ID",
  "reason": "選んだ理由（日本語・1行）"
}}

AIニュースに該当しない場合は空配列 [] を返してください。"""

SUMMARY_PROMPT = """\
以下のAIニュース投稿を日本語でまとめてください。

投稿:
{posts}

出力形式:
- 冒頭に今日のAIニュースの一言サマリー（1文）
- トピックごとにグループ化して箇条書き
- 各トピックは「タイトル」「内容（1-2文）」「出典リンク」を含める
- 最後に「今日のポイント」を3点以内でまとめる

マークダウン形式で出力してください。"""


@dataclass
class SummaryResult:
    markdown: str
    post_count: int
    filtered_count: int


class AISummarizer:
    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def _format_posts_for_prompt(self, posts: list[Post]) -> str:
        lines = []
        for p in posts:
            lines.append(f"[{p.id}] {p.author} ({p.source})\n{p.text}\nURL: {p.url}\n")
        return "\n---\n".join(lines)

    def filter_posts(self, posts: list[Post]) -> list[Post]:
        if not posts:
            return []

        posts_text = self._format_posts_for_prompt(posts)

        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": FILTER_PROMPT.format(posts=posts_text)
                }],
                system="あなたはAIニュースのキュレーターです。JSON以外の余分なテキストを出力しないでください。",
            )

            import json
            content = resp.content[0].text.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            selected = json.loads(content)
            selected_ids = {item["id"] for item in selected}
            filtered = [p for p in posts if p.id in selected_ids]
            logger.info("Filtered %d -> %d posts", len(posts), len(filtered))
            return filtered

        except Exception as e:
            logger.error("Filter failed: %s", e)
            return posts

    def summarize(self, posts: list[Post]) -> SummaryResult:
        original_count = len(posts)
        filtered = self.filter_posts(posts)

        if not filtered:
            return SummaryResult(
                markdown="本日はAI関連の新しいニュースがありませんでした。",
                post_count=original_count,
                filtered_count=0,
            )

        posts_text = self._format_posts_for_prompt(filtered)

        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                messages=[{
                    "role": "user",
                    "content": SUMMARY_PROMPT.format(posts=posts_text)
                }],
                system="あなたはAIニュースのライターです。わかりやすく、簡潔な日本語で書いてください。",
            )

            summary = resp.content[0].text.strip()
            return SummaryResult(
                markdown=summary,
                post_count=original_count,
                filtered_count=len(filtered),
            )

        except Exception as e:
            logger.error("Summarization failed: %s", e)
            raise
