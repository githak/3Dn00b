"""What every 3Dn00b package carries, whatever the format (.deb, .rpm, AppImage).

The app needs PySide6 and manifold3d, which most Linux distributions don't package
(or not in the versions needed), so every package carries its own copies of the
libraries, downloaded from PyPI for each Python version it supports. Parts of Qt
the app never uses are left out to keep the download small. A small launcher
(packaging/debian/launch.py) picks the set that matches the Python it runs on.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent / "debian"


@dataclass(frozen=True)
class Target:
    """A processor family the packages are built for."""
    machine: str                     # as Python wheels and RPM call it: x86_64, aarch64
    deb: str                         # as Debian calls it: amd64, arm64
    pythons: tuple[str, ...]         # the Python versions to carry libraries for
    glibc: int                       # newest glibc 2.x the libraries may need

    @property
    def platforms(self) -> list[str]:
        """pip --platform tags for wheels that run on glibc 2.17 up to self.glibc."""
        tags = [f"manylinux2014_{self.machine}"]
        tags += [f"manylinux_2_{n}_{self.machine}" for n in range(17, self.glibc + 1)]
        return tags


TARGETS = {
    # Oldest supported: Ubuntu 22.04 (glibc 2.35, Python 3.10).
    "x86_64": Target("x86_64", "amd64", ("3.10", "3.11", "3.12", "3.13", "3.14"), 35),
    # PySide6's ARM wheels need glibc 2.39: Ubuntu 24.04 (Python 3.12), Debian 13 and
    # Raspberry Pi OS Trixie (Python 3.13) and newer.
    "aarch64": Target("aarch64", "arm64", ("3.12", "3.13", "3.14"), 39),
}
TARGET_ALIASES = {"amd64": "x86_64", "arm64": "aarch64", "x86_64": "x86_64", "aarch64": "aarch64"}

# What the app actually uses from PySide6 (found by tracing a running app).
QT_MODULES = ("QtCore", "QtGui", "QtWidgets", "QtOpenGL", "QtOpenGLWidgets", "QtSvg",
              "QtTest", "QtDBus")
QT_PLUGIN_DIRS = ("platforms", "xcbglintegrations", "platforminputcontexts",
                  "platformthemes", "imageformats", "iconengines",
                  "wayland-decoration-client", "wayland-graphics-integration-client",
                  "wayland-shell-integration")
# Plugins for setups a desktop app doesn't run in (remote VNC, bare framebuffer,
# kiosk shells); leaving them out avoids needing Qt Network/QML and Kerberos.
QT_PLUGINS_UNUSED = ("libqvnc.so", "libqeglfs.so", "libqlinuxfb.so", "libqvkkhrdisplay.so",
                     "libqminimalegl.so", "libivi-shell.so", "libqt-shell.so",
                     "libfullscreen-shell-v1.so")



def run(*cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def app_version() -> str:
    text = (ROOT / "threedn00b" / "__init__.py").read_text()
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def requirements() -> list[str]:
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    # The app is tested with PySide6 6.11; 6.12.0 has a crash bug (see app.py).
    deps = [d if not d.startswith("PySide6") else "PySide6-Essentials>=6.11,<6.12" for d in deps]
    # numpy 2.4 is the newest that also supports Python 3.11, so every Python shares
    # one copy of its maths libraries (2.5 would add a second, 6 MB bigger).
    return deps + ["numpy<2.5"]


def install_libraries(vendor: Path, target: Target, pythons: tuple[str, ...] | None = None) -> None:
    """pip-install the dependencies separately for every supported Python version."""
    platforms = [arg for p in target.platforms for arg in ("--platform", p)]
    for py in pythons or target.pythons:
        run(sys.executable, "-m", "pip", "install", "--quiet", "--no-compile",
            "--disable-pip-version-check", "--only-binary=:all:", "--implementation", "cp",
            "--python-version", py, *platforms, "--target", vendor / f"py{py}", *requirements())


def prepare_libraries(vendor: Path, target: Target, pythons: tuple[str, ...] | None = None) -> None:
    """Download, share between Python versions, and trim the bundled libraries."""
    pythons = pythons or target.pythons
    vendor.mkdir(parents=True)
    install_libraries(vendor, target, pythons)
    share_identical(vendor, pythons)
    pyside = vendor / "common/PySide6"
    if not pyside.exists():                      # one Python only: nothing was shared
        pyside = vendor / f"py{pythons[0]}/PySide6"
    trim_qt(pyside)
    slim_down(vendor)


def _tree_hash(path: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]:
        h.update(str(f.relative_to(path) if path.is_dir() else f.name).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def share_identical(vendor: Path, pythons: tuple[str, ...]) -> None:
    """Move packages that are the same for every Python version into vendor/common."""
    common = vendor / "common"
    common.mkdir()
    if len(pythons) < 2:
        return
    first = vendor / f"py{pythons[0]}"

    def same_everywhere(name: str) -> bool:
        copies = [vendor / f"py{py}" / name for py in pythons]
        return all(c.exists() for c in copies) and len({_tree_hash(c) for c in copies}) == 1

    shared = {e.name for e in first.iterdir() if same_everywhere(e.name)}
    # A package's compiled libraries (numpy.libs, ...) are found next to the package
    # ($ORIGIN/../numpy.libs), so they only move along with the package itself.
    shared = {name for name in shared
              if not name.endswith(".libs") or name[:-len(".libs")] in shared}
    for name in sorted(shared):
        shutil.move(str(first / name), common / name)
        for py in pythons[1:]:
            copy = vendor / f"py{py}" / name
            shutil.rmtree(copy) if copy.is_dir() else copy.unlink()


def slim_down(vendor: Path) -> None:
    """Drop test suites and examples, and store identical files only once (hard links)."""
    for pattern in ("*/numpy/**/tests", "*/pyqtgraph/examples"):
        for path in list(vendor.glob(pattern)):
            if path.is_dir():
                shutil.rmtree(path)
    seen: dict[str, Path] = {}
    for path in sorted(p for p in vendor.rglob("*") if p.is_file() and not p.is_symlink()):
        if path.stat().st_size < 64 * 1024:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in seen:
            path.unlink()
            os.link(seen[digest], path)
        else:
            seen[digest] = path


def _needed(lib: Path) -> list[str]:
    out = subprocess.run(["readelf", "-d", str(lib)], capture_output=True, text=True).stdout
    return re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", out)


def trim_qt(pyside: Path) -> None:
    """Remove the parts of Qt that 3Dn00b never uses (QML, Designer, tools, ...)."""
    qt = pyside / "Qt"
    for entry in pyside.iterdir():
        name = entry.name
        keep = (name in ("Qt", "support", "__init__.py", "_config.py", "_git_pyside_version.py")
                or name.startswith("libpyside6.")           # not libpyside6qml
                or any(name.startswith(m + ".") and not name.endswith(".pyi") for m in QT_MODULES))
        if not keep:
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    for entry in qt.iterdir():
        if entry.name not in ("lib", "plugins", "translations"):
            shutil.rmtree(entry)
    for entry in (qt / "plugins").iterdir():
        if entry.name not in QT_PLUGIN_DIRS:
            shutil.rmtree(entry)
    for entry in (qt / "translations").iterdir():
        if not entry.name.startswith("qtbase_"):
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    # Drop plugins that need Qt libraries PySide6-Essentials doesn't ship (e.g. Qt PDF,
    # the virtual keyboard): they could never load.
    libs = {p.name: p for p in (qt / "lib").iterdir()}
    for plugin in list((qt / "plugins").rglob("*.so")):
        if plugin.name in QT_PLUGINS_UNUSED or any(
                n.startswith("libQt6") and n not in libs for n in _needed(plugin)):
            plugin.unlink()
    # Keep only the Qt libraries that the kept modules and plugins need.
    todo = [p for p in pyside.glob("*.so*")] + list((qt / "plugins").rglob("*.so"))
    needed: set[str] = set()
    while todo:
        for name in _needed(todo.pop()):
            if name in libs and name not in needed:
                needed.add(name)
                todo.append(libs[name])
    for name, path in libs.items():
        if name not in needed and not path.is_dir():
            path.unlink()


# The system libraries the bundled Qt needs: everything its kept parts link to,
# except what the GTK theme plugin needs (it only loads on GTK desktops, which have it).
SYSTEM_LIBRARIES = (
    "libEGL.so.1", "libGL.so.1", "libfontconfig.so.1", "libfreetype.so.6", "libzstd.so.1",
    "libdbus-1.so.3", "libglib-2.0.so.0", "libgthread-2.0.so.0", "libX11.so.6", "libX11-xcb.so.1",
    "libxkbcommon.so.0", "libxkbcommon-x11.so.0", "libxcb.so.1", "libxcb-util.so.1",
    "libxcb-cursor.so.0", "libxcb-glx.so.0", "libxcb-icccm.so.4", "libxcb-image.so.0",
    "libxcb-keysyms.so.1", "libxcb-randr.so.0", "libxcb-render.so.0", "libxcb-render-util.so.0",
    "libxcb-shape.so.0", "libxcb-shm.so.0", "libxcb-sync.so.1", "libxcb-xfixes.so.0",
    "libxcb-xkb.so.1", "libwayland-client.so.0", "libwayland-cursor.so.0", "libwayland-egl.so.1",
    "libSM.so.6", "libICE.so.6",                 # Qt's X11 support on ARM links these too
)
# Part of every Linux system.
BASE_LIBRARIES = ("libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0", "librt.so.1",
                  "libutil.so.1", "libstdc++.so.6", "libgcc_s.so.1", "libz.so.1",
                  "ld-linux-x86-64.so.2", "ld-linux-aarch64.so.1")
GTK_PLUGIN_LIBRARIES = ("libgtk-3.so.0", "libgdk-3.so.0", "libpango-1.0.so.0",
                        "libpangocairo-1.0.so.0", "libcairo.so.2", "libcairo-gobject.so.2",
                        "libatk-1.0.so.0", "libharfbuzz.so.0", "libgio-2.0.so.0",
                        "libgobject-2.0.so.0", "libgdk_pixbuf-2.0.so.0")


def check_libraries(tree: Path, extra_dirs: tuple[Path, ...] = ()) -> None:
    """Make sure every bundled library finds the libraries it needs: inside the
    package where its search path (RUNPATH) points, or on the system. Stops the
    build with a list of what's missing."""
    known = set(SYSTEM_LIBRARIES) | set(BASE_LIBRARIES) | set(GTK_PLUGIN_LIBRARIES)
    problems = []
    for path in sorted(tree.rglob("*.so*")):
        if not path.is_file() or path.is_symlink() or path.read_bytes()[:4] != b"\x7fELF":
            continue
        out = subprocess.run(["readelf", "-d", str(path)], capture_output=True, text=True).stdout
        dirs = [Path(d.replace("$ORIGIN", str(path.parent))) for found in
                re.findall(r"\((?:RUNPATH|RPATH)\)\s+Library r(?:un)?path: \[([^\]]+)\]", out)
                for d in found.split(":")] + list(extra_dirs)
        for name in re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", out):
            if "/" in name:                          # a path, e.g. $ORIGIN/../lib/libx.so
                if not Path(name.replace("$ORIGIN", str(path.parent))).exists():
                    problems.append(f"{path.relative_to(tree)} needs {name}")
            elif name not in known and not any((d / name).exists() for d in dirs):
                problems.append(f"{path.relative_to(tree)} needs {name}")
    if problems:
        sys.exit("Bundled libraries that can't be found:\n  " + "\n  ".join(problems))
    print("All bundled libraries find what they need.")


