"""GUI smoke tests. They need a display (run under `xvfb-run` on headless machines)."""

import os

import pytest

if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    pytest.skip("no display available", allow_module_level=True)

from PySide6.QtWidgets import QApplication  # noqa: E402

from threedn00b import project_io  # noqa: E402
from threedn00b.model import BOX, CYLINDER, FRONT, INSIDE  # noqa: E402


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from threedn00b.gui.viewer import prepare_opengl
    if QApplication.instance() is None:
        prepare_opengl()
    app = QApplication.instance() or QApplication([])
    from threedn00b.gui.main_window import MainWindow
    w = MainWindow()
    w.show()
    app.processEvents()
    yield w
    w.undo_stack.setClean()
    w.close()


def test_edit_undo_redo(window):
    window.width_spin.setValue(100)
    assert window.project.outer_width == 100
    window.width_spin.setValue(110)
    window.undo_stack.undo()          # consecutive width edits merge into one step
    assert window.project.width == 80
    window.undo_stack.redo()
    assert window.project.width == 110


def test_add_hole_and_lid(window):
    window.lid_check.setChecked(True)
    window.add_hole()
    window.rebuild()
    assert len(window.project.holes) == 1
    assert window.project.holes[0].surface == FRONT
    assert window.export_button.isEnabled()
    window.remove_selected_hole()
    assert window.project.holes == []
    window.undo_stack.undo()
    assert len(window.project.holes) == 1


def test_errors_block_export(window):
    window.wall_spin.setValue(10)
    window.width_spin.setValue(15)
    window.rebuild()
    assert not window.export_button.isEnabled()


def test_inside_mode_toggle_keeps_size(window):
    window.mode_inside.setChecked(True)
    assert window.project.size_mode == INSIDE
    assert window.project.outer_width == 80
    assert window.width_spin.value() == 76


def test_click_in_view_hits_the_box(window):
    window.rebuild()
    v = window.viewer
    hit = v.pick(v.width() / 2, v.height() * 0.6)
    assert hit is not None and hit[0] == "body"


def test_shape_switch_and_save_round_trip(window, tmp_path):
    window.shape_buttons[CYLINDER].click()
    window.rebuild()
    assert window.project.shape == CYLINDER
    window.path = tmp_path / "pot.3dn00b"
    assert window.save_project()
    assert project_io.load_project(window.path) == window.project
    window.shape_buttons[BOX].click()
    assert window.project.shape == BOX
