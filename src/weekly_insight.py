"""Weekly Claude usage insight - analyze GitHub Actions runs, compare with previous week."""

import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import anthropic
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

INSIGHTS_DIR = Path(__file__).parent.parent / "insights"
JST = timezone(timedelta(hours=9))


def get_analysis_period() -> tuple[date, date]:
    """Return the previous Mon-Sun date range."""
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    prev_monday = this_monday - timedelta(weeks=1)
    prev_sunday = this_monday - timedelta(days=1)
    return prev_monday, prev_sunday


def fetch_workflow_stats(github_token: str, repo: str, start: date, end: date) -> dict:
    """Fetch GitHub Actions workflow run statistics for the period."""
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    workflows_url = f"https://api.github.com/repos/{repo}/actions/workflows"
    resp = requests.get(workflows_url, headers=headers, timeout=15)
    if resp.status_code != 200:
        logger.error("Failed to fetch workflows: %d %s", resp.status_code, resp.text)
        return {}

    workflows = resp.json().get("workflows", [])
    stats = {}

    for wf in workflows:
        wf_id = wf["id"]
        wf_name = wf["name"]

        # GitHub created filter: YYYY-MM-DD..YYYY-MM-DD
        runs_url = f"https://api.github.com/repos/{repo}/actions/workflows/{wf_id}/runs"
        params = {"created": f"{start}..{end}", "per_page": 100}
        runs_resp = requests.get(runs_url, headers=headers, params=params, timeout=15)
        if runs_resp.status_code != 200:
            continue

        runs = runs_resp.json().get("workflow_runs", [])
        if not runs:
            continue

        conclusions = [r.get("conclusion") for r in runs]
        success = sum(1 for c in conclusions if c == "success")
        failure = sum(1 for c in conclusions if c == "failure")
        skipped = sum(1 for c in conclusions if c in ("skipped", "cancelled"))
        total = len(runs)

        durations_sec = []
        for r in runs:
            if r.get("run_started_at") and r.get("updated_at"):
                try:
                    started = datetime.fromisoformat(r["run_started_at"].replace("Z", "+00:00"))
                    updated = datetime.fromisoformat(r["updated_at"].replace("Z", "+00:00"))
                    durations_sec.append((updated - started).total_seconds())
                except Exception:
                    pass

        avg_duration = round(sum(durations_sec) / len(durations_sec)) if durations_sec else None

        stats[wf_name] = {
            "total_runs": total,
            "success": success,
            "failure": failure,
            "skipped": skipped,
            "success_rate_pct": round(success / total * 100, 1) if total > 0 else 0,
            "avg_duration_sec": avg_duration,
        }

    return stats


def load_previous_insight() -> dict | None:
    """Load the most recent previous insight JSON."""
    INSIGHTS_DIR.mkdir(exist_ok=True)
    files = sorted(INSIGHTS_DIR.glob("*.json"), reverse=True)
    if not files:
        return None
    try:
        with open(files[0], encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load previous insight: %s", e)
        return None


def save_insight(data: dict, period_end: date) -> Path:
    """Persist insight data to insights/<date>.json."""
    INSIGHTS_DIR.mkdir(exist_ok=True)
    filepath = INSIGHTS_DIR / f"{period_end}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    logger.info("Saved insight to %s", filepath)
    return filepath


def generate_insight_report(
    client: anthropic.Anthropic,
    start: date,
    end: date,
    current_stats: dict,
    previous: dict | None,
) -> tuple[str, dict]:
    """Ask Claude to analyze the week and compare with previous."""

    start_str = start.strftime("%Y年%-m月%-d日")
    end_str = end.strftime("%Y年%-m月%-d日")

    prev_section = ""
    if previous:
        prev_p = previous.get("period", {})
        prev_section = f"""
---
## 前週の分析データ
期間: {prev_p.get("start", "?")} 〜 {prev_p.get("end", "?")}

### 前週ワークフロー統計
```json
{json.dumps(previous.get("workflow_stats", {}), ensure_ascii=False, indent=2)}
```

### 前週サマリー（参考）
{previous.get("slack_report", "（なし）")}
"""

    prompt = f"""\
あなたはAI活用の週次インサイトレポートを作成するアシスタントです。
以下のデータを分析して、Slackに投稿する週次レポートを作成してください。

## 分析期間
{start_str}（月）〜 {end_str}（日）

## 今週のGitHub Actionsワークフロー実行統計
```json
{json.dumps(current_stats, ensure_ascii=False, indent=2)}
```
{prev_section}

## レポート要件

*必ず含める項目:*
1. 📊 **今週の実行サマリー** — 各ワークフローの実行回数・成功率・主な失敗（あれば）
2. 📈 **前週との比較**（前週データがある場合のみ）
   - ✅ 改善した点
   - ⚠️ 改善していない点・継続課題
3. 💡 **改善提案** — 具体的なアクションがあれば記載
4. 🔭 **来週の注目点** — 注意すべき予定・リスクなど

*フォーマット:*
- Slack mrkdwn形式（*bold*、箇条書き、絵文字）
- 簡潔かつ読みやすく
- 冒頭に1行のハイライトサマリーを入れる"""

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
        system=(
            "あなたはAI活用状況の週次インサイトアナリストです。"
            "データに基づいた客観的な分析と実用的な改善提案を日本語で行ってください。"
        ),
    )

    report_text = resp.content[0].text.strip()

    insight_data = {
        "period": {"start": str(start), "end": str(end)},
        "workflow_stats": current_stats,
        "slack_report": report_text,
        "generated_at": datetime.now(JST).isoformat(),
    }

    return report_text, insight_data


