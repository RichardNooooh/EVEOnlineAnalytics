"""Evidence mechanics for the local market-history revision notebook.

The notebook owns the analytical queries and charts. This module owns file
validation, adjacent-snapshot comparisons, and coverage checks.
"""

from __future__ import annotations

import bz2
import hashlib
import io
import json
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from math import isclose
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.request import urlopen

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

KEY_FIELDS = ("date", "region_id", "type_id")
MARKET_FIELDS = ("average", "highest", "lowest", "order_count", "volume")
METADATA_FIELDS = ("http_last_modified",)
REFERENCE_URL = "https://data.everef.net/reference-data/reference-data-latest.tar.xz"
POLL_TOLERANCE = timedelta(hours=1, seconds=60)

SNAPSHOT_SCHEMA = {
    "date": pl.String,
    "region_id": pl.Int64,
    "type_id": pl.Int64,
    "average": pl.Float64,
    "highest": pl.Float64,
    "lowest": pl.Float64,
    "order_count": pl.Int64,
    "volume": pl.Int64,
    "http_last_modified": pl.String,
}
EVENT_SCHEMA = {
    **SNAPSHOT_SCHEMA,
    "kind": pl.String,
    "observed_at": pl.String,
    "elapsed_hours": pl.Float64,
    "lower_bound_at": pl.String,
    "first_observed": pl.Boolean,
    "invalid_gap": pl.Boolean,
}
EFFECT_SCHEMA = {
    "region_id": pl.Int64,
    "observed_at": pl.String,
    "elapsed_hours": pl.Float64,
    "kind": pl.String,
    "row_effect": pl.Int64,
    "total_isk_traded_delta": pl.Float64,
}
SUMMARY_SCHEMA = {
    "observed_at": pl.String,
    "status": pl.String,
    "archive_path": pl.String,
    "row_count": pl.Int64,
    "total_isk_traded": pl.Float64,
    "comparable": pl.Boolean,
    "note": pl.String,
}
FIRST_SEEN_SCHEMA = {
    "date": pl.String,
    "region_id": pl.Int64,
    "type_id": pl.Int64,
    "first_appeared_valid_at": pl.String,
    "lower_bound_at": pl.String,
    "invalid_gap": pl.Boolean,
    "elapsed_hours": pl.Float64,
    "kind": pl.String,
}
DIAGNOSTIC_SCHEMA = {"kind": pl.String, "detail": pl.String}
INVALID_SCHEMA = {"observed_at": pl.String, "archive_path": pl.String, "error": pl.String}
TIMELINE_SCHEMA = {
    "observed_at": pl.String,
    "status": pl.String,
    "archive_path": pl.String,
    "totals_count": pl.Int64,
    "verified_totals_count": pl.Int64,
    "totals_state_matches_file": pl.Boolean,
}
TYPE_REFERENCE_SCHEMA = {
    "type_id": pl.Int64,
    "type_name": pl.String,
    "group_id": pl.Int64,
    "group_name": pl.String,
    "category_id": pl.Int64,
    "category_name": pl.String,
}
REGION_REFERENCE_SCHEMA = {"region_id": pl.Int64, "region_name": pl.String}


@dataclass
class RevisionEvidence:
    """Validated frames and observation metadata, without retaining old snapshots."""

    market_date: str | None
    baseline_at: datetime | None
    latest_snapshot: pl.DataFrame | None
    timeline: pl.DataFrame
    snapshot_summary: pl.DataFrame
    first_seen: pl.DataFrame
    events: pl.DataFrame
    observed_effects: pl.DataFrame
    totals_review: pl.DataFrame
    invalid_snapshots: pl.DataFrame
    diagnostics: pl.DataFrame

    @property
    def latest_comparable_at(self) -> datetime | None:
        comparable = self.snapshot_summary.filter(pl.col("comparable"))
        if comparable.is_empty():
            return None
        return parse_utc(comparable.get_column("observed_at")[-1])


@dataclass
class ReferenceData:
    types: pl.DataFrame
    regions: pl.DataFrame
    diagnostics: pl.DataFrame
    archive_path: Path | None


