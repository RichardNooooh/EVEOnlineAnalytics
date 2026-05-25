from __future__ import annotations

import pytest
import pyarrow as pa

from ingest.publishers.ducklake import (
    DEFAULT_DUCKLAKE_ALIAS,
    DuckLakeAttachConfig,
    DuckLakeTableTarget,
    attach_ducklake,
    build_ducklake_attach_path,
    write_arrow_table,
)


class FakeRelation:
    def __init__(self) -> None:
        self.view_names: list[str] = []

    def create_view(self, view_name: str) -> None:
        self.view_names.append(view_name)


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str] | None]] = []
        self.relation = FakeRelation()
        self.arrow_tables: list[pa.Table] = []

    def execute(self, query: str, params: list[str] | None = None) -> None:
        self.calls.append((query, params))

    def from_arrow(self, arrow_table: pa.Table) -> FakeRelation:
        self.arrow_tables.append(arrow_table)
        return self.relation


@pytest.mark.parametrize(
    ("catalog_url", "expected", "error_message"),
    [
        (
            "postgresql://airflow:airflow-local-only@127.0.0.1:5432/airflow",
            "ducklake:postgres:dbname=airflow host=127.0.0.1 port=5432 user=airflow password=airflow-local-only",
            None,
        ),
        ("sqlite:///tmp/catalog.db", None, "ducklake_catalog must be a PostgreSQL URL"),
    ],
)
def test_build_ducklake_attach_path(
    catalog_url: str,
    expected: str | None,
    error_message: str | None,
) -> None:
    if error_message is not None:
        with pytest.raises(ValueError, match=error_message):
            build_ducklake_attach_path(catalog_url)
        return

    assert build_ducklake_attach_path(catalog_url) == expected


def test_attach_ducklake_executes_expected_statements() -> None:
    con = FakeConnection()

    attach_ducklake(
        con,
        config=DuckLakeAttachConfig(
            attach_uri="ducklake:postgres:dbname=airflow host=127.0.0.1",
            data_path="/opt/eve-market/data/datasets/ducklake/raw/raw_market_history",
            metadata_schema="eve_market",
            alias="raw_lake",
        ),
    )

    assert con.calls[0] == ("INSTALL postgres", None)
    assert con.calls[1] == ("LOAD postgres", None)
    assert con.calls[2] == ("INSTALL ducklake", None)
    assert con.calls[3] == ("LOAD ducklake", None)
    assert 'ATTACH ? AS "raw_lake"' in con.calls[4][0]
    assert con.calls[4][1] == [
        "ducklake:postgres:dbname=airflow host=127.0.0.1",
        "/opt/eve-market/data/datasets/ducklake/raw/raw_market_history",
        "eve_market",
    ]


def test_write_arrow_table_appends_by_name(monkeypatch) -> None:
    con = FakeConnection()
    attached: dict[str, object] = {}
    arrow_table = pa.table({"b": [2], "a": [1]})

    def fake_attach_ducklake(connection, *, config) -> None:
        attached["connection"] = connection
        attached["config"] = config

    monkeypatch.setattr(
        "ingest.publishers.ducklake.attach_ducklake", fake_attach_ducklake
    )

    write_arrow_table(
        con,
        arrow_table=arrow_table,
        attach=DuckLakeAttachConfig(
            attach_uri="ducklake:postgres:dbname=airflow",
            data_path="/warehouse/raw/table",
        ),
        target=DuckLakeTableTarget(schema="raw", table="events"),
    )

    assert attached["connection"] is con
    assert con.arrow_tables == [arrow_table]
    assert len(con.relation.view_names) == 1
    assert 'INSERT INTO "ducklake"."raw"."events" BY NAME' in con.calls[0][0]
    assert "DROP VIEW IF EXISTS" in con.calls[1][0]


def test_write_arrow_table_merges_with_keys(monkeypatch) -> None:
    con = FakeConnection()
    arrow_table = pa.table({"id": [1, 2], "value": [10, 20]})

    monkeypatch.setattr(
        "ingest.publishers.ducklake.attach_ducklake",
        lambda connection, *, config: None,
    )

    write_arrow_table(
        con,
        arrow_table=arrow_table,
        attach=DuckLakeAttachConfig(
            attach_uri="ducklake:postgres:dbname=airflow",
            data_path="/warehouse/raw/table",
            alias=DEFAULT_DUCKLAKE_ALIAS,
        ),
        target=DuckLakeTableTarget(schema="raw", table="events"),
        merge_keys=["id"],
    )

    assert 'MERGE INTO "ducklake"."raw"."events" AS target' in con.calls[0][0]
    assert 'USING ("id")' in con.calls[0][0]
    assert "WHEN NOT MATCHED THEN INSERT BY NAME" in con.calls[0][0]


@pytest.mark.parametrize(
    ("attach", "target", "merge_keys", "arrow_table", "error_message"),
    [
        (
            DuckLakeAttachConfig(
                attach_uri="ducklake:postgres:dbname=airflow",
                data_path="/warehouse/raw/table",
                alias="raw lake",
            ),
            DuckLakeTableTarget(schema="raw", table="events"),
            [],
            pa.table({"id": [1], "value": [10]}),
            "SQL identifiers must be non-empty strings without spaces or dashes",
        ),
        (
            DuckLakeAttachConfig(
                attach_uri="ducklake:postgres:dbname=airflow",
                data_path="/warehouse/raw/table",
            ),
            DuckLakeTableTarget(schema="raw", table="market-events"),
            [],
            pa.table({"id": [1], "value": [10]}),
            "SQL identifiers must be non-empty strings without spaces or dashes",
        ),
        (
            DuckLakeAttachConfig(
                attach_uri="ducklake:postgres:dbname=airflow",
                data_path="/warehouse/raw/table",
            ),
            DuckLakeTableTarget(schema="raw", table="events"),
            ["item id"],
            pa.table({"id": [1], "value": [10]}),
            "SQL identifiers must be non-empty strings without spaces or dashes",
        ),
        (
            DuckLakeAttachConfig(
                attach_uri="ducklake:postgres:dbname=airflow",
                data_path="/warehouse/raw/table",
            ),
            DuckLakeTableTarget(schema="raw", table="events"),
            ["id"],
            pa.table({"value": [10]}),
            "merge_keys must exist in arrow_table columns",
        ),
    ],
)
def test_write_arrow_table_rejects_invalid_inputs(
    monkeypatch,
    attach: DuckLakeAttachConfig,
    target: DuckLakeTableTarget,
    merge_keys: list[str],
    arrow_table: pa.Table,
    error_message: str,
) -> None:
    con = FakeConnection()

    monkeypatch.setattr(
        "ingest.publishers.ducklake.attach_ducklake",
        lambda connection, *, config: None,
    )

    with pytest.raises(ValueError, match=error_message):
        write_arrow_table(
            con,
            arrow_table=arrow_table,
            attach=attach,
            target=target,
            merge_keys=merge_keys,
        )
