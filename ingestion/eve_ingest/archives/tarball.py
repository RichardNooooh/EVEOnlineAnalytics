from __future__ import annotations

import logging
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExtractedTarMember:
    archive_name: str
    path: Path

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def relative_path(self) -> Path:
        return Path(self.archive_name)

    @property
    def suffix(self) -> str:
        return self.path.suffix


class ExtractedTarball:
    def __init__(self, tarball_path: str | Path) -> None:
        self.tarball_path = Path(tarball_path)
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None
        self._root: Path | None = None
        self._members: list[ExtractedTarMember] | None = None

    def __enter__(self) -> ExtractedTarball:
        self._tmpdir = tempfile.TemporaryDirectory(prefix=f"{self.tarball_path.stem}-")
        self._root = Path(self._tmpdir.name)

        try:
            logger.info(
                "Extracting tarball path=%s temp_root=%s",
                self.tarball_path,
                self.root,
            )

            with tarfile.open(self.tarball_path, mode="r:*") as archive:
                archive.extractall(self._root, filter="data")

            self._members = [
                ExtractedTarMember(
                    archive_name=str(path.relative_to(self._root)),
                    path=path,
                )
                for path in self._root.rglob("*")
                if path.is_file()
            ]

            logger.info(
                "Extracted tarball path=%s file_count=%d temp_root=%s",
                self.tarball_path,
                len(self._members),
                self.root,
            )
        except Exception:
            self._tmpdir.cleanup()
            self._tmpdir = None
            self._root = None
            self._members = None
            raise

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._tmpdir is not None:
            logger.debug(
                "Cleaning extracted tarball temp_root=%s",
                self._root,
            )
            self._tmpdir.cleanup()
        self._tmpdir = None
        self._root = None
        self._members = None

    @property
    def root(self) -> Path:
        if self._root is None:
            raise RuntimeError("Tarball is not open")
        return self._root

    def list_files(self) -> list[ExtractedTarMember]:
        if self._members is None:
            raise RuntimeError("Tarball is not open")
        return list(self._members)

    def iter_files(self) -> Iterator[ExtractedTarMember]:
        yield from self.list_files()

    def iter_json_files(self) -> Iterator[ExtractedTarMember]:
        for member in self.iter_files():
            if member.path.suffix == ".json":
                yield member