@dataclass
class SnapshotComparison:
    events: pl.DataFrame
    effects: pl.DataFrame


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def validate_snapshot(path: Path, market_date: str) -> pl.DataFrame:
    with bz2.open(path, "rb") as archive:
        raw = pl.read_csv(io.BytesIO(archive.read()), infer_schema_length=0)
    required = list(KEY_FIELDS + MARKET_FIELDS + METADATA_FIELDS)
    if any(field not in raw.columns for field in required):
        raise ValueError("snapshot CSV is missing a required header")
    snapshot = raw.select(required)
    if snapshot.null_count().select(pl.any_horizontal(pl.all() > 0)).item():
        raise ValueError("snapshot row is missing a required field")
    try:
        snapshot = snapshot.with_columns(
            pl.col("region_id", "type_id", "order_count", "volume").cast(pl.Int64, strict=True),
            pl.col("average", "highest", "lowest").cast(pl.Float64, strict=True),
        )
    except (ValueError, pl.exceptions.PolarsError) as error:
        raise ValueError("integer or finite numeric validation failed") from error
    if snapshot.filter(pl.any_horizontal(~pl.col("average", "highest", "lowest").is_finite())).height:
        raise ValueError("snapshot prices must be finite")
    if snapshot.filter(pl.col("date") != market_date).height:
        raise ValueError("snapshot row date does not match market_date")
    if snapshot.group_by(list(KEY_FIELDS)).len().filter(pl.col("len") > 1).height:
        raise ValueError("duplicate snapshot key")
    return snapshot


def load_totals_count(path: Path, market_date: str) -> int | None:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError("totals payload must be a JSON object")
    value = payload.get(market_date)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("totals count must be a non-negative integer")
    return value


def review_totals_discrepancies(
    observations: Sequence[Mapping[str, Any]],
    row_counts: Mapping[str, int],
    tolerance: timedelta = timedelta(seconds=60),
) -> list[dict[str, Any]]:
    reviews = []
    for index, observation in enumerate(observations):
        archive_path = observation.get("archive_path")
        actual_count = row_counts.get(archive_path)
        if observation.get("status") != "downloaded" or actual_count is None:
            continue
        observed_at = parse_utc(observation["observed_at"])
        total = observation.get("verified_totals_count")
        review = {
            "archive_path": archive_path,
            "observed_at": observation["observed_at"],
            "actual_row_count": actual_count,
            "observed_totals_count": total,
            "allowance_ends_at": format_utc(observed_at + timedelta(hours=1)),
            "scheduling_deadline_at": format_utc(observed_at + timedelta(hours=1) + tolerance),
            "outcome": "unresolved_insufficient",
        }
        if total == actual_count:
            review["outcome"] = "matched"
            reviews.append(review)
            continue
        for later in observations[index + 1 :]:
            later_path = later.get("archive_path")
            later_count = row_counts.get(later_path)
            later_at = parse_utc(later["observed_at"])
            if later.get("status") == "downloaded" and later_path != archive_path and later_count != actual_count:
                review.update(
                    outcome="superseded_uncertain",
                    later_archive_path=later_path,
                    superseded_at=later["observed_at"],
                )
                break
            if later_count != actual_count or not isinstance(later.get("verified_totals_count"), int):
                continue
            review.update(
                later_archive_path=later_path,
                later_observed_at=later["observed_at"],
                later_totals_count=later["verified_totals_count"],
            )
            if later["verified_totals_count"] == actual_count:
                deadline = observed_at + timedelta(hours=1) + tolerance
                review["outcome"] = "resolved_within_hour" if later_at <= deadline else "unresolved_insufficient"
                break
            if later_at >= observed_at + timedelta(hours=1):
                review["outcome"] = "persistent_mismatch"
                break
        reviews.append(review)
    return reviews


