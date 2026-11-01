#!/usr/bin/env python3
"""Build a .deb package of 3Dn00b for Debian, Ubuntu, Linux Mint, Raspberry Pi OS and friends.

    python3 packaging/build_deb.py               # dist/3dn00b_<version>-1_amd64.deb
    python3 packaging/build_deb.py --arch arm64  # dist/3dn00b_<version>-1_arm64.deb

The package carries its own copies of PySide6 and manifold3d (see bundle.py) for
every Python version the distributions use. The amd64 package works on Ubuntu
22.04 and Debian 12 or newer; the arm64 package (Raspberry Pi 4 and 5, other ARM
computers) on Ubuntu 24.04, Debian 13 and Raspberry Pi OS Trixie or newer, because
Qt's ARM libraries need glibc 2.39.

Needs: Python 3.11+, pip, dpkg-deb and readelf (binutils), and internet access
to download the libraries from PyPI. Nothing is downloaded when users install.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from bundle import (HERE, ROOT, TARGET_ALIASES, TARGETS, app_version, changelog,
                    check_libraries, fix_permissions, prepare_libraries, run, write_app_tree)

# System libraries Qt needs; apt installs them together with 3Dn00b.
DEPENDS = [
    "libegl1", "libgl1", "libopengl0", "libfontconfig1", "libfreetype6", "libdbus-1-3",
    "libglib2.0-0t64 | libglib2.0-0", "libx11-6", "libx11-xcb1", "libxkbcommon0",
    "libxkbcommon-x11-0", "libxcb1", "libxcb-cursor0", "libxcb-glx0", "libxcb-icccm4",
    "libxcb-image0", "libxcb-keysyms1", "libxcb-randr0", "libxcb-render0",
    "libxcb-render-util0", "libxcb-shape0", "libxcb-shm0", "libxcb-sync1", "libxcb-xfixes0",
    "libxcb-xkb1", "libwayland-client0", "libwayland-cursor0", "libwayland-egl1",
    "libsm6", "libice6",
]


def write_control(pkg: Path, version: str, target) -> None:
    debian = pkg / "DEBIAN"
    debian.mkdir()
    files = {f.stat().st_ino: f.stat().st_size for f in pkg.rglob("*") if f.is_file()}
    size_kb = sum(files.values()) // 1024            # hard-linked files count once
    oldest, newest = target.pythons[0], target.pythons[-1]
    major, minor = newest.split(".")
    depends = [f"python3 (>= {oldest})", f"python3 (<< {major}.{int(minor) + 1})"] + DEPENDS
    (debian / "control").write_text(f"""\
Package: 3dn00b
Version: {version}-1
Architecture: {target.deb}
Maintainer: 3Dn00b <noreply@github.com>
Installed-Size: {size_kb}
Depends: {", ".join(depends)}
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--arch", default="amd64", choices=sorted(TARGET_ALIASES),
                        help="amd64 (most PCs) or arm64 (Raspberry Pi 4/5 and other ARM computers)")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    parser.add_argument("--work", type=Path, default=None)
    args = parser.parse_args()
    target = TARGETS[TARGET_ALIASES[args.arch]]
    work = args.work or ROOT / f"build/deb-{target.deb}"
    version = app_version()
    if work.exists():
        shutil.rmtree(work)
    pkg, vendor = work / "pkg", work / "vendor"
    prepare_libraries(vendor, target)
    write_app_tree(pkg, vendor)
    check_libraries(pkg)
    (pkg / "usr/share/doc/3dn00b/changelog.Debian.gz").write_bytes(changelog(version))
    write_control(pkg, version, target)
    fix_permissions(pkg)
    args.out.mkdir(parents=True, exist_ok=True)
    deb = args.out / f"3dn00b_{version}-1_{target.deb}.deb"
    run("dpkg-deb", "--root-owner-group", "-Zxz", "--build", pkg, deb)
    print(f"\nBuilt {deb} ({deb.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