def post_to_slack(webhook_url: str, report: str, period_end: date) -> bool:
    """Post the insight report to Slack, splitting if needed."""
    header = (
        f"🤖 *Claude週次インサイト* — {period_end.strftime('%Y年%-m月%-d日')}週\n\n"
    )
    full_text = header + report

    blocks = []
    chunk_size = 3000
    for i in range(0, len(full_text), chunk_size):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": full_text[i:i + chunk_size]},
        })

    payload = {"blocks": blocks}
    try:
        resp = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Slack message sent")
            return True
        logger.error("Slack returned %d: %s", resp.status_code, resp.text)
        return False
    except Exception as e:
        logger.error("Failed to post to Slack: %s", e)
        return False


def commit_insight(filepath: Path) -> None:
    """Git-add and commit the new insight file."""
    try:
        subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
        subprocess.run(["git", "config", "user.name", "GitHub Actions"], check=True)
        subprocess.run(["git", "add", str(filepath)], check=True)
        subprocess.run(
            ["git", "commit", "-m", f"insight: add weekly report {filepath.stem}"],
            check=True,
        )
        subprocess.run(["git", "push"], check=True)
        logger.info("Committed and pushed %s", filepath.name)
    except subprocess.CalledProcessError as e:
        logger.warning("Git commit/push failed: %s", e)


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    webhook_url = os.environ.get("INSIGHT_SLACK_WEBHOOK_URL")
    github_token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY", "t06901ky/weekly-report")

    if not api_key:
        logger.error("ANTHROPIC_API_KEY is not set")
        sys.exit(1)
    if not webhook_url:
        logger.error("INSIGHT_SLACK_WEBHOOK_URL is not set")
        sys.exit(1)

    start, end = get_analysis_period()
    logger.info("Analyzing period: %s - %s", start, end)

    current_stats = {}
    if github_token:
        logger.info("Fetching workflow stats from GitHub API")
        current_stats = fetch_workflow_stats(github_token, repo, start, end)
        logger.info("Got stats for %d workflows", len(current_stats))
    else:
        logger.warning("GITHUB_TOKEN not set; skipping workflow stats")

    previous = load_previous_insight()
    if previous:
        logger.info("Loaded previous insight from %s", previous.get("period"))

    client = anthropic.Anthropic(api_key=api_key)
    report_text, insight_data = generate_insight_report(client, start, end, current_stats, previous)

    filepath = save_insight(insight_data, end)

    if not post_to_slack(webhook_url, report_text, end):
        sys.exit(1)

    # Commit the new insight file back to the repo
    if os.environ.get("CI"):
        commit_insight(filepath)

    logger.info("Done")


if __name__ == "__main__":
    main()