def _event_frame(
    snapshot: pl.DataFrame,
    kind: str,
    observed_at: datetime,
    baseline_at: datetime,
    *,
    lower_bound: datetime | None = None,
    first_observed: bool = False,
    invalid_gap: bool = False,
) -> pl.DataFrame:
    return snapshot.with_columns(
        pl.lit(kind).alias("kind"),
        pl.lit(format_utc(observed_at)).alias("observed_at"),
        pl.lit((observed_at - baseline_at).total_seconds() / 3600).alias("elapsed_hours"),
        pl.lit(format_utc(lower_bound) if lower_bound else None, dtype=pl.String).alias("lower_bound_at"),
        pl.lit(first_observed).alias("first_observed"),
        pl.lit(invalid_gap).alias("invalid_gap"),
    )


def _snapshot_side(joined: pl.DataFrame, suffix: str) -> pl.DataFrame:
    return joined.select(
        list(KEY_FIELDS)
        + [pl.col(f"{field}_{suffix}").alias(field) for field in SNAPSHOT_SCHEMA if field not in KEY_FIELDS]
    )


def _signed_effects(events: pl.DataFrame, row_effect: int) -> pl.DataFrame:
    return events.select(
        "region_id",
        "observed_at",
        "elapsed_hours",
        "kind",
        pl.lit(row_effect, dtype=pl.Int64).alias("row_effect"),
        (pl.col("average") * pl.col("volume") * row_effect).alias("total_isk_traded_delta"),
    )


def compare_snapshot_rows(
    previous: pl.DataFrame,
    current: pl.DataFrame,
    seen_keys: set[tuple[str, int, int]],
    previous_at: datetime,
    observed_at: datetime,
    baseline_at: datetime,
) -> SnapshotComparison:
    """Classify one usable transition; first arrivals are relative to the full ledger."""
    before = previous.rename({field: f"{field}_before" for field in previous.columns if field not in KEY_FIELDS})
    after = current.rename({field: f"{field}_after" for field in current.columns if field not in KEY_FIELDS})
    joined = before.join(after, on=list(KEY_FIELDS), how="full", coalesce=True)
    added = joined.filter(pl.col("average_before").is_null() & pl.col("average_after").is_not_null())
    removed = joined.filter(pl.col("average_before").is_not_null() & pl.col("average_after").is_null())
    common = joined.filter(pl.col("average_before").is_not_null() & pl.col("average_after").is_not_null())
    market_changed = pl.any_horizontal(
        [pl.col(f"{field}_before") != pl.col(f"{field}_after") for field in MARKET_FIELDS]
    )
    metadata_changed = pl.any_horizontal(
        [pl.col(f"{field}_before") != pl.col(f"{field}_after") for field in METADATA_FIELDS]
    )
    modified = common.filter(market_changed)
    metadata_only = common.filter(~market_changed & metadata_changed)
    new_keys = [key for key in added.select(list(KEY_FIELDS)).iter_rows() if key not in seen_keys]
    key_schema = {field: current.schema[field] for field in KEY_FIELDS}
    new_key_frame = pl.DataFrame(new_keys, schema=key_schema, orient="row")
    first_arrivals = added.join(new_key_frame, on=list(KEY_FIELDS), how="inner")
    reappearances = added.join(new_key_frame, on=list(KEY_FIELDS), how="anti")

    event_parts = []
    effect_parts = []
    for rows, kind, suffix, is_first, row_effect in (
        (first_arrivals, "added", "after", True, 1),
        (reappearances, "reappeared", "after", False, 1),
        (removed, "removed", "before", False, -1),
        (modified, "market_values_modified", "after", False, 0),
        (metadata_only, "metadata_only_modified", "after", False, 0),
    ):
        event = _event_frame(
            _snapshot_side(rows, suffix),
            kind,
            observed_at,
            baseline_at,
            lower_bound=previous_at,
            first_observed=is_first,
        )
        event_parts.append(event)
        if row_effect and event.height:
            effect_parts.append(_signed_effects(event, row_effect))
    if modified.height:
        revision_effects = (
            modified.select(
                "region_id",
                (
                    pl.col("average_after") * pl.col("volume_after")
                    - pl.col("average_before") * pl.col("volume_before")
                ).alias("total_isk_traded_delta"),
            )
            .with_columns(
                pl.lit(format_utc(observed_at)).alias("observed_at"),
                pl.lit((observed_at - baseline_at).total_seconds() / 3600).alias("elapsed_hours"),
                pl.lit("market_values_modified").alias("kind"),
                pl.lit(0, dtype=pl.Int64).alias("row_effect"),
            )
            .select(list(EFFECT_SCHEMA))
        )
        effect_parts.append(revision_effects)
    return SnapshotComparison(
        pl.concat(event_parts, how="vertical_relaxed"),
        pl.concat(effect_parts, how="vertical_relaxed") if effect_parts else pl.DataFrame(schema=EFFECT_SCHEMA),
    )


