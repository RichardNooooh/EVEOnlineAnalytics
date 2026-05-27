from __future__ import annotations

from collections import defaultdict

from sqlalchemy.engine import Connection

from ingest.cache.ledger.mappers import require_update_mode
from ingest.cache.ledger.reader import RawObjectReader
from ingest.cache.plans import (
    BaseFetchPlan,
    FetchPlan,
    ResolvedFetchPlan,
    UnresolvedFetchPlan,
)


class FetchPlanResolver:
    def __init__(self, con: Connection, reader: RawObjectReader) -> None:
        self._con = con
        self._reader = reader

    def resolve_fetch_plan(self, base_plan: BaseFetchPlan) -> FetchPlan:
        return self.resolve_fetch_plans([base_plan])[0]

    def resolve_fetch_plans(self, base_plans: list[BaseFetchPlan]) -> list[FetchPlan]:
        if not base_plans:
            return []

        grouped_plans: dict[tuple[str, str], list[BaseFetchPlan]] = defaultdict(list)
        for base_plan in base_plans:
            grouped_plans[base_plan.ref.group_key].append(base_plan)

        resolved_by_identity: dict[tuple[str, str, str], FetchPlan] = {}
        for (source_name, dataset_name), plans in grouped_plans.items():
            raw_objects = self._reader.load_raw_objects(
                group_key=(source_name, dataset_name),
                identity_hashes=[plan.ref.identity_hash for plan in plans],
            )
            current_versions = self._reader.load_latest_versions([raw_object.id for raw_object in raw_objects.values()])
            for plan in plans:
                raw_object = raw_objects.get(plan.ref.identity_hash)
                require_update_mode(raw_object, plan.update_mode)
                if raw_object is None:
                    resolved: FetchPlan = UnresolvedFetchPlan(
                        ref=plan.ref,
                        source_url=plan.source_url,
                        source_relative_path=plan.source_relative_path,
                        update_mode=plan.update_mode,
                        identity_key=plan.identity_key,
                        temp_path=plan.temp_path,
                    )
                else:
                    current_version = current_versions.get(raw_object.id)
                    if current_version is None:
                        raise RuntimeError(f"Ledger corruption: raw_object {raw_object.id} exists but has no versions")
                    resolved = ResolvedFetchPlan(
                        ref=plan.ref,
                        source_url=plan.source_url,
                        source_relative_path=plan.source_relative_path,
                        update_mode=plan.update_mode,
                        identity_key=plan.identity_key,
                        temp_path=plan.temp_path,
                        raw_object=raw_object,
                        current_version=current_version,
                    )
                resolved_by_identity[(plan.ref.source_name, plan.ref.dataset_name, plan.ref.identity_hash)] = resolved

        return [
            resolved_by_identity[(plan.ref.source_name, plan.ref.dataset_name, plan.ref.identity_hash)]
            for plan in base_plans
        ]
