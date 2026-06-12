from __future__ import annotations

from pathlib import Path


def test_static_contract_rejects_legacy_raw_source_objects_references() -> None:
    ingestion_root = Path(__file__).resolve().parents[1] / "eve_ingest"
    offenders = sorted(
        str(path.relative_to(ingestion_root.parent))
        for path in ingestion_root.rglob("*.py")
        if "raw_source_objects" in path.read_text()
    )

    assert offenders == []
