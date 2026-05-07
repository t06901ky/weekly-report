"""YouTube videos via public RSS feeds (no API key required)."""

import feedparser
import requests
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

from .x_collector import Post

logger = logging.getLogger(__name__)

YOUTUBE_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


class YouTubeCollector:
    def __init__(self, channel_ids: list[str]):
        self.channel_ids = channel_ids
        self.timeout = 10

    def _parse_published(self, entry) -> datetime:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        return datetime.now(timezone.utc)

    def collect(self, since_hours: int = 24) -> list[Post]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        posts = []

        for channel_id in self.channel_ids:
            url = YOUTUBE_RSS_URL.format(channel_id=channel_id)
            try:
                resp = requests.get(url, timeout=self.timeout)
                if resp.status_code != 200:
                    logger.warning("Failed to fetch YouTube feed for %s: HTTP %d", channel_id, resp.status_code)
                    continue

                feed = feedparser.parse(resp.text)
                channel_name = feed.feed.get("title", channel_id)

                for entry in feed.entries:
                    published = self._parse_published(entry)
                    if published < cutoff:
                        continue

                    video_id = entry.get("yt_videoid", entry.get("id", ""))
                    title = entry.get("title", "")
                    url = entry.get("link", f"https://www.youtube.com/watch?v={video_id}")
                    description = entry.get("summary", "")

                    posts.append(Post(
                        id=f"yt_{video_id}",
                        source="youtube",
                        author=channel_name,
                        text=f"{title}\n{description[:300]}",
                        url=url,
                        published_at=published,
                    ))

                logger.info("Collected %d videos from %s", len([p for p in posts if p.author == channel_name]), channel_name)

            except Exception as e:
                logger.warning("Error fetching YouTube feed for %s: %s", channel_id, e)

        return posts
