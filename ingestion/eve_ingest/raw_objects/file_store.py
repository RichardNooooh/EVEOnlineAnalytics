from __future__ import annotations

from typing import TYPE_CHECKING

from eve_ingest.raw_objects.fetch_plan import FetchPlan
from eve_ingest.raw_objects.identity import (
    hash_identity_key,
    normalize_source_path,
    normalize_source_relative_path,
    resolve_identity_key,
)
from eve_ingest.raw_objects.ledger.models import RawObjectRef
from eve_ingest.raw_objects.paths import (
    build_temp_path,
)

if TYPE_CHECKING:
    from pathlib import Path

    from eve_ingest.raw_objects.models import RawObjectRequest
    from eve_ingest.raw_objects.primitives import UpdateMode


class RawObjectFileStore:
    """Plan construction and file path helpers for raw object storage."""

    def __init__(
        self,
        *,
        raw_root: Path,
        source_name: str,
        dataset_name: str,
        update_mode: UpdateMode,
    ) -> None:
        self._raw_root = raw_root
        self._source_name = source_name
        self._dataset_name = dataset_name
        self._update_mode = update_mode

    def build_plan(self, request: RawObjectRequest) -> FetchPlan:
        source_relative_path = (
            normalize_source_path(request.source_path)
            if request.source_path is not None
            else normalize_source_relative_path(request.source_url)
        )
        resolved_identity_key = resolve_identity_key(
            identity_key=request.identity_key,
            source_relative_path=source_relative_path,
        )
        identity_hash = hash_identity_key(resolved_identity_key)

        ref = RawObjectRef(
            source_name=self._source_name,
            dataset_name=self._dataset_name,
            identity_hash=identity_hash,
            identity_key=resolved_identity_key,
            update_mode=self._update_mode,
        )
        return FetchPlan(
            ref=ref,
            source_url=request.source_url,
            source_relative_path=source_relative_path,
            temp_path=str(build_temp_path(raw_root=self._raw_root, ref=ref)),
        )