def write_app_tree(pkg: Path, vendor: Path, prefix: str = "usr") -> Path:
    """The installed files: the app and its libraries under <prefix>/lib/3dn00b, the
    launcher, the menu entry, icon, file type, examples and docs. Returns the lib dir."""
    root = pkg / prefix
    lib = root / "lib/3dn00b"
    shutil.copytree(ROOT / "threedn00b", lib / "app/threedn00b",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.move(str(vendor), lib / "vendor")
    shutil.copy(HERE / "launch.py", lib / "launch.py")
    (root / "bin").mkdir(parents=True)
    shutil.copy(HERE / "3dn00b", root / "bin/3dn00b")
    (root / "bin/3dn00b").chmod(0o755)
    share = root / "share"
    (share / "applications").mkdir(parents=True)
    shutil.copy(ROOT / "data/3dn00b.desktop", share / "applications/3dn00b.desktop")
    (share / "icons/hicolor/scalable/apps").mkdir(parents=True)
    shutil.copy(ROOT / "threedn00b/resources/3dn00b.svg", share / "icons/hicolor/scalable/apps/3dn00b.svg")
    (share / "mime/packages").mkdir(parents=True)
    shutil.copy(HERE / "3dn00b-mime.xml", share / "mime/packages/3dn00b.xml")
    shutil.copytree(ROOT / "examples", share / "3dn00b/examples")
    doc = share / "doc/3dn00b"
    doc.mkdir(parents=True)
    shutil.copy(ROOT / "README.md", doc / "README.md")
    (doc / "copyright").write_text(COPYRIGHT)
    return lib


def fix_permissions(tree: Path) -> None:
    for path in tree.rglob("*"):                 # predictable permissions
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() or os.access(path, os.X_OK) else 0o644)


