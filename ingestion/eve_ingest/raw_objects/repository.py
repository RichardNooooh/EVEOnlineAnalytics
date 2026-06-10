"""Repository for raw objects — ledger state loading and state-based dispatch."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from eve_ingest.raw_objects.fetch_plan import FetchPlan
from eve_ingest.raw_objects.http_client import HttpRawObjectClient
from eve_ingest.raw_objects.ledger import RawObjectLedger
from eve_ingest.raw_objects.ledger.models import CurrentRawObjectState, RawObjectEntry
from eve_ingest.raw_objects.models import AcquiredRawObject
from eve_ingest.raw_objects.primitives import UpdateMode
from eve_ingest.raw_objects.store_helpers import file_exists


class RawObjectRepository:
    """Ledger-based state resolution and dispatch for raw objects."""

    def __init__(
        self,
        *,
        ledger: RawObjectLedger,
        update_mode: UpdateMode,
        downloader,
    ) -> None:
        self._ledger = ledger
        self._update_mode = update_mode
        self._downloader = downloader

    # ── ledger state loading ────────────────────────────────────────────────

    def load_current_state(self, ref) -> CurrentRawObjectState | None:
        with self._ledger.transaction() as tx:
            return tx.reader.load_current_states(refs=[ref]).get(ref.identity_hash)

    def load_current_states(self, refs: list) -> dict[str, CurrentRawObjectState | None]:
        if not refs:
            return {}
        with self._ledger.transaction() as tx:
            return tx.reader.load_current_states(refs=refs)

    def load_current_states_for_results(
        self,
        results: Iterable[AcquiredRawObject],
    ) -> dict[str, CurrentRawObjectState | None]:
        refs = [result.raw_object.ref for result in results]
        if not refs:
            return {}
        with self._ledger.transaction() as tx:
            return tx.reader.load_current_states(refs=refs)

    # ── state-based dispatch ────────────────────────────────────────────────

    def get_from_plan(
        self,
        plan: FetchPlan,
        state: CurrentRawObjectState | None,
        *,
        client: HttpRawObjectClient | None = None,
    ) -> AcquiredRawObject:
        if state is None:
            return self._downloader.fetch_new(plan, client=client)

        self._require_update_mode_match(state.raw_object)
        if self._can_use_snapshot_local_hit(plan, state):
            return self._downloader._record_hit(plan, state)

        return self._downloader.revalidate_or_store(plan, state, client=client)

    # ── current-version filtering ───────────────────────────────────────────

    def filter_current_versions(
        self,
        results: list[AcquiredRawObject],
    ) -> tuple[list[AcquiredRawObject], int, int]:
        mutable_results = [result for result in results if result.update_mode is UpdateMode.MUTABLE]
        if not mutable_results:
            return results, 0, 0

        current_states = self.load_current_states_for_results(mutable_results)
        current_results: list[AcquiredRawObject] = []
        stale_count = 0
        missing_stale_count = 0

        for result in results:
            if result.update_mode is not UpdateMode.MUTABLE:
                current_results.append(result)
                continue

            state = current_states.get(result.raw_object.ref.identity_hash)
            is_current = (
                state is not None
                and state.current_version.id == result.version.id
                and state.current_version.sha256 == result.version.sha256
                and state.current_version.local_path == result.version.local_path
            )
            path_exists = Path(result.path).exists()
            if not is_current:
                if not path_exists:
                    missing_stale_count += 1
                else:
                    stale_count += 1
                continue
            if not path_exists:
                raise FileNotFoundError(f"Current cached raw object file is missing: {result.path}")
            current_results.append(result)

        return current_results, stale_count, missing_stale_count

    # ── helpers ─────────────────────────────────────────────────────────────

    def _require_update_mode_match(self, raw_object_entry: RawObjectEntry) -> None:
        if raw_object_entry.ref.update_mode is not self._update_mode:
            raise ValueError(
                "raw object update_mode mismatch: "
                f"stored={raw_object_entry.ref.update_mode.value} requested={self._update_mode.value}"
            )

    def _can_use_snapshot_local_hit(
        self,
        plan: FetchPlan,
        state: CurrentRawObjectState,
    ) -> bool:
        return plan.ref.update_mode is UpdateMode.SNAPSHOT and file_exists(state.current_version.local_path)
