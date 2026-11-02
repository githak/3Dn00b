"""Finding installed slicers and opening exported files in them."""

import os
import time

import pytest

from threedn00b import slicers
from threedn00b.slicers import Slicer, clean_environment, exec_command


def test_exec_lines_become_commands():
    assert exec_command("prusa-slicer %F") == ("prusa-slicer", "%F")
    assert exec_command("cura %U %i --debug") == ("cura", "%F", "--debug")
    flatpak = ("/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=prusa-slicer "
               "--file-forwarding com.prusa3d.PrusaSlicer @@ %F @@")
    command = exec_command(flatpak)
    assert command[-3:] == ("@@", "%F", "@@") and command[0] == "/usr/bin/flatpak"
    assert exec_command('"/opt/My Slicer/slicer" --size=100%% %f') == (
        "/opt/My Slicer/slicer", "--size=100%", "%F")
    assert exec_command("") is None and exec_command('broken "quote') is None


def test_files_go_where_the_command_says():
    files = ["/tmp/a body.stl", "/tmp/lid.stl"]
    assert Slicer("x", "X", ("flatpak", "run", "@@", "%F", "@@")).arguments(files) == [
        "flatpak", "run", "@@", "/tmp/a body.stl", "/tmp/lid.stl", "@@"]
    assert Slicer("x", "X", ("slicer", "--single-instance")).arguments(files) == [
        "slicer", "--single-instance", "/tmp/a body.stl", "/tmp/lid.stl"]


def _program(path, script="#!/bin/sh\nexit 0\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script)
    path.chmod(0o755)
    return path


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home, bin_dir = tmp_path / "home", tmp_path / "bin"
    home.mkdir()
    bin_dir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local/share"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "system"))
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(slicers, "SYSTEM_MENU_DIRS", ())
    return tmp_path


def test_finds_slicers_from_menus_programs_and_appimages(fake_home):
    tmp = fake_home
    flatpak = _program(tmp / "bin/flatpak")
    apps = tmp / "system/applications"
    apps.mkdir(parents=True)
    (apps / "com.prusa3d.PrusaSlicer.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=PrusaSlicer\n"
        f"Exec={flatpak} run --file-forwarding com.prusa3d.PrusaSlicer @@ %F @@\n"
        "[Desktop Action New]\nExec=nothing\n")
    (apps / "bambu-studio.desktop").write_text(               # hidden: not offered
        "[Desktop Entry]\nType=Application\nHidden=true\nExec=bambu-studio %U\n")
    (apps / "superslicer.desktop").write_text(                # its program is gone
        "[Desktop Entry]\nType=Application\nExec=/nowhere/superslicer %F\n")
    _program(tmp / "bin/orca-slicer")
    cura = _program(tmp / "home/Applications/UltiMaker-Cura-5.10.0-linux-X64.AppImage")
    (tmp / "home/Downloads").mkdir()
    (tmp / "home/Downloads/OrcaSlicer_Linux_V2.3.0.AppImage").write_text("")   # not runnable
    found = slicers.find_slicers()
    assert [s.key for s in found] == ["prusaslicer", "orcaslicer", "cura"]
    prusa, orca, cura_found = found
    assert prusa.command == (str(flatpak), "run", "--file-forwarding", "com.prusa3d.PrusaSlicer",
                             "@@", "%F", "@@")
    assert orca.command == (str(tmp / "bin/orca-slicer"), "%F")
    assert cura_found.command == (str(cura), "%F") and cura_found.name == "UltiMaker Cura"


def test_nothing_found_on_a_bare_system(fake_home):
    assert slicers.find_slicers() == []


def test_slicers_dont_get_the_appimage_libraries():
    env = {"APPDIR": "/tmp/.mount_3Dn00b", "LD_LIBRARY_PATH": "/tmp/.mount_3Dn00b/usr/lib:/opt/lib",
           "PYTHONHOME": "/x", "HOME": "/home/me"}
    assert clean_environment(env) == {"APPDIR": "/tmp/.mount_3Dn00b", "LD_LIBRARY_PATH": "/opt/lib",
                                      "HOME": "/home/me"}
    env["LD_LIBRARY_PATH"] = "/tmp/.mount_3Dn00b/usr/lib"
    assert "LD_LIBRARY_PATH" not in clean_environment(env)
    assert clean_environment({"LD_LIBRARY_PATH": "/opt/lib"}) == {"LD_LIBRARY_PATH": "/opt/lib"}
    # The AppImage's launcher remembers the path as it was before it added its own.
    env = {"LD_LIBRARY_PATH": "/real/mount/usr/lib:/opt/lib", "THREEDN00B_LD_LIBRARY_PATH": "/opt/lib",
           "APPDIR": "/tmp/link-to-mount"}
    assert clean_environment(env) == {"LD_LIBRARY_PATH": "/opt/lib", "APPDIR": "/tmp/link-to-mount"}
    env["THREEDN00B_LD_LIBRARY_PATH"] = ""
    assert "LD_LIBRARY_PATH" not in clean_environment(env)


def test_launch_opens_the_files(tmp_path, monkeypatch):
    out = tmp_path / "out.txt"
    script = _program(tmp_path / "slicer", "#!/bin/sh\n"
                      f'printf "%s\\n" "$@" "lib=$LD_LIBRARY_PATH" > "{out}.tmp" && mv "{out}.tmp" "{out}"\n')
    monkeypatch.setenv("APPDIR", str(tmp_path / "app"))
    monkeypatch.setenv("LD_LIBRARY_PATH", f"{tmp_path}/app/usr/lib")
    files = [tmp_path / "my box-body.stl", tmp_path / "my box-lid.stl"]
    assert slicers.launch(Slicer("x", "X", (str(script), "%F")), files)
    for _ in range(100):
        if out.exists():
            break
        time.sleep(0.05)
    assert out.read_text().splitlines() == [str(f) for f in files] + ["lib="]
    assert not slicers.launch(Slicer("x", "X", (str(tmp_path / "missing"), "%F")), files)