def load_revision_evidence(evidence_dir: Path) -> RevisionEvidence:
    """Read one state checkpoint and stream archives, keeping adjacent frames only."""
    state_path = evidence_dir / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else None
    diagnostics = []
    observations = []
    market_date = None
    if state is None:
        diagnostics.append({"kind": "state", "detail": "No watcher state: run watch.py to collect observations."})
    elif state.get("schema_version") != 1:
        diagnostics.append({"kind": "state", "detail": f"Unsupported schema version {state.get('schema_version')}"})
    else:
        market_date = state.get("market_date")
        observations = sorted(state.get("observations", []), key=lambda row: parse_utc(row["observed_at"]))
        if not market_date or not observations:
            diagnostics.append({"kind": "state", "detail": "No market date or observations: continue watch.py."})
    for observation in observations:
        observation["verified_totals_count"] = None
        observation["totals_state_matches_file"] = None
        totals_path = observation.get("totals_path")
        if isinstance(totals_path, str):
            try:
                count = load_totals_count(evidence_dir / totals_path, market_date)
                observation["verified_totals_count"] = count
                observation["totals_state_matches_file"] = observation.get("totals_count") == count
            except (OSError, ValueError) as error:
                diagnostics.append({"kind": "totals", "detail": f"{observation['observed_at']}: {error}"})
    timeline = (
        pl.from_dicts(observations, schema=TIMELINE_SCHEMA)
        .with_columns(pl.col("observed_at").str.to_datetime(time_zone="UTC").alias("observed_datetime"))
        .sort("observed_datetime")
        .with_columns(pl.col("observed_datetime").diff().dt.total_seconds().truediv(3600).alias("poll_delta_hours"))
        .with_columns((pl.col("poll_delta_hours") > (1 + 2 / 60)).fill_null(False).alias("observation_gap"))
    )

    event_parts, effect_parts, summary, invalid = [], [], [], []
    row_counts, first_seen = {}, {}
    baseline_at = None
    previous_snapshot = latest_snapshot = None
    previous_path = previous_at = None
    previous_total_isk_traded = None

    def record_snapshot(
        observation: dict[str, Any], snapshot: pl.DataFrame | None, total_isk_traded: float | None, note: str
    ):
        summary.append(
            {
                "observed_at": observation["observed_at"],
                "status": observation["status"],
                "archive_path": observation.get("archive_path"),
                "row_count": snapshot.height if snapshot is not None else None,
                "total_isk_traded": total_isk_traded,
                "comparable": snapshot is not None,
                "note": note,
            }
        )

    def remember_first_arrivals(arrivals: pl.DataFrame):
        for row in arrivals.filter(pl.col("first_observed")).iter_rows(named=True):
            key = tuple(row[field] for field in KEY_FIELDS)
            first_seen[key] = {
                "first_appeared_valid_at": row["observed_at"],
                "lower_bound_at": row["lower_bound_at"],
                "invalid_gap": row["invalid_gap"],
                "elapsed_hours": row["elapsed_hours"],
                "kind": row["kind"],
            }

    for observation in observations:
        observed_at = parse_utc(observation["observed_at"])
        archive_path = observation.get("archive_path")
        current = None
        if observation["status"] == "downloaded":
            try:
                current = validate_snapshot(evidence_dir / archive_path, market_date)
                row_counts[archive_path] = current.height
            except (OSError, ValueError, TypeError, EOFError, pl.exceptions.PolarsError) as error:
                invalid.append(
                    {"observed_at": observation["observed_at"], "archive_path": archive_path, "error": str(error)}
                )
                record_snapshot(observation, None, None, "invalid archive/reset")
                previous_snapshot = None
                continue
        elif observation["status"] == "unchanged" and previous_snapshot is not None and archive_path == previous_path:
            current = previous_snapshot
        if current is None:
            record_snapshot(observation, None, None, "no usable archive/reset")
            previous_snapshot = None
            continue
        total_isk_traded = (
            previous_total_isk_traded
            if observation["status"] == "unchanged"
            else current.select((pl.col("average") * pl.col("volume")).sum()).item()
        )
        if baseline_at is None:
            baseline_at = observed_at
            baseline = _event_frame(current, "baseline", observed_at, baseline_at, first_observed=True)
            event_parts.append(baseline)
            effect_parts.append(_signed_effects(baseline, 1))
            remember_first_arrivals(baseline)
            note = "baseline"
        elif observation["status"] == "unchanged":
            note = "same archive"
        elif previous_snapshot is None:
            unseen_keys = [key for key in current.select(list(KEY_FIELDS)).iter_rows() if key not in first_seen]
            key_schema = {field: current.schema[field] for field in KEY_FIELDS}
            unseen = pl.DataFrame(unseen_keys, schema=key_schema, orient="row")
            arrivals = _event_frame(
                current.join(unseen, on=list(KEY_FIELDS), how="inner"),
                "first_appearance_after_invalid_gap",
                observed_at,
                baseline_at,
                first_observed=True,
                invalid_gap=True,
            )
            event_parts.append(arrivals)
            remember_first_arrivals(arrivals)
            note = "reset snapshot; unresolved impact"
        else:
            comparison = compare_snapshot_rows(
                previous_snapshot, current, set(first_seen), previous_at, observed_at, baseline_at
            )
            reconstructed_total = previous_total_isk_traded + comparison.effects["total_isk_traded_delta"].sum()
            assert isclose(total_isk_traded, reconstructed_total, rel_tol=1e-12, abs_tol=1e-8)
            event_parts.append(comparison.events)
            effect_parts.append(comparison.effects)
            remember_first_arrivals(comparison.events)
            note = "compared"
        record_snapshot(observation, current, total_isk_traded, note)
        previous_snapshot = latest_snapshot = current
        previous_path, previous_at, previous_total_isk_traded = archive_path, observed_at, total_isk_traded

    first_seen_rows = [{**dict(zip(KEY_FIELDS, key, strict=True)), **row} for key, row in first_seen.items()]
    reviews = review_totals_discrepancies(observations, row_counts)
    return RevisionEvidence(
        market_date=market_date,
        baseline_at=baseline_at,
        latest_snapshot=latest_snapshot,
        timeline=timeline,
        snapshot_summary=pl.from_dicts(summary, schema=SUMMARY_SCHEMA),
        first_seen=pl.from_dicts(first_seen_rows, schema=FIRST_SEEN_SCHEMA),
        events=pl.concat(event_parts, how="vertical_relaxed") if event_parts else pl.DataFrame(schema=EVENT_SCHEMA),
        observed_effects=pl.concat(effect_parts, how="vertical_relaxed")
        if effect_parts
        else pl.DataFrame(schema=EFFECT_SCHEMA),
        totals_review=pl.from_dicts(reviews) if reviews else pl.DataFrame(schema={"outcome": pl.String}),
        invalid_snapshots=pl.from_dicts(invalid, schema=INVALID_SCHEMA),
        diagnostics=pl.from_dicts(diagnostics, schema=DIAGNOSTIC_SCHEMA),
    )


