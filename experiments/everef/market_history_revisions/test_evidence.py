"""Regression checks for evidence mechanics; no real evidence or network writes."""

from __future__ import annotations

import bz2
import csv
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import polars as pl

from experiments.everef.market_history_revisions.evidence import (
    KEY_FIELDS,
    MARKET_FIELDS,
    METADATA_FIELDS,
    cutoff_coverage,
    format_utc,
    load_reference_data,
    load_revision_evidence,
    load_totals_count,
    parse_utc,
    review_totals_discrepancies,
    threshold_table,
    validate_snapshot,
)

MARKET_DATE = "2026-01-01"
BASELINE = parse_utc("2026-01-02T00:00:00Z")
FORGE_REGION_ID = 10000002


def market_row(type_id=1, *, average="10", volume="2", modified="a"):
    return {
        "date": MARKET_DATE,
        "region_id": FORGE_REGION_ID,
        "type_id": type_id,
        "average": average,
        "highest": average,
        "lowest": average,
        "order_count": "1",
        "volume": volume,
        "http_last_modified": modified,
    }


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.evidence_dir = Path(self.temporary.name)
        self.observations = []

    def write_snapshot(self, name, rows, fields=None):
        path = self.evidence_dir / name
        with bz2.open(path, "wt", newline="") as archive:
            writer = csv.DictWriter(archive, fieldnames=fields or list(KEY_FIELDS + MARKET_FIELDS + METADATA_FIELDS))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def poll(self, hour, *, status="unchanged", archive_path="baseline.csv.bz2", count=1):
        totals_path = f"totals-{hour}.json"
        (self.evidence_dir / totals_path).write_text(json.dumps({MARKET_DATE: count}))
        observation = {
            "observed_at": format_utc(BASELINE + timedelta(hours=hour)),
            "status": status,
            "archive_path": archive_path,
            "totals_path": totals_path,
            "totals_count": count,
        }
        self.observations.append(observation)
        return observation

    def load(self):
        state = {"schema_version": 1, "market_date": MARKET_DATE, "observations": self.observations}
        (self.evidence_dir / "state.json").write_text(json.dumps(state))
        return load_revision_evidence(self.evidence_dir)

    def test_snapshot_validation_and_numeric_dtypes(self):
        path = self.write_snapshot("valid.csv.bz2", [market_row(average="10.25")])
        snapshot = validate_snapshot(path, MARKET_DATE)
        self.assertEqual(snapshot["average"].item(), 10.25)
        for field in ("average", "highest", "lowest"):
            self.assertEqual(snapshot.schema[field], pl.Float64)
        for field in ("region_id", "type_id", "order_count", "volume"):
            self.assertEqual(snapshot.schema[field], pl.Int64)
        bad_rows = {
            "date": [{**market_row(), "date": "wrong"}],
            "integer": [{**market_row(), "region_id": "1.5"}],
            "nan": [market_row(average="NaN")],
            "infinity": [market_row(average="inf")],
            "duplicate": [market_row(), market_row()],
        }
        for name, rows in bad_rows.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_snapshot(self.write_snapshot(f"{name}.csv.bz2", rows), MARKET_DATE)
        with self.assertRaises(ValueError):
            validate_snapshot(self.write_snapshot("header.csv.bz2", [{"bad": "x"}], ["bad"]), MARKET_DATE)

    def test_transitions_separate_arrivals_reappearances_and_revisions(self):
        self.write_snapshot("baseline.csv.bz2", [market_row(1), market_row(2)])
        self.write_snapshot("second.csv.bz2", [market_row(2, average="11"), market_row(3)])
        self.write_snapshot(
            "third.csv.bz2", [market_row(1, average="10.0"), market_row(2, average="11", modified="b"), market_row(3)]
        )
        self.poll(0, status="downloaded", count=2)
        self.poll(1, status="downloaded", archive_path="second.csv.bz2", count=2)
        self.poll(2, status="downloaded", archive_path="third.csv.bz2", count=3)
        evidence = self.load()
        counts = dict(evidence.events.group_by("kind").len().iter_rows())
        self.assertEqual(
            counts,
            {
                "baseline": 2,
                "added": 1,
                "removed": 1,
                "reappeared": 1,
                "market_values_modified": 1,
                "metadata_only_modified": 1,
            },
        )
        self.assertEqual(evidence.first_seen.height, 3)
        self.assertAlmostEqual(evidence.observed_effects["total_isk_traded_delta"].sum(), 62.0)
        self.assertEqual(evidence.snapshot_summary["total_isk_traded"].to_list(), [40.0, 42.0, 62.0])
        self.assertEqual(evidence.snapshot_summary.schema["total_isk_traded"], pl.Float64)
        self.assertEqual(evidence.observed_effects.schema["total_isk_traded_delta"], pl.Float64)

    def test_equivalent_numeric_formatting_does_not_create_revision(self):
        self.write_snapshot("baseline.csv.bz2", [market_row(average="10")])
        self.write_snapshot("later.csv.bz2", [market_row(average="10.0")])
        self.poll(0, status="downloaded")
        self.poll(1, status="downloaded", archive_path="later.csv.bz2")
        self.assertEqual(self.load().events["kind"].to_list(), ["baseline"])

    def test_invalid_archive_breaks_comparison_but_not_first_seen_ledger(self):
        self.write_snapshot("baseline.csv.bz2", [market_row(1)])
        (self.evidence_dir / "invalid.csv.bz2").write_bytes(b"not an archive")
        self.write_snapshot("reset.csv.bz2", [market_row(1), market_row(2)])
        self.write_snapshot("later.csv.bz2", [market_row(1), market_row(2), market_row(3)])
        self.poll(0, status="downloaded")
        self.poll(1, status="downloaded", archive_path="invalid.csv.bz2")
        self.poll(2, status="downloaded", archive_path="reset.csv.bz2", count=2)
        self.poll(3, status="downloaded", archive_path="later.csv.bz2", count=3)
        evidence = self.load()
        self.assertEqual(evidence.first_seen.height, evidence.latest_snapshot.height)
        uncertain = evidence.first_seen.filter(pl.col("type_id") == 2)
        self.assertTrue(uncertain["invalid_gap"].item())
        self.assertIsNone(uncertain["lower_bound_at"].item())
        self.assertEqual(evidence.invalid_snapshots.height, 1)
        self.assertEqual(evidence.snapshot_summary["note"][2], "reset snapshot; unresolved impact")

    def test_unchanged_polls_extend_coverage_and_tighten_arrival_bounds(self):
        self.write_snapshot("baseline.csv.bz2", [market_row(1)])
        self.write_snapshot("later.csv.bz2", [market_row(1), market_row(2)])
        self.poll(0, status="downloaded")
        for hour in range(1, 30):
            self.poll(hour)
        self.poll(30, status="downloaded", archive_path="later.csv.bz2", count=2)
        evidence = self.load()
        self.assertEqual(cutoff_coverage(evidence.snapshot_summary, evidence.baseline_at, 24), "available")
        self.assertEqual(evidence.latest_comparable_at, BASELINE + timedelta(hours=30))
        self.assertEqual(
            evidence.first_seen.filter(pl.col("type_id") == 2)["lower_bound_at"].item(),
            format_utc(BASELINE + timedelta(hours=29)),
        )

    def test_gap_crossing_cutoff_and_failed_polls_are_not_coverage(self):
        self.write_snapshot("baseline.csv.bz2", [market_row()])
        self.poll(0, status="downloaded")
        for hour in range(1, 24):
            self.poll(hour)
        self.poll(30, status="downloaded")
        evidence = self.load()
        self.assertEqual(
            cutoff_coverage(evidence.snapshot_summary, evidence.baseline_at, 24), "unknown_gap_crosses_cutoff"
        )
        for observation in self.observations[1:-1]:
            observation["status"] = "error"
        evidence = self.load()
        self.assertEqual(
            cutoff_coverage(evidence.snapshot_summary, evidence.baseline_at, 12), "unknown_gap_crosses_cutoff"
        )

    def test_revision_delta_is_numeric(self):
        self.write_snapshot("baseline.csv.bz2", [market_row(average="10.25", volume="3")])
        self.write_snapshot("later.csv.bz2", [market_row(average="12.50", volume="4")])
        self.poll(0, status="downloaded")
        self.poll(1, status="downloaded", archive_path="later.csv.bz2")
        evidence = self.load()
        impact = evidence.observed_effects.filter(pl.col("kind") == "market_values_modified")[
            "total_isk_traded_delta"
        ].item()
        self.assertAlmostEqual(impact, 19.25)
        self.assertEqual(evidence.snapshot_summary["total_isk_traded"].to_list(), [30.75, 50.0])

    def test_retained_totals_are_verified_instead_of_trusting_state(self):
        self.write_snapshot("baseline.csv.bz2", [market_row()])
        self.poll(0, status="downloaded")
        (self.evidence_dir / "totals-0.json").write_text(json.dumps({MARKET_DATE: 999}))
        evidence = self.load()
        self.assertFalse(evidence.timeline["totals_state_matches_file"].item())
        self.assertEqual(evidence.totals_review["observed_totals_count"].item(), 999)
        (self.evidence_dir / "totals-0.json").write_text(json.dumps({MARKET_DATE: True}))
        with self.assertRaises(ValueError):
            load_totals_count(self.evidence_dir / "totals-0.json", MARKET_DATE)
        self.assertEqual(self.load().diagnostics.height, 1)

    def test_empty_and_missing_evidence_remain_inspectable(self):
        missing = load_revision_evidence(self.evidence_dir)
        self.assertIsNone(missing.baseline_at)
        self.assertTrue(missing.events.is_empty())
        self.assertTrue(self.load().snapshot_summary.is_empty())
        self.poll(0, status="missing", archive_path=None)
        self.assertIsNone(self.load().latest_snapshot)

    def test_reference_cache_does_not_fetch_unless_requested(self):
        with patch("experiments.everef.market_history_revisions.evidence.urlopen") as request:
            reference = load_reference_data(self.evidence_dir)
            request.assert_not_called()
            self.assertTrue(reference.types.is_empty())
            request.side_effect = OSError("offline")
            reference = load_reference_data(self.evidence_dir, acquire=True)
            self.assertIn("acquisition failed", reference.diagnostics["detail"].item())


