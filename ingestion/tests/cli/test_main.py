from __future__ import annotations

import pytest

from ingest.main import main


@pytest.mark.parametrize(
    ("sub_command", "expected_message"),
    [
        ("market-history", "Everef market-history command is not implemented yet."),
        ("market-orders", "Everef market-orders command is not implemented yet."),
    ],
)
def test_valid_everef_command_raises_not_implemented(
    monkeypatch,
    capsys,
    sub_command: str,
    expected_message: str,
) -> None:
    monkeypatch.setenv("INGEST_LOG_LEVEL", "CRITICAL")

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "everef",
                sub_command,
                "--start-date",
                "2025-01-01",
                "--end-date",
                "2025-01-31",
            ]
        )

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert expected_message in captured.err


def test_main_surfaces_validation_error(monkeypatch, capsys) -> None:
    monkeypatch.setenv("INGEST_LOG_LEVEL", "CRITICAL")

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "everef",
                "market-history",
                "--start-date",
                "2025-02-01",
                "--end-date",
                "2025-01-31",
            ]
        )

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "start_date must be on or before end_date" in captured.err


def test_empty_esi_branch_errors_cleanly(monkeypatch, capsys) -> None:
    monkeypatch.setenv("INGEST_LOG_LEVEL", "CRITICAL")

    with pytest.raises(SystemExit) as exc_info:
        main(["esi"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "Provider 'esi' does not have any commands yet." in captured.err
