from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eve_ingest.raw_objects.ledger import RawObjectLedger


class RawFileReconciler:
    """Reconcile raw files on disk against ledger records.

    Supports finding orphaned files (on disk but not tracked by the ledger)
    and cleaning them up after a configurable retention window.
    """

    def __init__(self, raw_root: str | Path, ledger: RawObjectLedger) -> None:
        self._raw_root = Path(raw_root)
        self._ledger = ledger

    def list_files_on_disk(self) -> list[Path]:
        """Walk ``raw_root`` and return all regular files, skipping ``.tmp/``."""
        if not self._raw_root.is_dir():
            return []
        files: list[Path] = []
        for entry in self._raw_root.rglob("*"):
            if entry.is_file() and not self._is_temp_path(entry):
                files.append(entry)
        return sorted(files)

    def list_ledger_paths(self) -> set[str]:
        """Query all ``local_path`` values from the ledger."""
        with self._ledger.transaction() as tx:
            return set(tx.reader.list_all_version_paths())

    def find_orphans(
        self,
        older_than: timedelta | None = None,
    ) -> list[Path]:
        """Return files on disk not tracked in the ledger.

        Args:
            older_than: If set, only include files whose mtime is older
                than this duration.
        """
        ledger_paths = self.list_ledger_paths()
        now = datetime.now(UTC)
        orphans: list[Path] = []
        for disk_file in self.list_files_on_disk():
            if str(disk_file) in ledger_paths:
                continue
            if older_than is not None:
                mtime = datetime.fromtimestamp(disk_file.stat().st_mtime, tz=UTC)
                if now - mtime <= older_than:
                    continue
            orphans.append(disk_file)
        return orphans

    def delete_orphans(
        self,
        older_than: timedelta | None = None,
    ) -> int:
        """Delete orphaned files older than *older_than*.

        Returns:
            Number of files deleted.
        """
        count = 0
        for orphan in self.find_orphans(older_than=older_than):
            orphan.unlink()
            count += 1
        return count

    @staticmethod
    def _is_temp_path(path: Path) -> bool:
        return ".tmp" in path.parts
