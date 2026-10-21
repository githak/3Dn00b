"""GUI smoke tests. They need a display (run under `xvfb-run` on headless machines)."""

import os
import sys

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
    from threedn00b.gui.main_window import release_window
    release_window(w)


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


def test_add_hole_button_click(window):
    """Use the real button: clicked() passes an extra argument that once crashed the app."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    window.tabs.setCurrentIndex(1)
    QTest.mouseClick(window.add_hole_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.add_hole_button, Qt.MouseButton.LeftButton)
    window.rebuild()
    assert [h.surface for h in window.project.holes] == [FRONT, FRONT]
    window.undo_stack.undo()
    window.undo_stack.redo()
    assert len(window.project.holes) == 2


def test_double_click_wall_adds_hole(window):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    window.rebuild()
    v = window.viewer
    pos = QPoint(v.width() // 2, int(v.height() * 0.6))
    QTest.mouseDClick(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    assert len(window.project.holes) == 1
    assert window.project.holes[0].surface == FRONT


def test_every_button_click_is_safe(window):
    """Click each push button on the hole/lid tabs with a hole selected; nothing may raise."""
    import sys
    from PySide6.QtWidgets import QPushButton
    errors = []
    old_hook = sys.excepthook
    sys.excepthook = lambda *exc: errors.append(exc)
    try:
        window.add_hole()
        for tab in (1, 2):
            for button in window.tabs.widget(tab).findChildren(QPushButton):
                if button.isEnabled():
                    button.click()
                    window.rebuild()
    finally:
        sys.excepthook = old_hook
    assert errors == []


def _hole_pixel(window, hole):
    from threedn00b.model import hole_center_3d
    center, _ = hole_center_3d(window.project, hole)
    x, y = window.viewer.project_point(center)
    from PySide6.QtCore import QPoint
    return QPoint(round(x), round(y))


def _drag(widget, start, end, steps=8):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    for i in range(1, steps + 1):
        QTest.mouseMove(widget, QPoint(start.x() + (end.x() - start.x()) * i // steps,
                                       start.y() + (end.y() - start.y()) * i // steps))
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)


def test_drag_hole_along_wall_is_one_undo_step(window):
    from PySide6.QtCore import QPoint
    window.add_hole()
    window.rebuild()
    hole = window.project.holes[0]
    window.select_hole(None)
    camera = dict(window.viewer.opts)
    start = _hole_pixel(window, hole)
    steps_before = window.undo_stack.count()
    _drag(window.viewer, start, start + QPoint(-60, 25))
    moved = window.project.holes[0]
    assert window.selected_id == moved.id
    assert moved.u < -5 and moved.v < -2            # moved left and down on the front wall
    assert window.viewer.opts["azimuth"] == camera["azimuth"]   # the view did not turn
    assert window.undo_stack.count() == steps_before + 1
    window.undo_stack.undo()
    assert (window.project.holes[0].u, window.project.holes[0].v) == (hole.u, hole.v)


def test_drag_keeps_hole_on_the_wall(window):
    from PySide6.QtCore import QPoint
    window.add_hole()
    window.rebuild()
    start = _hole_pixel(window, window.project.holes[0])
    _drag(window.viewer, start, start + QPoint(-2000, 0))
    window.rebuild()
    assert not any(i.hole_id for i in window.issues if i.level != "info")


def test_drag_on_empty_space_turns_the_view(window):
    from PySide6.QtCore import QPoint
    window.rebuild()
    azimuth = window.viewer.opts["azimuth"]
    _drag(window.viewer, QPoint(30, 30), QPoint(130, 30))
    assert window.viewer.opts["azimuth"] != azimuth


def test_drag_on_round_wall_changes_angle(window):
    from PySide6.QtCore import QPoint
    window.shape_buttons[CYLINDER].click()
    window.add_hole()
    window.rebuild()
    window.viewer.reset_view(window.project)
    hole = window.project.holes[0]
    start = _hole_pixel(window, hole)
    _drag(window.viewer, start, start + QPoint(40, 0))
    assert window.project.holes[0].u > hole.u + 5      # moved round towards the right


def test_drag_hole_on_lid(window):
    from PySide6.QtCore import QPoint
    from threedn00b.model import LID, hole_center_3d
    window.lid_check.setChecked(True)
    window.add_hole(LID)
    window.rebuild()
    hole = window.project.holes[0]
    center, _ = hole_center_3d(window.project, hole)
    x, y = window.viewer.project_point((center[0], center[1], center[2] + window.viewer.lid_offset))
    start = QPoint(round(x), round(y))
    _drag(window.viewer, start, start + QPoint(50, 0))
    assert window.project.holes[0].surface == LID
    assert window.project.holes[0].u > 5


@pytest.mark.skipif(sys.version_info >= (3, 12), reason="None is immortal on Python 3.12+")
def test_long_drags_do_not_corrupt_reference_counts(window):
    """PySide6 6.12.0 dropped a reference to None on every OpenGL buffer upload.

    On Python 3.11 that crashed the app after a few minutes of dragging holes.
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication
    for u in (-20, 0, 20):
        window.add_hole(FRONT, u, 0)
    window.rebuild()
    QApplication.processEvents()
    before = sys.getrefcount(None)
    hole = window.project.holes[1]
    for i in range(10):
        start = _hole_pixel(window, window.project.hole(hole.id))
        _drag(window.viewer, start, start + QPoint(10 if i % 2 else -10, 8 if i % 2 else -8), steps=10)
        window.viewer.repaint()
        QApplication.processEvents()
    assert sys.getrefcount(None) - before > -50
