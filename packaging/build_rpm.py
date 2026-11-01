#!/usr/bin/env python3
"""Build an .rpm package of 3Dn00b for Fedora, openSUSE Tumbleweed and other RPM systems.

    python3 packaging/build_rpm.py               # dist/3dn00b-<version>-1.x86_64.rpm
    python3 packaging/build_rpm.py --arch arm64  # dist/3dn00b-<version>-1.aarch64.rpm

Like the .deb, it carries its own copies of PySide6 and manifold3d (see bundle.py),
here for Python 3.12 to 3.14 (Fedora 40 to 43 and newer, openSUSE Tumbleweed).
The system libraries Qt needs are required by file name (libxcb-cursor.so.0 and
so on), so the package manager finds them whatever the distribution calls them.

Needs: Python 3.11+, pip, rpmbuild (Debian/Ubuntu: apt install rpm), readelf, and
internet access to download the libraries from PyPI.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from bundle import (ROOT, SYSTEM_LIBRARIES, TARGET_ALIASES, TARGETS, app_version,
                    check_libraries, fix_permissions, prepare_libraries, run, write_app_tree)

PYTHONS = ("3.12", "3.13", "3.14")
def spec(version: str, machine: str) -> str:
    requires = "\n".join(f"Requires: {lib}()(64bit)" for lib in SYSTEM_LIBRARIES)
    return f"""\
Name:           3dn00b
Version:        {version}
Release:        1
Summary:        Beginner-first designer for simple 3D-printable boxes
License:        GPL-3.0-or-later
URL:            https://github.com/githak/3Dn00b
BuildArch:      {machine}
AutoReqProv:    no
Requires:       python3 >= {PYTHONS[0]}
Requires:       python3 < 3.{int(PYTHONS[-1].split(".")[1]) + 1}
{requires}

# The files are ready-made (see build_rpm.py): no compiling, stripping or debug info.
%global debug_package %{{nil}}
%global __os_install_post %{{nil}}
%global _build_id_links none

%description
3Dn00b makes simple, useful objects for 3D printing without learning CAD:
boxes and round containers with holes, vents, compartments, screw posts for
circuit boards and several kinds of lids. It checks the design in plain
language and exports STL or 3MF files for your slicer.

%install
cp -a %{{_sourcedir}}/tree/. %{{buildroot}}/

%post
# Pre-compile the Python files for this computer's Python so 3Dn00b starts quickly.
py=$(python3 -c 'import sys; print("py%d.%d" % sys.version_info[:2])')
python3 -m compileall -q -j 0 /usr/lib/3dn00b/app /usr/lib/3dn00b/vendor/common \\
    "/usr/lib/3dn00b/vendor/$py" >/dev/null 2>&1 || :

%preun
if [ "$1" -eq 0 ]; then
    find /usr/lib/3dn00b -name __pycache__ -type d -prune -exec rm -rf {{}} + 2>/dev/null || :
fi

%files
/usr/bin/3dn00b
/usr/lib/3dn00b
/usr/share/applications/3dn00b.desktop
/usr/share/icons/hicolor/scalable/apps/3dn00b.svg
/usr/share/mime/packages/3dn00b.xml
/usr/share/3dn00b
%doc /usr/share/doc/3dn00b
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--arch", default="x86_64", choices=sorted(TARGET_ALIASES))
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    target = TARGETS[TARGET_ALIASES[args.arch]]
    work = ROOT / f"build/rpm-{target.machine}"
    version = app_version()
    if work.exists():
        shutil.rmtree(work)
    tree, vendor = work / "SOURCES/tree", work / "vendor"
    prepare_libraries(vendor, target, PYTHONS)
    write_app_tree(tree, vendor)
    check_libraries(tree)
    fix_permissions(tree)
    spec_file = work / "SPECS/3dn00b.spec"
    spec_file.parent.mkdir(parents=True)
    spec_file.write_text(spec(version, target.machine))
    run("rpmbuild", "-bb", "--target", target.machine,
        "--define", f"_topdir {work}", "--define", "_binary_payload w9.xzdio", spec_file)
    built = next((work / "RPMS" / target.machine).glob("*.rpm"))
    args.out.mkdir(parents=True, exist_ok=True)
    rpm = args.out / built.name
    shutil.copy(built, rpm)
    print(f"\nBuilt {rpm} ({rpm.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
