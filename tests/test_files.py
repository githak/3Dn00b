"""Own templates, automatic backups and measurements (no screen needed)."""

import json

import pytest

from threedn00b import measure, project_io, userdata
from threedn00b.model import (BOTTOM, BOX, CYLINDER, FRONT, LID, RIGHT, SIDE, Hole,
                              default_project)


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path / "data" / "3dn00b"


# ---- own templates -------------------------------------------------------

def test_save_and_list_own_templates(data_home):
    assert userdata.my_templates() == []
    p = default_project(BOX)
    p.width, p.template = 123.0, "pi"
    path = userdata.save_template(p, "  Screw box  ")
    assert path.parent == data_home / "templates" and path.name == "screw-box.3dn00b"
    userdata.save_template(default_project(CYLINDER), "Coffee jar")
    mine = userdata.my_templates()
    assert [t.name for t in mine] == ["Coffee jar", "Screw box"]
    assert [t.shape for t in mine] == [CYLINDER, BOX]
    started = userdata.load_template(mine[1])
    assert started.width == 123.0 and started.name == "Screw box"
    assert started.template == "my:Screw box"         # Box / Round then start over
    assert p.template == "pi" and p.name == "My box"   # the design itself is unchanged


def test_same_name_replaces_and_names_never_clash(data_home):
    first = userdata.save_template(default_project(BOX), "Box")
    again = userdata.save_template(default_project(CYLINDER), "box")
    assert again == first and len(userdata.my_templates()) == 1
    assert userdata.my_templates()[0].shape == CYLINDER
    other = userdata.save_template(default_project(BOX), "Box!")    # same file stem
    assert other != first and len(userdata.my_templates()) == 2
    with pytest.raises(ValueError):
        userdata.save_template(default_project(BOX), "   ")


def test_rename_and_remove_own_templates(data_home):
    userdata.save_template(default_project(BOX), "Old name")
    t = userdata.find_template("old NAME")
    userdata.rename_template(t, "New name")
    assert [x.name for x in userdata.my_templates()] == ["New name"]
    assert not t.path.exists()
    userdata.remove_template(userdata.find_template("New name"))
    assert userdata.my_templates() == []


def test_broken_template_files_are_skipped(data_home):
    userdata.save_template(default_project(BOX), "Good")
    (data_home / "templates" / "broken.3dn00b").write_text("{not json")
    assert [t.name for t in userdata.my_templates()] == ["Good"]


# ---- automatic backups ---------------------------------------------------

from threedn00b.gui.autosave import SUFFIX, Autosave, leftover_backups  # noqa: E402


def test_backup_of_an_open_window_is_not_offered(tmp_path):
    auto = Autosave(tmp_path)
    p = default_project(BOX)
    p.width = 99.0
    assert auto.write(p, None)
    assert auto.path.exists()
    assert leftover_backups(tmp_path) == []          # its window is still open
    auto.close()                                      # closed normally: nothing left
    assert list(tmp_path.glob("*" + SUFFIX)) == []
    assert leftover_backups(tmp_path) == []


def test_backup_left_by_a_crash_is_offered(tmp_path):
    p = default_project(CYLINDER)
    p.height = 77.0
    left = tmp_path / f"abc{SUFFIX}"                   # no lock: its program is gone
    left.write_text(json.dumps({"saved_at": 1000.0, "file": "/somewhere/jar.3dn00b",
                                "project": project_io.to_dict(p)}))
    newer = tmp_path / f"def{SUFFIX}"
    newer.write_text(json.dumps({"saved_at": 2000.0, "file": None,
                                 "project": project_io.to_dict(default_project(BOX))}))
    (tmp_path / f"bad{SUFFIX}").write_text("damaged")
    backups = leftover_backups(tmp_path)
    assert [b.path.name for b in backups] == [newer.name, left.name]     # newest first
    old = backups[1]
    assert old.project.height == 77.0 and str(old.file) == "/somewhere/jar.3dn00b"
    assert leftover_backups(tmp_path) == []          # locked while they're being offered
    backups[0].discard()
    backups[1].keep()
    assert not newer.exists() and left.exists()
    assert [b.path.name for b in leftover_backups(tmp_path)] == [left.name]
    assert (tmp_path / f"bad{SUFFIX}").exists()      # never thrown away unasked


