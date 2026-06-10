from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from eve_ingest.raw_objects.http_models import (
    ModifiedRead,
    ReadResult,
    ReadStatus,
    RevalidationMetadata,
)
from eve_ingest.raw_objects.ledger.models import CurrentRawObjectState
from eve_ingest.raw_objects.primitives import UpdateMode


def file_exists(path: str | None) -> bool:
    return path is not None and Path(path).exists()


def request_headers_for(state: CurrentRawObjectState, update_mode: UpdateMode) -> Mapping[str, str]:
    if update_mode is not UpdateMode.MUTABLE:
        return {}
    return state.raw_object.revalidation.request_headers()


def revalidation_for_hit(state: CurrentRawObjectState, read_result: ReadResult | None) -> RevalidationMetadata:
    if read_result is None:
        return state.raw_object.revalidation
    return read_result.revalidation


def ensure_downloaded(read_result: ReadResult) -> ModifiedRead:
    if read_result.status is ReadStatus.MODIFIED:
        assert isinstance(read_result, ModifiedRead)
        return read_result
    raise RuntimeError("client returned unexpected outcome without download")
