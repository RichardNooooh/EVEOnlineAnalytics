from __future__ import annotations

from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.csv as pac

from ingest.cache import CacheResult
from ingest.publishers.ducklake import DuckLakeWriter, RawDuckLakeTable
from ingest.sources.everef.logger import logger
from ingest.util import file_size


def read_csv_to_arrow(result: CacheResult) -> pa.Table:
    path = result.path
    source_date = str(result.identity_key["source_date"])
    content_length = file_size(path)
    expected = result.version.revalidation.content_length
    if expected is not None and content_length != expected:
        logger.warning(
            "File size mismatch for %s: on-disk %d, expected %d",
            source_date,
            content_length,
            expected,
        )
    table = pac.read_csv(path)
    n = len(table)
    logger.debug(
        "Parsed CSV to Arrow source_date=%s rows=%d columns=%d path=%s sha256_prefix=%s",
        source_date,
        n,
        len(table.column_names),
        path,
        result.version.sha256[:16],
    )
    if n == 0:
        logger.warning(
            "Zero-row CSV file source_date=%s path=%s source_url=%s",
            source_date,
            path,
            result.version.source_url,
        )
    now = datetime.now(UTC)

    provenance = [
        ("_source_market_date", pa.array([source_date] * n, type=pa.utf8())),
        ("_source_url", pa.array([result.version.source_url] * n, type=pa.utf8())),
        ("_source_local_path", pa.array([path] * n, type=pa.utf8())),
        ("_source_sha256", pa.array([result.version.sha256] * n, type=pa.utf8())),
        ("_source_content_length", pa.array([content_length] * n, type=pa.int64())),
        ("_source_last_modified", pa.array([result.version.revalidation.last_modified] * n, type=pa.utf8())),
        ("_source_downloaded_at", pa.array([result.version.fetched_at] * n, type=pa.timestamp("us", tz="UTC"))),
        ("_ingested_at", pa.array([now] * n, type=pa.timestamp("us", tz="UTC"))),
    ]
    for name, col in provenance:
        table = table.append_column(name, col)

    return table


def process_result(
    result: CacheResult,
    writer: DuckLakeWriter,
    *,
    table_key: RawDuckLakeTable,
    key_columns: list[str],
) -> bool:
    try:
        writer.write(read_csv_to_arrow(result), table=table_key, key_columns=key_columns)
        return True
    except Exception as e:
        logger.exception("Failed to process %s: %s", result.identity_key, e)
        return False