def cutoff_coverage(snapshot_summary: pl.DataFrame, baseline_at: datetime | None, cutoff_hours: float) -> str:
    if baseline_at is None:
        return "not_enough_cutoff_coverage"
    cutoff_at = baseline_at + timedelta(hours=cutoff_hours)
    comparable = [parse_utc(value) for value in snapshot_summary.filter(pl.col("comparable"))["observed_at"]]
    before = [value for value in comparable if value <= cutoff_at]
    after = [value for value in comparable if value >= cutoff_at]
    intervals = list(pairwise(comparable))
    if any(start < cutoff_at < end and end - start > POLL_TOLERANCE for start, end in intervals):
        return "unknown_gap_crosses_cutoff"
    if before and after and cutoff_at - before[-1] <= POLL_TOLERANCE:
        if any(end - start > POLL_TOLERANCE for start, end in intervals):
            return "available_with_earlier_gap_caveat"
        return "available"
    return "not_enough_cutoff_coverage"


def threshold_table(
    scope: str,
    cohorts: pl.DataFrame,
    effects: pl.DataFrame,
    latest_values: pl.DataFrame,
    coverage: str,
    cutoff_hours: float,
    targets: Sequence[float],
    impact_coverage: str | None = None,
) -> pl.DataFrame:
    """First-observed threshold crossings relative to the latest snapshot."""
    rows = []
    latest_rows = latest_values.height
    latest_total_isk_traded = latest_values["latest_total_isk_traded"].sum()
    views = (
        ("latest_current_cohort", cohorts, "latest_total_isk_traded", None),
        ("as_observed_signed_effects", effects, "total_isk_traded_delta", "row_effect"),
    )
    for view, frame, isk_column, row_column in views:
        view_coverage = impact_coverage if view == "as_observed_signed_effects" and impact_coverage else coverage
        if frame.is_empty():
            rows.append({"scope": scope, "view": view, "measure": "availability", "status": "no_records"})
            continue
        row_expression = pl.len() if row_column is None else pl.col(row_column).sum()
        points = (
            frame.group_by("observed_at", "elapsed_hours")
            .agg(row_expression.alias("rows"), pl.col(isk_column).sum().alias("total_isk_traded"))
            .sort("elapsed_hours")
            .with_columns(
                (pl.col("rows").cum_sum() / latest_rows if latest_rows else pl.lit(None, dtype=pl.Float64)).alias(
                    "row_share"
                ),
                (
                    pl.col("total_isk_traded").cum_sum() / latest_total_isk_traded
                    if latest_total_isk_traded
                    else pl.lit(None, dtype=pl.Float64)
                ).alias("isk_share"),
            )
        )
        cutoff_point = points.filter(pl.col("elapsed_hours") <= cutoff_hours).tail(1)
        for measure, share_column, denominator in (
            ("rows", "row_share", latest_rows),
            ("total_isk_traded", "isk_share", latest_total_isk_traded),
        ):
            available = view_coverage.startswith("available") or view_coverage == "covered"
            rows.append(
                {
                    "scope": scope,
                    "view": view,
                    "measure": f"{measure}_share_at_{cutoff_hours}h",
                    "target": None,
                    "observed_at": None,
                    "elapsed_hours": float(cutoff_hours),
                    "share": cutoff_point[share_column].item() if available and cutoff_point.height else None,
                    "status": view_coverage if denominator else f"zero_{measure}_denominator",
                }
            )
            for target in targets:
                crossing = points.filter(pl.col(share_column) >= target).head(1)
                rows.append(
                    {
                        "scope": scope,
                        "view": view,
                        "measure": measure,
                        "target": target,
                        "observed_at": crossing["observed_at"].item() if crossing.height else None,
                        "elapsed_hours": crossing["elapsed_hours"].item() if crossing.height else None,
                        "share": crossing[share_column].item() if crossing.height else None,
                        "status": (
                            "first_observed"
                            if crossing.height
                            else "threshold_not_reached"
                            if denominator
                            else f"zero_{measure}_denominator"
                        ),
                    }
                )
    return pl.from_dicts(
        rows,
        schema={
            "scope": pl.String,
            "view": pl.String,
            "measure": pl.String,
            "target": pl.Float64,
            "observed_at": pl.String,
            "elapsed_hours": pl.Float64,
            "share": pl.Float64,
            "status": pl.String,
        },
    )


