from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eve_ingest.raw_objects import AcquiredRawObject

logger = logging.getLogger(__name__)


def parse_last_modified_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            logger.warning("Could not parse last_modified timestamp value=%r", value)
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def build_source_object_metadata(
    result: AcquiredRawObject,
    source_system: str,
    endpoint: str,
    *,
    source_ref_id: str,
    source_market_date: date | None = None,
    snapshot_ts: datetime | None = None,
) -> dict:
    return {
        "source_ref_id": source_ref_id,
        "source_system": source_system,
        "endpoint": endpoint,
        "source_url": result.version.source_url,
        "storage_uri": result.path,
        "source_market_date": source_market_date,
        "snapshot_ts": snapshot_ts,
        "last_modified": parse_last_modified_timestamp(result.version.revalidation.last_modified),
        "content_length": result.version.revalidation.content_length,
        "sha256": result.version.sha256,
        "downloaded_at": result.version.fetched_at,
        "status": "downloaded",
    }
