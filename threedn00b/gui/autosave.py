"""Automatic backups while you work, and getting your design back after a crash.

While a design has unsaved changes, a copy is written to the autosave folder
every few seconds. Closing 3Dn00b normally removes it, so a backup that is still
there at the next start means 3Dn00b (or the computer) stopped unexpectedly.

Each window locks its own backup, so a second 3Dn00b running at the same time
never offers the first one's backup for recovery.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QLockFile

from .. import project_io
from ..model import Project
from ..userdata import autosave_dir

SUFFIX = ".autosave"


def _lock_for(path: Path) -> QLockFile:
    lock = QLockFile(str(path.with_suffix(".lock")))
    lock.setStaleLockTime(0)        # only a lock whose program has gone is stale
    return lock


class Autosave:
    """The backup file of one window."""

    def __init__(self, folder: Path | None = None):
        self.folder = Path(folder) if folder is not None else autosave_dir()
        self.path = self.folder / f"{uuid.uuid4().hex[:12]}{SUFFIX}"
        self._lock = _lock_for(self.path)
        self._locked = False

    def write(self, project: Project, file: Path | None) -> bool:
        """Back up the design. Returns False if it couldn't be written."""
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            if not self._locked:
                self._locked = self._lock.tryLock(0)
            data = {"saved_at": time.time(), "file": str(file) if file else None,
                    "project": project_io.to_dict(project)}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(self.path)
            return True
        except OSError:
            return False

    def clear(self) -> None:
        """Remove the backup (the design is saved, or there's nothing to keep)."""
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass

    def close(self) -> None:
        self.clear()
        if self._locked:
            self._lock.unlock()
            self._locked = False


@dataclass
class Backup:
    """A backup left behind by a 3Dn00b that didn't close normally."""
    path: Path
    saved_at: float
    file: Path | None
    project: Project
    _lock: QLockFile

    def discard(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        self._lock.unlock()

    def keep(self) -> None:
        """Leave it for next time."""
        self._lock.unlock()


def leftover_backups(folder: Path | None = None) -> list[Backup]:
    """Backups no running 3Dn00b owns, newest first. They stay locked until
    discarded or kept, so no other window offers them at the same time."""
    folder = Path(folder) if folder is not None else autosave_dir()
    found = []
    if not folder.is_dir():
        return found
    for path in folder.glob("*" + SUFFIX):
        lock = _lock_for(path)
        if not lock.tryLock(0):
            continue                    # its window is still open
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            project = project_io.from_dict(data["project"])
            file = Path(data["file"]) if data.get("file") else None
            found.append(Backup(path, float(data.get("saved_at", 0.0)), file, project, lock))
        except (OSError, ValueError, KeyError, TypeError, project_io.ProjectFileError):
            lock.unlock()               # damaged, or from a newer version: leave it alone
    return sorted(found, key=lambda b: b.saved_at, reverse=True)