def test_backup_survives_an_unwritable_folder(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    auto = Autosave(blocker / "autosave")             # a file is in the way
    assert auto.write(default_project(BOX), None) is False
    auto.close()


# ---- measurements in the 3D view -----------------------------------------

def test_size_measures_of_a_box_with_a_lid():
    p = default_project(BOX)
    p.lid.enabled = True
    width, depth, height = measure.size_measures(p)
    assert (width.text, depth.text) == ("80 mm", "60 mm")
    assert width.length == pytest.approx(80) and depth.length == pytest.approx(60)
    assert height.text == "40 mm (42 mm with the lid)" and height.length == pytest.approx(40)
    assert width.start[1] < -p.outer_depth / 2 and depth.start[0] > p.outer_width / 2   # outside
    assert len(width.marks) == 2


def test_size_measures_of_a_round_container():
    p = default_project(CYLINDER)
    p.width = 61.5            # boxes only: ignored
    diameter, height = measure.size_measures(p)
    assert diameter.text == "⌀ 60 mm" and height.text == "80 mm"


@pytest.mark.parametrize("surface, u, v, expected", [
    (FRONT, 10, -5, ["50 mm", "15 mm"]),        # from the left edge, and from the bottom
    (RIGHT, -12.5, 4, ["17.5 mm", "24 mm"]),
    (BOTTOM, 10, -5, ["50 mm", "25 mm"]),       # from the left, and from the front
    (LID, -30, 0, ["10 mm", "30 mm"]),
])
def test_hole_measures(surface, u, v, expected):
    p = default_project(BOX)
    p.lid.enabled = True
    found = measure.hole_measures(p, Hole(surface, 8, u, v))
    assert [m.text for m in found] == expected
    for m in found:                              # the lines are as long as they say
        assert m.length == pytest.approx(float(m.text.split()[0]))


def test_hole_measures_on_the_round_wall_and_at_the_edge():
    p = default_project(CYLINDER)
    (up,) = measure.hole_measures(p, Hole(SIDE, 8, 90, 5))
    assert up.text == "45 mm" and up.start[0] > p.outer_diameter / 2
    box = default_project(BOX)
    # A hole right at the left edge has nothing to measure across.
    assert [m.text for m in measure.hole_measures(box, Hole(FRONT, 8, -40, 0))] == ["20 mm"]


def test_mm_text():
    assert measure.mm(80) == "80 mm" and measure.mm(95.5) == "95.5 mm"
    assert measure.mm(12.04) == "12 mm"


def test_backup_whose_program_crashed_is_offered(tmp_path):
    """A lock left behind by a program that died doesn't keep its backup hidden."""
    import subprocess
    import sys
    from threedn00b.gui import autosave
    backup = tmp_path / f"crash{SUFFIX}"
    backup.write_text(json.dumps({"saved_at": 5.0, "file": None,
                                  "project": project_io.to_dict(default_project(BOX))}))
    lock = backup.with_suffix(".lock")
    code = ("import os, sys\n"
            "from PySide6.QtCore import QLockFile\n"
            "lock = QLockFile(sys.argv[1]); lock.setStaleLockTime(0)\n"
            "assert lock.tryLock(0)\n"
            "os._exit(0)\n")                                  # dies without unlocking
    subprocess.run([sys.executable, "-c", code, str(lock)], check=True, timeout=60)
    assert lock.exists()
    found = autosave.leftover_backups(tmp_path)
    assert [b.path for b in found] == [backup]
    found[0].keep()


def test_size_lines_go_along_the_sides_you_look_at():
    assert measure.facing_sides(-62) == (1, -1)       # the usual view: front and right
    assert measure.facing_sides(120) == (-1, 1)       # from behind on the left
    p = default_project(BOX)
    width, depth, height = measure.size_measures(p, (-1, 1))
    assert width.start[1] > p.outer_depth / 2          # along the back
    assert depth.start[0] < -p.outer_width / 2         # along the left side
    assert height.start[0] > p.outer_width / 2 and height.start[1] == pytest.approx(p.outer_depth / 2)
    assert all(m.length == pytest.approx(n.length)
               for m, n in zip(measure.size_measures(p), (width, depth, height)))
    c = default_project(CYLINDER)
    _, h = measure.size_measures(c, (1, 1))
    assert h.start[0] < 0 < h.start[1]                 # at the back left, beside the container
