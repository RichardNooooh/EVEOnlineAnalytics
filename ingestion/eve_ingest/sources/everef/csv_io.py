from __future__ import annotations

import logging
import time

import pyarrow as pa
import pyarrow.csv as pac

from eve_ingest.raw_objects import AcquiredRawObject
from eve_ingest.util import file_size

logger = logging.getLogger("eve_ingest.sources.everef")


def _elapsed_seconds(start_time: float) -> float:
    return time.perf_counter() - start_time


def parse_csv_to_arrow(
    result: AcquiredRawObject,
    *,
    read_options: pac.ReadOptions | None = None,
    parse_options: pac.ParseOptions | None = None,
    convert_options: pac.ConvertOptions | None = None,
) -> pa.Table:
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
    parse_started_at = time.perf_counter()
    table = pac.read_csv(
        path,
        read_options=read_options,
        parse_options=parse_options,
        convert_options=convert_options,
    )
    n = len(table)
    logger.debug(
        "Parsed CSV to Arrow source_date=%s rows=%d columns=%d path=%s sha256_prefix=%s duration_seconds=%.3f",
        source_date,
        n,
        len(table.column_names),
        path,
        result.version.sha256[:16],
        _elapsed_seconds(parse_started_at),
    )
    if n == 0:
        logger.warning(
            "Zero-row CSV file source_date=%s path=%s source_url=%s",
            source_date,
            path,
            result.version.source_url,
        )
    return table
