from __future__ import annotations

import pytest

from ingest.main import main


@pytest.mark.parametrize(
    ("argv", "expected_message"),
    [
        (
            [
                "everef",
                "market-history",
                "--start-date",
                "2025-01-01",
                "--end-date",
                "2025-01-31",
                "--raw-ledger-url",
                "",
            ],
            "raw_ledger_url must not be empty",
        ),
        (
            [
                "everef",
                "market-history",
                "--start-date",
                "2025-02-01",
                "--end-date",
                "2025-01-31",
            ],
            "start_date must be on or before end_date",
        ),
    ],
)
def test_main_surfaces_parser_and_validation_errors(
    monkeypatch,
    capsys,
    argv: list[str],
    expected_message: str,
) -> None:
    monkeypatch.setenv("INGEST_LOG_LEVEL", "CRITICAL")

    with pytest.raises(SystemExit) as exc_info:
        main(argv)

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert expected_message in captured.err
