"""Market history ingestion contract.

The Everef/ESI ``average`` field is canonicalized as volume-weighted average
price (VWAP) semantics. The in-game client may label this value as median, but
ingestion contracts should retain the API field name and document it as VWAP.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pyarrow as pa

MARKET_HISTORY_PRIMARY_KEY = ["date", "region_id", "type_id"]
REQUIRED_MARKET_HISTORY_COLUMNS = {
    "date",
    "region_id",
    "type_id",
    "average",
    "highest",
    "lowest",
    "order_count",
    "volume",
}
NUMERIC_MARKET_HISTORY_COLUMNS = {
    "average",
    "highest",
    "lowest",
    "order_count",
    "volume",
}
MARKET_HISTORY_COLUMNS = {
    column_name: {"nullable": False}
    for column_name in sorted(REQUIRED_MARKET_HISTORY_COLUMNS)
}
MARKET_HISTORY_COLUMNS["average"]["description"] = (
    "Volume-weighted average price (VWAP)."
)

MARKET_HISTORY_ARROW_SCHEMA = pa.schema(
    [
        pa.field("date", pa.string(), nullable=False),
        pa.field("region_id", pa.int64(), nullable=False),
        pa.field("type_id", pa.int64(), nullable=False),
        pa.field("average", pa.float64(), nullable=False),
        pa.field("highest", pa.float64(), nullable=False),
        pa.field("lowest", pa.float64(), nullable=False),
        pa.field("order_count", pa.int64(), nullable=False),
        pa.field("volume", pa.int64(), nullable=False),
        pa.field("_source_market_date", pa.string()),
        pa.field("_source_url", pa.string()),
        pa.field("_source_local_path", pa.string()),
        pa.field("_source_sha256", pa.string()),
        pa.field("_source_content_length", pa.int64()),
        pa.field("_source_last_modified", pa.string()),
        pa.field("_source_downloaded_at", pa.string()),
        pa.field("_ingested_at", pa.string()),
    ]
)


def validate_market_history_chunk(
    chunk: pd.DataFrame,
    *,
    file_url: str,
    market_date: str,
    chunk_index: int,
) -> None:
    """Validate one Everef market history CSV chunk before loading."""
    missing_columns = REQUIRED_MARKET_HISTORY_COLUMNS.difference(chunk.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        msg = f"Everef CSV chunk {chunk_index} from {file_url} is missing columns: {missing}"
        raise ValueError(msg)

    key_nulls = chunk[MARKET_HISTORY_PRIMARY_KEY].isna().sum()
    if key_nulls.any():
        msg = (
            f"Everef CSV chunk {chunk_index} from {file_url} contains null primary-key "
            f"values: {key_nulls.to_dict()}"
        )
        raise ValueError(msg)

    duplicated_keys = chunk.duplicated(subset=MARKET_HISTORY_PRIMARY_KEY, keep=False)
    if duplicated_keys.any():
        duplicate_count = int(duplicated_keys.sum())
        msg = (
            f"Everef CSV chunk {chunk_index} from {file_url} contains "
            f"{duplicate_count} duplicate primary-key rows"
        )
        raise ValueError(msg)

    parsed_market_date = date.fromisoformat(market_date)
    parsed_dates = pd.to_datetime(chunk["date"], format="%Y-%m-%d", errors="coerce")
    if parsed_dates.isna().any():
        msg = f"Everef CSV chunk {chunk_index} from {file_url} contains invalid date values"
        raise ValueError(msg)
    if (parsed_dates.dt.date != parsed_market_date).any():
        msg = (
            f"Everef CSV chunk {chunk_index} from {file_url} contains dates that do not "
            f"match source market_date {market_date}"
        )
        raise ValueError(msg)

    numeric_values = chunk[list(NUMERIC_MARKET_HISTORY_COLUMNS)].apply(
        pd.to_numeric,
        errors="coerce",
    )
    invalid_numeric = numeric_values.isna().sum()
    if invalid_numeric.any():
        msg = (
            f"Everef CSV chunk {chunk_index} from {file_url} contains invalid numeric "
            f"values: {invalid_numeric[invalid_numeric > 0].to_dict()}"
        )
        raise ValueError(msg)

    negative_numeric = (numeric_values < 0).sum()
    if negative_numeric.any():
        msg = (
            f"Everef CSV chunk {chunk_index} from {file_url} contains negative numeric "
            f"values: {negative_numeric[negative_numeric > 0].to_dict()}"
        )
        raise ValueError(msg)

    if (numeric_values["highest"] < numeric_values["lowest"]).any():
        msg = f"Everef CSV chunk {chunk_index} from {file_url} contains highest below lowest"
        raise ValueError(msg)
