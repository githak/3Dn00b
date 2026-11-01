"""Files 3Dn00b keeps for the user: their own templates and automatic backups.

They live in ~/.local/share/3dn00b (or $XDG_DATA_HOME/3dn00b). Own templates are
ordinary project files, so they can be copied to another computer.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path

from . import project_io
from .model import Project

MY_TEMPLATE = "my:"      # a design's `template` when it was started from an own template


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "3dn00b"


def templates_dir() -> Path:
    return data_dir() / "templates"


def autosave_dir() -> Path:
    return data_dir() / "autosave"


@dataclass(frozen=True)
class MyTemplate:
    name: str
    path: Path
    shape: str


def my_templates() -> list[MyTemplate]:
    """The user's own templates, sorted by name (unreadable files are skipped)."""
    folder = templates_dir()
    found = []
    if folder.is_dir():
        for path in folder.glob("*" + project_io.PROJECT_SUFFIX):
            try:
                project = project_io.load_project(path)
            except project_io.ProjectFileError:
                continue
            found.append(MyTemplate(project.name.strip() or path.stem, path, project.shape))
    return sorted(found, key=lambda t: t.name.lower())


def find_template(name: str) -> MyTemplate | None:
    wanted = name.strip().lower()
    return next((t for t in my_templates() if t.name.lower() == wanted), None)


def save_template(project: Project, name: str) -> Path:
    """Save the design as an own template called `name` (replacing one with that name)."""
    name = name.strip()
    if not name:
        raise ValueError("A template needs a name.")
    existing = find_template(name)
    folder = templates_dir()
    if existing is not None:
        path = existing.path
    else:
        stem = project_io.safe_file_stem(name)
        path = folder / f"{stem}{project_io.PROJECT_SUFFIX}"
        number = 2
        while path.exists():
            path = folder / f"{stem}-{number}{project_io.PROJECT_SUFFIX}"
            number += 1
    saved = copy.deepcopy(project)
    saved.name, saved.template = name, ""
    folder.mkdir(parents=True, exist_ok=True)
    project_io.save_project(saved, path)
    return path


def load_template(template: MyTemplate) -> Project:
    """A new design from an own template (it remembers where it came from)."""
    project = project_io.load_project(template.path)
    project.template = MY_TEMPLATE + template.name
    return project


def rename_template(template: MyTemplate, new_name: str) -> Path:
    project = project_io.load_project(template.path)
    path = save_template(project, new_name)
    if path != template.path:
        template.path.unlink(missing_ok=True)
    return path


def remove_template(template: MyTemplate) -> None:
    template.path.unlink(missing_ok=True)
