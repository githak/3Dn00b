"""Find the slicers installed on this computer, and open exported files in one.

Slicers are found by their menu entries (.desktop files: packages, Flatpak, Snap, and
AppImages that have been added to the menu), then by their programs on the PATH, then
by AppImage files in the usual folders. Nothing is installed or downloaded.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Known:
    key: str
    name: str
    ids: tuple[str, ...]          # menu entry (.desktop file) names, lower case, without .desktop
    programs: tuple[str, ...]     # programs on the PATH
    appimage: str                 # how an AppImage file name starts, lower case


# The slicers beginners use most, in the order they are offered.
KNOWN = (
    Known("prusaslicer", "PrusaSlicer",
          ("prusaslicer", "prusa-slicer", "com.prusa3d.prusaslicer", "prusa3d-prusaslicer"),
          ("prusa-slicer", "PrusaSlicer"), "prusaslicer"),
    Known("orcaslicer", "OrcaSlicer",
          ("orcaslicer", "orca-slicer", "io.github.softfever.orcaslicer", "com.orcaslicer.orcaslicer"),
          ("orca-slicer", "OrcaSlicer"), "orcaslicer"),
    Known("bambustudio", "Bambu Studio",
          ("bambustudio", "bambu-studio", "com.bambulab.bambustudio", "bambu_studio"),
          ("bambu-studio", "BambuStudio", "bambu_studio"), "bambu_studio"),
    Known("cura", "UltiMaker Cura",
          ("cura", "ultimaker-cura", "com.ultimaker.cura", "ultimaker_cura", "cura_cura"),
          ("cura", "UltiMaker-Cura", "ultimaker-cura"), "ultimaker-cura"),
    Known("superslicer", "SuperSlicer",
          ("superslicer", "super-slicer", "com.superslicer.superslicer"),
          ("superslicer", "SuperSlicer"), "superslicer"),
    Known("crealityprint", "Creality Print",
          ("crealityprint", "creality-print", "io.github.crealityofficial.crealityprint"),
          ("CrealityPrint", "creality-print"), "crealityprint"),
)
FILE_CODES = {"%f", "%F", "%u", "%U"}             # where a menu entry wants the files
APPIMAGE_FOLDERS = ("Applications", "AppImages", "Downloads", ".local/bin")   # in the home folder
SYSTEM_MENU_DIRS = ("/var/lib/flatpak/exports/share", "/var/lib/snapd/desktop")


@dataclass(frozen=True)
class Slicer:
    key: str
    name: str
    command: tuple[str, ...]      # the program and its arguments; "%F" marks where files go

    def arguments(self, files: list[str | os.PathLike]) -> list[str]:
        """The full command line that opens these files."""
        names = [str(f) for f in files]
        args = []
        for part in self.command:
            if part == "%F":
                args += names
            else:
                args.append(part)
        if "%F" not in self.command:
            args += names
        return args


def _data_dirs() -> list[Path]:
    home = Path(os.environ.get("HOME", str(Path.home())))
    first = os.environ.get("XDG_DATA_HOME") or str(home / ".local/share")
    rest = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    dirs = [Path(first)] + [Path(d) for d in rest.split(":") if d]
    # Flatpak and Snap menu entries, in case the desktop session didn't add them.
    dirs += [home / ".local/share/flatpak/exports/share"] + [Path(d) for d in SYSTEM_MENU_DIRS]
    seen, out = set(), []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def read_desktop_entry(path: Path) -> dict[str, str]:
    """The [Desktop Entry] keys of a .desktop file (untranslated)."""
    entry, inside = {}, False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            inside = line == "[Desktop Entry]"
        elif inside and "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            entry.setdefault(key.strip(), value.strip())
    return entry


def exec_command(exec_line: str) -> tuple[str, ...] | None:
    """A menu entry's Exec line as a command, with "%F" where the files go.

    Field codes other than the file ones are dropped, as the desktop entry
    specification says; Flatpak's "@@ %F @@" markers stay around the files.
    """
    try:
        parts = shlex.split(exec_line.replace("%%", "\x00"))
    except ValueError:
        return None
    command, has_files = [], False
    for part in parts:
        part = part.replace("\x00", "%")
        if part in FILE_CODES:
            if not has_files:
                command.append("%F")
                has_files = True
        elif re.fullmatch(r"%[a-zA-Z]", part):
            continue
        else:
            command.append(part)
    return tuple(command) if command else None


def _runnable(program: str) -> bool:
    if os.sep in program:
        return os.path.isfile(program) and os.access(program, os.X_OK)
    return shutil.which(program) is not None


def _from_menu(known: Known) -> Slicer | None:
    for folder in _data_dirs():
        apps = folder / "applications"
        if not apps.is_dir():
            continue
        for path in sorted(apps.glob("*.desktop")):
            stem = path.name[:-len(".desktop")].lower()
            if stem not in known.ids:
                continue
            entry = read_desktop_entry(path)
            if entry.get("Type", "Application") != "Application" or entry.get("Hidden") == "true":
                continue
            command = exec_command(entry.get("Exec", ""))
            if command and _runnable(command[0]):
                return Slicer(known.key, known.name, command)
    return None


def _from_path(known: Known) -> Slicer | None:
    for program in known.programs:
        found = shutil.which(program)
        if found:
            return Slicer(known.key, known.name, (found, "%F"))
    return None


def _from_appimage(known: Known) -> Slicer | None:
    home = Path(os.environ.get("HOME", str(Path.home())))
    for name in APPIMAGE_FOLDERS:
        folder = home / name
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir(), reverse=True):        # newest version first
            low = path.name.lower()
            if (low.startswith(known.appimage) and low.endswith(".appimage")
                    and path.is_file() and os.access(path, os.X_OK)):
                return Slicer(known.key, known.name, (str(path), "%F"))
    return None


def find_slicers() -> list[Slicer]:
    """The known slicers installed here, in the order of KNOWN."""
    found = []
    for known in KNOWN:
        slicer = _from_menu(known) or _from_path(known) or _from_appimage(known)
        if slicer:
            found.append(slicer)
    return found


def clean_environment(env: dict[str, str]) -> dict[str, str]:
    """The environment for a slicer started from 3Dn00b: without the library paths
    3Dn00b's AppImage sets for itself, which would make another program load the wrong
    libraries."""
    env = dict(env)
    if "THREEDN00B_LD_LIBRARY_PATH" in env:          # set by the AppImage: what it was before
        before = env.pop("THREEDN00B_LD_LIBRARY_PATH")
        if before:
            env["LD_LIBRARY_PATH"] = before
        else:
            env.pop("LD_LIBRARY_PATH", None)
        return {k: v for k, v in env.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
    appdir = env.get("APPDIR")
    if appdir and "LD_LIBRARY_PATH" in env:
        kept = [p for p in env["LD_LIBRARY_PATH"].split(":") if p and not p.startswith(appdir)]
        if kept:
            env["LD_LIBRARY_PATH"] = ":".join(kept)
        else:
            del env["LD_LIBRARY_PATH"]
    for key in ("PYTHONHOME", "PYTHONPATH"):
        env.pop(key, None)
    return env


def launch(slicer: Slicer, files: list[str | os.PathLike]) -> bool:
    """Start the slicer with these files, on its own (it keeps running after 3Dn00b)."""
    import subprocess
    try:
        subprocess.Popen(slicer.arguments(files), env=clean_environment(dict(os.environ)),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    return True
