from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import duckdb

from transform.publish_curated_ducklake import Publication
from transform.publish_curated_ducklake import attach_curated_ducklake
from transform.publish_curated_ducklake import ensure_local_paths
from transform.publish_curated_ducklake import publish_dataset


class PublishCuratedDuckLakeTest(unittest.TestCase):
    def test_publish_dataset_copies_scratch_table_into_curated_ducklake(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            scratch_path = Path(temp_dir) / "scratch.duckdb"
            ducklake_root = Path(temp_dir) / "ducklake"
            catalog_path = ducklake_root / "lake_catalog.sqlite"

            con = duckdb.connect(str(scratch_path))
            con.execute(
                "create table main.mart_curated_daily_prices as "
                "select date '2025-01-01' as date, 10000002 as region_id, "
                "34 as type_id, 5.0 as vwap_price"
            )
            con.execute("install ducklake")
            con.execute("load ducklake")
            ensure_local_paths(
                f"ducklake:sqlite:{catalog_path}",
                str(ducklake_root),
            )
            attach_curated_ducklake(
                con,
                alias="curated_lake",
                attach_path=f"ducklake:sqlite:{catalog_path}",
                data_path=str(ducklake_root),
                metadata_schema="main",
                override_data_path=False,
            )

            publish_dataset(
                con,
                publication=Publication(
                    source_table="mart_curated_daily_prices",
                    target_table="curated_daily_prices",
                ),
                source_schema="main",
                target_alias="curated_lake",
                target_schema="curated",
            )

            rows = con.execute(
                "select date, region_id, type_id, vwap_price "
                "from curated_lake.curated.curated_daily_prices"
            ).fetchall()
            self.assertEqual(rows, [(dt.date(2025, 1, 1), 10000002, 34, 5.0)])
            self.assertTrue(catalog_path.exists())
            con.close()


if __name__ == "__main__":
    unittest.main()
