"""X (Twitter) posts via Nitter RSS feeds."""

import feedparser
import requests
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


@dataclass
class Post:
    id: str
    source: str
    author: str
    text: str
    url: str
    published_at: datetime


class XCollector:
    def __init__(self, nitter_instances: list[str], accounts: list[str]):
        self.nitter_instances = nitter_instances
        self.accounts = accounts
        self.timeout = 10

    def _fetch_rss(self, url: str) -> feedparser.FeedParserDict | None:
        for instance in self.nitter_instances:
            feed_url = url.format(instance=instance)
            try:
                resp = requests.get(feed_url, timeout=self.timeout, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; AINewsBot/1.0)"
                })
                if resp.status_code == 200:
                    feed = feedparser.parse(resp.text)
                    if feed.entries:
                        return feed
                    logger.warning("Empty feed from %s", feed_url)
            except Exception as e:
                logger.warning("Failed to fetch %s: %s", feed_url, e)
        return None

    def _parse_published(self, entry) -> datetime:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        return datetime.now(timezone.utc)

    def collect(self, since_hours: int = 24) -> list[Post]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        posts = []

        for account in self.accounts:
            feed = self._fetch_rss("{instance}/" + account + "/rss")
            if not feed:
                logger.warning("Could not fetch X feed for @%s", account)
                continue

            for entry in feed.entries:
                published = self._parse_published(entry)
                if published < cutoff:
                    continue

                post_id = entry.get("id", entry.get("link", ""))
                text = entry.get("summary", entry.get("title", ""))
                url = entry.get("link", "")

                posts.append(Post(
                    id=f"x_{post_id}",
                    source="x",
                    author=f"@{account}",
                    text=text,
                    url=url,
                    published_at=published,
                ))

            logger.info("Collected %d posts from @%s", len(posts), account)

        return posts
