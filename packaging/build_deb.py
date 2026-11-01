#!/usr/bin/env python3
"""Build a .deb package of 3Dn00b for Debian, Ubuntu, Linux Mint and friends.

    python3 packaging/build_deb.py            # writes dist/3dn00b_<version>-1_amd64.deb

Some of 3Dn00b's libraries (PySide6, manifold3d) are not packaged by Debian, so
the package carries its own copies, for every Python version those
distributions use (3.10 to 3.14). A small launcher picks the right set. Parts of
Qt the app never uses are left out to keep the download small.

Needs: Python 3.11+, pip, dpkg-deb and readelf (binutils), and internet access
to download the libraries from PyPI. Nothing is downloaded when users install.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent / "debian"
PYTHONS = ("3.10", "3.11", "3.12", "3.13", "3.14")
# Oldest glibc we support is 2.35 (Ubuntu 22.04; Debian 12 has 2.36).
PLATFORMS = ["manylinux2014_x86_64"] + [f"manylinux_2_{n}_x86_64"
                                        for n in (17, 24, 27, 28, 31, 34, 35)]

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

# System libraries Qt needs; apt installs them together with 3Dn00b.
DEPENDS = [
    "python3 (>= 3.10)", "python3 (<< 3.15)",
    "libegl1", "libgl1", "libopengl0", "libfontconfig1", "libfreetype6", "libdbus-1-3",
    "libglib2.0-0t64 | libglib2.0-0", "libx11-6", "libx11-xcb1", "libxkbcommon0",
    "libxkbcommon-x11-0", "libxcb1", "libxcb-cursor0", "libxcb-glx0", "libxcb-icccm4",
    "libxcb-image0", "libxcb-keysyms1", "libxcb-randr0", "libxcb-render0",
    "libxcb-render-util0", "libxcb-shape0", "libxcb-shm0", "libxcb-sync1", "libxcb-xfixes0",
    "libxcb-xkb1", "libwayland-client0", "libwayland-cursor0", "libwayland-egl1",
]


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


def install_libraries(vendor: Path) -> None:
    """pip-install the dependencies separately for every supported Python version."""
    platforms = [arg for p in PLATFORMS for arg in ("--platform", p)]
    for py in PYTHONS:
        run(sys.executable, "-m", "pip", "install", "--quiet", "--no-compile",
            "--disable-pip-version-check", "--only-binary=:all:", "--implementation", "cp",
            "--python-version", py, *platforms, "--target", vendor / f"py{py}", *requirements())


def _tree_hash(path: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]:
        h.update(str(f.relative_to(path) if path.is_dir() else f.name).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def share_identical(vendor: Path) -> None:
    """Move packages that are the same for every Python version into vendor/common."""
    common = vendor / "common"
    common.mkdir()
    first = vendor / f"py{PYTHONS[0]}"
    for entry in sorted(first.iterdir()):
        copies = [vendor / f"py{py}" / entry.name for py in PYTHONS]
        if all(c.exists() for c in copies) and len({_tree_hash(c) for c in copies}) == 1:
            shutil.move(str(entry), common / entry.name)
            for c in copies[1:]:
                shutil.rmtree(c) if c.is_dir() else c.unlink()


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


def write_tree(pkg: Path, version: str, vendor: Path) -> None:
    lib = pkg / "usr/lib/3dn00b"
    shutil.copytree(ROOT / "threedn00b", lib / "app/threedn00b",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.move(str(vendor), lib / "vendor")
    shutil.copy(HERE / "launch.py", lib / "launch.py")
    (pkg / "usr/bin").mkdir(parents=True)
    shutil.copy(HERE / "3dn00b", pkg / "usr/bin/3dn00b")
    (pkg / "usr/bin/3dn00b").chmod(0o755)
    share = pkg / "usr/share"
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
    date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    changelog = (f"3dn00b ({version}-1) unstable; urgency=medium\n\n"
                 f"  * Release {version}. See the project page for what's new.\n\n"
                 f" -- 3Dn00b <noreply@github.com>  {date}\n")
    (doc / "changelog.Debian.gz").write_bytes(gzip.compress(changelog.encode(), mtime=0))


def write_control(pkg: Path, version: str) -> None:
    debian = pkg / "DEBIAN"
    debian.mkdir()
    files = {f.stat().st_ino: f.stat().st_size for f in pkg.rglob("*") if f.is_file()}
    size_kb = sum(files.values()) // 1024            # hard-linked files count once
    (debian / "control").write_text(f"""\
Package: 3dn00b
Version: {version}-1
Architecture: amd64
Maintainer: 3Dn00b <noreply@github.com>
Installed-Size: {size_kb}
Depends: {", ".join(DEPENDS)}
Section: graphics
Priority: optional
Homepage: https://github.com/githak/3Dn00b
Description: beginner-first designer for simple 3D-printable boxes
 3Dn00b makes simple, useful objects for 3D printing without learning CAD:
 boxes and round containers with holes, vents, compartments, screw posts for
 circuit boards and several kinds of lids. It checks the design in plain
 language and exports STL or 3MF files for your slicer.
""")
    for script in ("postinst", "prerm"):
        shutil.copy(HERE / script, debian / script)
        (debian / script).chmod(0o755)


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    parser.add_argument("--work", type=Path, default=ROOT / "build/deb")
    args = parser.parse_args()
    version = app_version()
    if args.work.exists():
        shutil.rmtree(args.work)
    pkg, vendor = args.work / "pkg", args.work / "vendor"
    vendor.mkdir(parents=True)
    install_libraries(vendor)
    share_identical(vendor)
    trim_qt(vendor / "common/PySide6")
    slim_down(vendor)
    write_tree(pkg, version, vendor)
    write_control(pkg, version)
    for path in pkg.rglob("*"):                 # predictable permissions
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() or os.access(path, os.X_OK) else 0o644)
    args.out.mkdir(parents=True, exist_ok=True)
    deb = args.out / f"3dn00b_{version}-1_amd64.deb"
    run("dpkg-deb", "--root-owner-group", "-Zxz", "--build", pkg, deb)
    print(f"\nBuilt {deb} ({deb.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
