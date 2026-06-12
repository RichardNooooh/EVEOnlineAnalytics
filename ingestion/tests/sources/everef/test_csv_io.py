from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pyarrow as pa
from eve_ingest.sources.everef.csv_io import parse_csv_to_arrow
from tests.sources.everef.conftest import make_cache_result

if TYPE_CHECKING:
    import pathlib

    import pytest

_CSV_IO_LOGGER = logging.getLogger("eve_ingest.sources.everef.csv_io")


def _write_csv(path: pathlib.Path, rows: list[list[str]]) -> str:
    content = "\n".join(",".join(row) for row in rows) + "\n"
    path.write_text(content)
    return content


##############################
# parse_csv_to_arrow
##############################


class TestParseCsvToArrow:
    def test_parses_csv_to_table(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "data.csv"
        _write_csv(path, [["a", "b"], ["1", "10"], ["2", "20"]])
        result = make_cache_result(str(path), content_length=len(path.read_text()))
        table = parse_csv_to_arrow(result)
        assert isinstance(table, pa.Table)
        assert table.num_rows == 2
        assert table.column_names == ["a", "b"]
        assert table.column("a").to_pylist() == [1, 2]
        assert table.column("b").to_pylist() == [10, 20]

    def test_content_length_mismatch_logs_warning(
        self, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "data.csv"
        _write_csv(path, [["x"], ["1"]])
        result = make_cache_result(str(path), content_length=9999)
        _CSV_IO_LOGGER.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING, logger=_CSV_IO_LOGGER.name):
                parse_csv_to_arrow(result)
            assert "File size mismatch" in caplog.text
        finally:
            _CSV_IO_LOGGER.removeHandler(caplog.handler)

    def test_content_length_match_does_not_log_warning(
        self, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "data.csv"
        _write_csv(path, [["x"], ["1"]])
        result = make_cache_result(str(path), content_length=len(path.read_text()))
        _CSV_IO_LOGGER.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING, logger=_CSV_IO_LOGGER.name):
                parse_csv_to_arrow(result)
            assert "File size mismatch" not in caplog.text
        finally:
            _CSV_IO_LOGGER.removeHandler(caplog.handler)

    def test_none_content_length_skips_validation(
        self, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "data.csv"
        _write_csv(path, [["x"], ["1"]])
        result = make_cache_result(str(path), content_length=None)
        _CSV_IO_LOGGER.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING, logger=_CSV_IO_LOGGER.name):
                parse_csv_to_arrow(result)
            assert "File size mismatch" not in caplog.text
        finally:
            _CSV_IO_LOGGER.removeHandler(caplog.handler)

    def test_zero_row_csv_logs_warning(self, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
        path = tmp_path / "empty.csv"
        _write_csv(path, [["a", "b"]])
        result = make_cache_result(str(path), content_length=len(path.read_text()))
        _CSV_IO_LOGGER.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING, logger=_CSV_IO_LOGGER.name):
                table = parse_csv_to_arrow(result)
            assert table.num_rows == 0
            assert "Zero-row CSV file" in caplog.text
        finally:
            _CSV_IO_LOGGER.removeHandler(caplog.handler)

    def test_passes_read_options(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "data.csv"
        _write_csv(path, [["a", "b"], ["1", "10"], ["2", "20"]])
        result = make_cache_result(str(path), content_length=len(path.read_text()))
        table = parse_csv_to_arrow(result, read_options=pa.csv.ReadOptions(skip_rows=1))
        assert table.num_rows == 1

    def test_passes_parse_options(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "data.tsv"
        content = "a\tb\n1\t10\n2\t20\n"
        path.write_text(content)
        result = make_cache_result(str(path), content_length=len(content))
        table = parse_csv_to_arrow(
            result,
            parse_options=pa.csv.ParseOptions(delimiter="\t"),
        )
        assert table.num_rows == 2

    def test_passes_convert_options(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "data.csv"
        _write_csv(path, [["s"], ["hello"], ["world"]])
        result = make_cache_result(str(path), content_length=len(path.read_text()))
        table = parse_csv_to_arrow(
            result,
            convert_options=pa.csv.ConvertOptions(column_types={"s": pa.utf8()}),
        )
        assert table.column("s").to_pylist() == ["hello", "world"]

    def test_default_options_work_with_standard_csv(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "data.csv"
        _write_csv(path, [["a", "b", "c"], ["1", "hello", "3.5"], ["2", "world", "4.5"]])
        result = make_cache_result(str(path), content_length=len(path.read_text()))
        table = parse_csv_to_arrow(result)
        assert table.num_rows == 2

    def test_does_not_add_private_columns(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "market.csv"
        path.write_text("type_id,price\n1,10.0\n")
        result = make_cache_result(str(path), content_length=len(path.read_text()))
        table = parse_csv_to_arrow(result)
        assert "source_market_date" not in table.column_names
        assert "_source_market_date" not in table.column_names
        assert all(not c.startswith("_source") for c in table.column_names)


##############################
# _elapsed_seconds
##############################