def _acquire_reference_archive(evidence_dir: Path) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    acquired_at = format_utc(datetime.now(UTC))
    temporary_path = evidence_dir / ".reference-data-download.tmp"
    with urlopen(REFERENCE_URL, timeout=10) as response:
        temporary_path.write_bytes(response.read())
    digest = hashlib.sha256(temporary_path.read_bytes()).hexdigest()
    archive_name = f"reference-data-{digest[:16]}.tar.xz"
    temporary_path.replace(evidence_dir / archive_name)
    provenance = evidence_dir / ".reference-data-provenance.tmp"
    provenance.write_text(
        json.dumps(
            {
                "archive_path": archive_name,
                "url": REFERENCE_URL,
                "acquired_utc": acquired_at,
                "sha256": digest,
            },
            indent=2,
        )
    )
    provenance.replace(evidence_dir / "reference-data-provenance.json")


def _reference_frame(payload: dict[str, Any], id_column: str) -> pl.DataFrame:
    return pl.from_dicts([{id_column: key, **value} for key, value in payload.items() if isinstance(value, dict)])


def load_reference_data(evidence_dir: Path, *, acquire: bool = False) -> ReferenceData:
    types = pl.DataFrame(schema=TYPE_REFERENCE_SCHEMA)
    regions = pl.DataFrame(schema=REGION_REFERENCE_SCHEMA)
    diagnostics = []
    archive_path = None
    if acquire:
        try:
            _acquire_reference_archive(evidence_dir)
        except (OSError, ValueError) as error:
            diagnostics.append({"detail": f"Opt-in reference acquisition failed: {error}"})
    try:
        provenance = evidence_dir / "reference-data-provenance.json"
        if provenance.exists():
            archive_path = evidence_dir / json.loads(provenance.read_text())["archive_path"]
        else:
            candidates = sorted(evidence_dir.glob("reference-data-*.tar.xz"))
            archive_path = candidates[-1] if candidates else None
        if archive_path and archive_path.exists():
            with tarfile.open(archive_path, "r:xz") as archive:
                members = {Path(member.name).name: member for member in archive.getmembers()}
                payloads = {}
                for name in ("types.json", "regions.json", "groups.json", "categories.json"):
                    payloads[name] = json.load(archive.extractfile(members[name]))
            type_rows = _reference_frame(payloads["types.json"], "type_id")
            group_rows = _reference_frame(payloads["groups.json"], "group_id").with_columns(
                pl.col("group_id").cast(pl.Int64), pl.col("name").struct.field("en").alias("group_name")
            )
            category_rows = _reference_frame(payloads["categories.json"], "category_id").with_columns(
                pl.col("category_id").cast(pl.Int64), pl.col("name").struct.field("en").alias("category_name")
            )
            types = (
                type_rows.with_columns(
                    pl.col("type_id").cast(pl.Int64),
                    pl.col("group_id", "category_id").cast(pl.Int64, strict=False),
                    pl.col("name").struct.field("en").alias("type_name"),
                )
                .join(group_rows.select("group_id", "group_name"), on="group_id", how="left")
                .join(category_rows.select("category_id", "category_name"), on="category_id", how="left")
                .select(list(TYPE_REFERENCE_SCHEMA))
            )
            regions = (
                _reference_frame(payloads["regions.json"], "region_id")
                .with_columns(
                    pl.col("region_id").cast(pl.Int64), pl.col("name").struct.field("en").alias("region_name")
                )
                .select(list(REGION_REFERENCE_SCHEMA))
            )
    except (OSError, ValueError, KeyError, tarfile.TarError, pl.exceptions.PolarsError) as error:
        diagnostics.append({"detail": f"Cached reference unavailable/corrupt: {error}"})
    return ReferenceData(types, regions, pl.from_dicts(diagnostics, schema={"detail": pl.String}), archive_path)
