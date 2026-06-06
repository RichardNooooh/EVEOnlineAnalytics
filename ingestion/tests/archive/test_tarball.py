from __future__ import annotations

from pathlib import Path
import tarfile

import pytest

from eve_ingest.archives.tarball import ExtractedTarball, ExtractedTarMember


def make_tarball(path: Path, files: dict[str, str]) -> Path:
    staging = path.parent / "staging"
    staging.mkdir()
    for name, content in files.items():
        file_path = staging / name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)

    with tarfile.open(path, "w:bz2") as archive:
        for file_path in staging.rglob("*"):
            if file_path.is_file():
                archive.add(file_path, arcname=str(file_path.relative_to(staging)))

    return path


def _make_malicious_tarball(path: Path) -> Path:
    with tarfile.open(path, "w:bz2") as archive:
        ti = tarfile.TarInfo(name="../escape.json")
        ti.size = 0
        archive.addfile(ti)
    return path


class TestExtractsRegularFiles:
    def test_extracts_regular_files(self, tmp_path: Path) -> None:
        tarball = make_tarball(
            tmp_path / "test.tar.bz2",
            {"foo.txt": "hello", "bar.txt": "world"},
        )
        with ExtractedTarball(tarball) as archive:
            files = archive.list_files()
            assert len(files) == 2
            for member in files:
                assert member.path.exists()
            contents = {m.path.read_text() for m in files}
            assert contents == {"hello", "world"}


class TestReturnsMemberMetadata:
    def test_returns_member_metadata(self, tmp_path: Path) -> None:
        tarball = make_tarball(
            tmp_path / "test.tar.bz2",
            {"nested/example.json": '{"key": "value"}'},
        )
        with ExtractedTarball(tarball) as archive:
            member = archive.list_files()[0]
            assert isinstance(member, ExtractedTarMember)
            assert member.archive_name == "nested/example.json"
            assert member.filename == "example.json"
            assert member.relative_path == Path("nested/example.json")
            assert member.suffix == ".json"


class TestFiltersJsonFiles:
    def test_filters_json_files(self, tmp_path: Path) -> None:
        tarball = make_tarball(
            tmp_path / "test.tar.bz2",
            {"a.json": "1", "b.txt": "2", "nested/c.json": "3"},
        )
        with ExtractedTarball(tarball) as archive:
            json_files = list(archive.iter_json_files())
            names = {m.archive_name for m in json_files}
            assert names == {"a.json", "nested/c.json"}


class TestDeletesTempDirOnNormalExit:
    def test_deletes_temp_dir_on_normal_exit(self, tmp_path: Path) -> None:
        tarball = make_tarball(tmp_path / "test.tar.bz2", {"f.txt": "data"})
        with ExtractedTarball(tarball) as archive:
            root_path = archive.root
            assert root_path.exists()
        assert not root_path.exists()


class TestDeletesTempDirOnException:
    def test_deletes_temp_dir_on_exception(self, tmp_path: Path) -> None:
        tarball = make_tarball(tmp_path / "test.tar.bz2", {"f.txt": "data"})
        root_path = None
        try:
            with ExtractedTarball(tarball) as archive:
                root_path = archive.root
                raise ValueError("deliberate failure")
        except ValueError:
            pass
        assert root_path is not None
        assert not root_path.exists()


class TestRaisesOutsideLifecycle:
    def test_raises_outside_lifecycle(self, tmp_path: Path) -> None:
        tarball = make_tarball(tmp_path / "test.tar.bz2", {"f.txt": "data"})

        archive = ExtractedTarball(tarball)
        with pytest.raises(RuntimeError, match="Tarball is not open"):
            archive.list_files()
        with pytest.raises(RuntimeError, match="Tarball is not open"):
            list(archive.iter_files())
        with pytest.raises(RuntimeError, match="Tarball is not open"):
            list(archive.iter_json_files())
        with pytest.raises(RuntimeError, match="Tarball is not open"):
            _ = archive.root

        with ExtractedTarball(tarball) as archive2:
            pass
        with pytest.raises(RuntimeError, match="Tarball is not open"):
            archive2.list_files()
        with pytest.raises(RuntimeError, match="Tarball is not open"):
            list(archive2.iter_files())
        with pytest.raises(RuntimeError, match="Tarball is not open"):
            list(archive2.iter_json_files())
        with pytest.raises(RuntimeError, match="Tarball is not open"):
            _ = archive2.root


class TestRejectsPathTraversal:
    def test_rejects_path_traversal(self, tmp_path: Path) -> None:
        malicious = _make_malicious_tarball(tmp_path / "malicious.tar.bz2")
        with pytest.raises(tarfile.OutsideDestinationError):
            with ExtractedTarball(malicious):
                pass
        assert not (tmp_path / "escape.json").exists()


class TestSupportsTarBz2:
    def test_supports_tar_bz2(self, tmp_path: Path) -> None:
        tarball = make_tarball(
            tmp_path / "archive.tar.bz2",
            {"readme.txt": "bz2 content"},
        )
        with ExtractedTarball(tarball) as archive:
            assert len(archive.list_files()) == 1
            assert archive.list_files()[0].path.read_text() == "bz2 content"
