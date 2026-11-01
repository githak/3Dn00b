#!/usr/bin/env python3
"""Build an AppImage of 3Dn00b: one file that runs on most Linux systems.

    python3 packaging/build_appimage.py                # dist/3Dn00b-<version>-x86_64.AppImage
    python3 packaging/build_appimage.py --arch arm64   # dist/3Dn00b-<version>-aarch64.AppImage

Unlike the .deb and .rpm it carries its own Python too (a relocatable build from
python-build-standalone, fetched with uv), so it doesn't depend on the system's
Python version. It also carries the X11 helper libraries Qt needs that aren't on
every desktop (xcb-util, xkbcommon), taken from Ubuntu 22.04 (PC) or 24.04 (ARM).
Everything else it uses (OpenGL, fonts, X11, D-Bus) is on every Linux desktop.
The PC version needs glibc 2.34 or newer (Ubuntu 22.04, Debian 12, Fedora 35,
Linux Mint 21, openSUSE Leap 16 and newer); the ARM version glibc 2.39.

Needs: Python 3.11+, pip, readelf, Docker (for the helper libraries; an ARM build
on a PC also needs qemu-user-static), and internet access to PyPI and GitHub.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from bundle import (ROOT, TARGET_ALIASES, TARGETS, app_version, check_libraries,
                    fix_permissions, prepare_libraries, run, write_app_tree)

PYTHON = "3.12"
# Libraries Qt's X11 support needs that a desktop may not have (with what they need).
HELPER_LIBS = ("libxcb-cursor.so.0", "libxcb-icccm.so.4", "libxcb-image.so.0",
               "libxcb-keysyms.so.1", "libxcb-render-util.so.0", "libxcb-util.so.1",
               "libxkbcommon.so.0", "libxkbcommon-x11.so.0", "libxcb-xkb.so.1")
HELPER_PACKAGES = ("libxcb-cursor0", "libxcb-icccm4", "libxcb-image0", "libxcb-keysyms1",
                   "libxcb-render-util0", "libxcb-util1", "libxkbcommon0",
                   "libxkbcommon-x11-0", "libxcb-xkb1")
HELPER_IMAGE = {"x86_64": "ubuntu:22.04", "aarch64": "ubuntu:24.04"}
APPIMAGETOOL = ("https://github.com/AppImage/appimagetool/releases/download/continuous/"
                "appimagetool-x86_64.AppImage")
RUNTIME = "https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-{}"
# Parts of Python a desktop app doesn't need.
PYTHON_UNUSED = ("test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3",
                 "pydoc_data", "unittest/test")

APPRUN = """\
#!/bin/sh
# Start 3Dn00b with its own Python and libraries.
HERE="$(dirname "$(readlink -f "$0")")"
export LD_LIBRARY_PATH="$HERE/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
unset PYTHONHOME PYTHONPATH
exec "$HERE/usr/python/bin/python3" -I "$HERE/usr/lib/3dn00b/launch.py" "$@"
"""


def download(url: str, path: Path) -> Path:
    if not path.exists():
        run("curl", "-sSfL", "-o", path, url)
    return path


def portable_python(work: Path, machine: str) -> Path:
    """A relocatable CPython from python-build-standalone, as uv downloads it."""
    tools = work / "uv"
    run(sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
        "--target", tools, "uv")
    install = work / "python-install"
    env = dict(os.environ, UV_PYTHON_INSTALL_DIR=str(install))
    run(tools / "bin/uv", "python", "install", f"cpython-{PYTHON}-linux-{machine}-gnu", env=env)
    found = sorted(p for p in install.iterdir() if p.is_dir() and not p.is_symlink()
                   and p.name.startswith(f"cpython-{PYTHON}.") and machine in p.name)
    return found[-1]


def copy_python(source: Path, dest: Path) -> None:
    shutil.copytree(source, dest, symlinks=True)
    lib = dest / f"lib/python{PYTHON}"
    for name in PYTHON_UNUSED:
        target = lib / name
        if target.exists():
            shutil.rmtree(target)
    for path in [*lib.glob("config-*"), dest / "include", dest / "share"]:
        if path.exists():
            shutil.rmtree(path)
    for path in [*dest.glob("lib/libtcl*"), *dest.glob("lib/libtk*"), *dest.glob("lib/tcl*"),
                 *dest.glob("lib/tk*"), *dest.glob("lib/itcl*"), *dest.glob("lib/thread*"),
                 *lib.glob("lib-dynload/_tkinter*"), *lib.glob("lib-dynload/_crypt*")]:
        shutil.rmtree(path) if path.is_dir() else path.unlink()
    for cache in list(dest.rglob("__pycache__")):
        shutil.rmtree(cache)


def helper_libraries(dest: Path, machine: str) -> None:
    """Copy the helper libraries out of a clean Ubuntu container of the right kind."""
    dest.mkdir(parents=True, exist_ok=True)
    arch_dir = f"/usr/lib/{machine}-linux-gnu"
    proxy = os.environ.get("APT_PROXY", "")
    ca = os.environ.get("APT_CA", "")
    extra = ["--network", "host"] if proxy else []
    if ca:
        extra += ["-v", f"{Path(ca).resolve()}:/tmp/proxy-ca.crt:ro"]
    script = f"""
