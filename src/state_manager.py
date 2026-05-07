"""Track seen post IDs in S3 to avoid duplicates."""

import json
import logging
from datetime import datetime, timezone, timedelta

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class StateManager:
    def __init__(self, bucket: str, region: str = "ap-northeast-1"):
        self.bucket = bucket
        self.s3 = boto3.client("s3", region_name=region)
        self.key = "seen_ids.json"

    def _load(self) -> dict:
        try:
            resp = self.s3.get_object(Bucket=self.bucket, Key=self.key)
            return json.loads(resp["Body"].read())
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return {"ids": [], "updated_at": None}
            raise

    def _save(self, data: dict) -> None:
        self.s3.put_object(
            Bucket=self.bucket,
            Key=self.key,
            Body=json.dumps(data),
            ContentType="application/json",
        )

    def filter_new(self, post_ids: list[str]) -> list[str]:
        data = self._load()
        seen = set(data.get("ids", []))
        return [pid for pid in post_ids if pid not in seen]

    def mark_seen(self, post_ids: list[str]) -> None:
        data = self._load()
        seen = set(data.get("ids", []))

        # 30日以上前のIDは削除してS3サイズを抑制
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        # IDにタイムスタンプが含まれないため全IDを保持（最大10000件で制限）
        seen.update(post_ids)
        if len(seen) > 10000:
            seen = set(list(seen)[-10000:])

        self._save({
            "ids": list(seen),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("Marked %d posts as seen (total: %d)", len(post_ids), len(seen))