def changelog(version: str) -> bytes:
    date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    text = (f"3dn00b ({version}-1) unstable; urgency=medium\n\n"
            f"  * Release {version}. See the project page for what's new.\n\n"
            f" -- 3Dn00b <noreply@github.com>  {date}\n")
    return gzip.compress(text.encode(), mtime=0)


COPYRIGHT = """\
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: 3Dn00b
Source: https://github.com/githak/3Dn00b

Files: *
License: GPL-3.0-or-later
 On Debian systems the full text is in /usr/share/common-licenses/GPL-3.

Files: usr/lib/3dn00b/app/threedn00b/fonts/*
Copyright: 2003 Bitstream, Inc. (Bitstream Vera); DejaVu changes are in the public domain
License: Bitstream-Vera
 DejaVu Sans Bold, cut down to the letters of European languages. The full
 license text is in usr/lib/3dn00b/app/threedn00b/fonts/LICENSE.

Files: usr/lib/3dn00b/vendor/*
Comment: Libraries bundled because Debian does not package them (or not in the
 versions needed). Each keeps its own license file in its *.dist-info folder:
 PySide6 and shiboken6 (Qt for Python): LGPL-3.0; Qt: LGPL-3.0;
 numpy: BSD-3-Clause; manifold3d: Apache-2.0; pyqtgraph: MIT;
 PyOpenGL: BSD-3-Clause; colorama: BSD-3-Clause.
"""