class TotalsLagTests(unittest.TestCase):
    def review(self, seconds, later_total=1):
        observations = [
            {
                "status": "downloaded",
                "archive_path": "a",
                "observed_at": format_utc(BASELINE),
                "verified_totals_count": 0,
            },
            {
                "status": "unchanged",
                "archive_path": "a",
                "observed_at": format_utc(BASELINE + timedelta(seconds=seconds)),
                "verified_totals_count": later_total,
            },
        ]
        return review_totals_discrepancies(observations, {"a": 1})[0]["outcome"]

    def test_one_hour_lag_and_scheduling_tolerance(self):
        self.assertEqual(self.review(3660), "resolved_within_hour")
        self.assertEqual(self.review(3661), "unresolved_insufficient")
        self.assertEqual(self.review(3600, later_total=0), "persistent_mismatch")


class ThresholdTests(unittest.TestCase):
    def test_thresholds_use_latest_denominator_and_numeric_shares(self):
        cohorts = pl.DataFrame(
            {
                "observed_at": [format_utc(BASELINE), format_utc(BASELINE + timedelta(hours=30))],
                "elapsed_hours": [0.0, 30.0],
                "latest_total_isk_traded": [85.0, 15.0],
            }
        )
        effects = cohorts.select("observed_at", "elapsed_hours").with_columns(
            pl.lit(1).alias("row_effect"), cohorts["latest_total_isk_traded"].alias("total_isk_traded_delta")
        )
        for scope in ("global", "forge"):
            result = threshold_table(scope, cohorts, effects, cohorts, "available", 12, [0.90])
            crossings = result.filter((pl.col("measure") == "total_isk_traded") & (pl.col("target") == 0.90))
            self.assertEqual(crossings["elapsed_hours"].to_list(), [30.0, 30.0])
            self.assertEqual(result.schema["share"], pl.Float64)
            self.assertEqual(result.schema["target"], pl.Float64)
            cutoff = result.filter(pl.col("measure").str.contains("_share_at_"))
            self.assertTrue(all(value == 12.0 for value in cutoff["elapsed_hours"]))
            isk_cutoff = cutoff.filter(pl.col("measure") == "total_isk_traded_share_at_12h")
            for share in isk_cutoff["share"]:
                self.assertAlmostEqual(share, 0.85)

    def test_zero_isk_and_reset_impacts_are_explicit(self):
        cohorts = pl.DataFrame({"observed_at": ["a"], "elapsed_hours": [0.0], "latest_total_isk_traded": [0.0]})
        effects = pl.DataFrame(
            {"observed_at": ["a"], "elapsed_hours": [0.0], "total_isk_traded_delta": [0.0], "row_effect": [1]}
        )
        result = threshold_table(
            "global", cohorts, effects, cohorts, "available", 24, [0.90], "unresolved_reset_impact"
        )
        zero = result.filter(pl.col("measure") == "total_isk_traded_share_at_24h")
        self.assertEqual(
            zero["status"].to_list(), ["zero_total_isk_traded_denominator", "zero_total_isk_traded_denominator"]
        )
        reset = result.filter(
            (pl.col("view") == "as_observed_signed_effects") & (pl.col("measure") == "rows_share_at_24h")
        )
        self.assertIsNone(reset["share"].item())
        self.assertEqual(reset["status"].item(), "unresolved_reset_impact")


if __name__ == "__main__":
    unittest.main()