set -e
export DEBIAN_FRONTEND=noninteractive
if [ -n "$APT_PROXY" ]; then
    sed -i "s#http://#https://#g" /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true
    echo "Acquire::https::Proxy \\"$APT_PROXY\\";" > /etc/apt/apt.conf.d/01proxy
    [ -f /tmp/proxy-ca.crt ] && echo "Acquire::https::CAInfo \\"/tmp/proxy-ca.crt\\";" >> /etc/apt/apt.conf.d/01proxy
fi
apt-get update -qq >/dev/null
apt-get install -y -qq {" ".join(HELPER_PACKAGES)} >/dev/null
for lib in {" ".join(HELPER_LIBS)}; do cp -L {arch_dir}/$lib /out/; done
chown -R {os.getuid()}:{os.getgid()} /out
"""
    platform = "linux/arm64" if machine == "aarch64" else "linux/amd64"
    run("docker", "run", "--rm", "--platform", platform, *extra, "-e", f"APT_PROXY={proxy}",
        "-v", f"{dest.resolve()}:/out", HELPER_IMAGE[machine], "sh", "-ec", script)


def desktop_entry(appdir: Path, version: str) -> None:
    text = (ROOT / "data/3dn00b.desktop").read_text().rstrip() + f"\nX-AppImage-Version={version}\n"
    (appdir / "3dn00b.desktop").write_text(text)
    shutil.copy(ROOT / "threedn00b/resources/3dn00b.svg", appdir / "3dn00b.svg")
    os.symlink("3dn00b.svg", appdir / ".DirIcon")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--arch", default="x86_64", choices=sorted(TARGET_ALIASES))
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    target = TARGETS[TARGET_ALIASES[args.arch]]
    machine = target.machine
    work = ROOT / f"build/appimage-{machine}"
    cache = ROOT / "build/appimage-tools"
    cache.mkdir(parents=True, exist_ok=True)
    version = app_version()
    if work.exists():
        shutil.rmtree(work)
    appdir, vendor = work / "AppDir", work / "vendor"
    prepare_libraries(vendor, target, (PYTHON,))
    write_app_tree(appdir, vendor)
    (appdir / "usr/bin/3dn00b").unlink()                 # AppRun starts it instead
    copy_python(portable_python(work, machine), appdir / "usr/python")
    helper_libraries(appdir / "usr/lib", machine)
    (appdir / "AppRun").write_text(APPRUN)
    (appdir / "AppRun").chmod(0o755)
    desktop_entry(appdir, version)
    check_libraries(appdir, extra_dirs=(appdir / "usr/lib",))   # AppRun adds usr/lib
    fix_permissions(appdir)
    # Compile the Python files once: an AppImage can't store them when it runs.
    run(appdir / "usr/python/bin/python3", "-m", "compileall", "-q", "-j", "0",
        appdir / "usr/lib/3dn00b", appdir / "usr/python/lib", stdout=subprocess.DEVNULL)
    tool = download(APPIMAGETOOL, cache / "appimagetool-x86_64.AppImage")
    tool.chmod(0o755)
    runtime = download(RUNTIME.format(machine), cache / f"runtime-{machine}")
    args.out.mkdir(parents=True, exist_ok=True)
    image = args.out / f"3Dn00b-{version}-{machine}.AppImage"
    env = dict(os.environ, ARCH=machine, APPIMAGE_EXTRACT_AND_RUN="1")
    run(tool, "--no-appstream", "--runtime-file", runtime, appdir, image, env=env)
    print(f"\nBuilt {image} ({image.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
