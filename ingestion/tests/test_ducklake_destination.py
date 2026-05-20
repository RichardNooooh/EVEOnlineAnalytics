from __future__ import annotations

import pytest

from ingest.publishers import ducklake as ducklake_pub


class FakeDuckLakeCredentials:
    def __init__(self, name: str, *, catalog: str, storage: str) -> None:
        self.name = name
        self.catalog = catalog
        self.storage = storage


def fake_ducklake_destination(
    credentials: FakeDuckLakeCredentials,
) -> dict[str, object]:
    return {"credentials": credentials}


def patch_ducklake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ducklake_pub, "DuckLakeCredentials", FakeDuckLakeCredentials)
    monkeypatch.setattr(ducklake_pub, "ducklake", fake_ducklake_destination)


def test_ducklake_destination_uses_local_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)

    destination_config = ducklake_pub.build_destination_config("ducklake")

    credentials = destination_config["credentials"]
    assert credentials.name == ducklake_pub.DEFAULT_DUCKLAKE_NAME
    assert credentials.catalog == ducklake_pub.local_ducklake_catalog()
    assert credentials.storage == ducklake_pub.local_ducklake_storage()
    assert credentials.catalog.startswith("sqlite:///")
    assert credentials.catalog.endswith(
        "/ingestion/.local/ducklake/everef_market_history/lake_catalog.sqlite"
    )
    assert credentials.storage.startswith("file://")
    assert credentials.storage.endswith(
        "/ingestion/.local/ducklake/everef_market_history/files"
    )


def test_ducklake_destination_creates_local_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    patch_ducklake(monkeypatch)
    monkeypatch.setattr(
        ducklake_pub, "local_ducklake_root", lambda: tmp_path / "ducklake"
    )

    destination_config = ducklake_pub.build_destination_config("ducklake")

    assert destination_config["credentials"].catalog.endswith("/lake_catalog.sqlite")
    assert (tmp_path / "ducklake").is_dir()
    assert (tmp_path / "ducklake/files").is_dir()


def test_ducklake_destination_uses_explicit_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    destination_config = ducklake_pub.build_destination_config(
        "ducklake",
        "arg_lake",
        "postgresql://arg/catalog",
        "file:///mnt/arg",
    )

    credentials = destination_config["credentials"]
    assert credentials.name == "arg_lake"
    assert credentials.catalog == "postgresql://arg/catalog"
    assert credentials.storage == "file:///mnt/arg"


def test_ducklake_destination_rejects_mounted_storage_with_default_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)

    with pytest.raises(
        ValueError,
        match="mounted DuckLake storage requires a non-local catalog.*PostgreSQL",
    ):
        ducklake_pub.build_destination_config(
            "ducklake",
            storage_target="mounted",
        )


def test_ducklake_destination_uses_mounted_storage_target_with_explicit_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)

    destination_config = ducklake_pub.build_destination_config(
        "ducklake",
        ducklake_catalog="postgresql://lake/catalog",
        storage_target="mounted",
    )

    credentials = destination_config["credentials"]
    assert credentials.catalog == "postgresql://lake/catalog"
    assert (
        credentials.storage
        == "file:///opt/eve-market/data/ducklake/everef/market_history"
    )


def test_ducklake_destination_rejects_explicit_mounted_storage_with_default_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)

    with pytest.raises(
        ValueError,
        match="mounted DuckLake storage requires a non-local catalog.*PostgreSQL",
    ):
        ducklake_pub.build_destination_config(
            "ducklake",
            ducklake_storage=ducklake_pub.mounted_ducklake_storage("/mnt/data"),
            data_root="/mnt/data",
        )


def test_ducklake_destination_allows_mounted_storage_with_postgres_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)
    mounted_storage = ducklake_pub.mounted_ducklake_storage("/mnt/data")

    destination_config = ducklake_pub.build_destination_config(
        "ducklake",
        ducklake_catalog="postgresql://lake/catalog",
        data_root="/mnt/data",
        ducklake_storage=mounted_storage,
    )

    credentials = destination_config["credentials"]
    assert credentials.catalog == "postgresql://lake/catalog"
    assert credentials.storage == mounted_storage


def test_ducklake_destination_uses_data_root_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)

    destination_config = ducklake_pub.build_destination_config(
        "ducklake",
        ducklake_catalog="postgresql://lake/catalog",
        storage_target="mounted",
        data_root="/mnt/arg-root",
    )

    credentials = destination_config["credentials"]
    assert credentials.storage == "file:///mnt/arg-root/ducklake/everef/market_history"


def test_ducklake_storage_override_skips_mounted_data_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_ducklake(monkeypatch)

    destination_config = ducklake_pub.build_destination_config(
        "ducklake",
        ducklake_catalog="postgresql://lake/catalog",
        ducklake_storage="file:///mnt/explicit",
        storage_target="mounted",
    )

    credentials = destination_config["credentials"]
    assert credentials.storage == "file:///mnt/explicit"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"ducklake_name": ""}, "ducklake_name must not be empty"),
        ({"ducklake_catalog": ""}, "ducklake_catalog must not be empty"),
        ({"ducklake_storage": ""}, "ducklake_storage must not be empty"),
        ({"storage_target": "mounted", "data_root": ""}, "data_root must not be empty"),
    ],
)
def test_ducklake_destination_rejects_empty_explicit_values(
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, str],
    message: str,
) -> None:
    patch_ducklake(monkeypatch)

    with pytest.raises(ValueError, match=message):
        ducklake_pub.build_destination_config("ducklake", **kwargs)
