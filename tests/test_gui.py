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


def test_rectangular_hole_from_button_and_presets(window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from threedn00b.model import RECT
    QTest.mouseClick(window.add_rect_button, Qt.MouseButton.LeftButton)
    window.rebuild()
    hole = window.project.holes[0]
    assert hole.kind == RECT and (hole.width, hole.height) == (12, 6)
    assert window.hole_width.isVisible() and not window.hole_diameter.isVisible()
    usb_a = window.common_sizes.findText("USB-A plug (16 × 8.5 mm)")
    window.common_sizes.activated.emit(usb_a)
    assert (window.project.holes[0].width, window.project.holes[0].height) == (16, 8.5)
    window.hole_width.setValue(20)
    assert window.project.holes[0].width == 20
    assert "20 × 8.5 mm" in window.hole_list.item(0).text()
    assert not validation_errors(window)


def test_switching_hole_shape_keeps_it_valid(window):
    from threedn00b.model import RECT, ROUND
    window.add_hole()
    window.select_hole(window.project.holes[0].id)
    window.hole_v.setValue(window.hole_v.minimum())          # as low as a round hole can go
    window.kind_combo.setCurrentIndex(window.kind_combo.findData(RECT))
    window.kind_combo.activated.emit(window.kind_combo.currentIndex())
    assert window.project.holes[0].kind == RECT
    assert not validation_errors(window)
    window.undo_stack.undo()
    assert window.project.holes[0].kind == ROUND


def test_drag_rectangular_hole(window):
    from PySide6.QtCore import QPoint
    window.add_hole(kind="rect")
    window.rebuild()
    hole = window.project.holes[0]
    start = _hole_pixel(window, hole) + QPoint(15, 0)      # grab near its right end
    _drag(window.viewer, start, start + QPoint(-50, 0))
    assert window.project.holes[0].u < hole.u - 5


def validation_errors(window):
    window.rebuild()
    return [i.message for i in window.issues if i.level == "error"]


def test_air_vent_controls(window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.mouseClick(window.add_vent_button, Qt.MouseButton.LeftButton)
    window.rebuild()
    vent = window.project.holes[0]
    assert vent.kind == "vent" and vent.slot_count == 8
    assert window.vent_slot.isVisible() and not window.common_sizes.isVisible()
    assert "8 slots" in window.vent_info.text()
    window.vent_gap.setValue(3)
    assert window.project.holes[0].slot_count == 6
    window.vent_direction.setCurrentIndex(1)
    window.vent_direction.activated.emit(1)
    assert window.project.holes[0].slot_direction == "along_u"
    assert "print more cleanly" in window.vent_info.text()
    assert not validation_errors(window)
    window.undo_stack.undo()
    assert window.project.holes[0].slot_direction == "along_v"


def test_drag_air_vent(window):
    from PySide6.QtCore import QPoint
    window.add_hole(kind="vent")
    window.rebuild()
    vent = window.project.holes[0]
    start = _hole_pixel(window, vent) + QPoint(3, 0)    # grab between two slots
    _drag(window.viewer, start, start + QPoint(40, 0))
    assert window.project.holes[0].u > vent.u + 3


def test_compartment_controls(window):
    window.div_across.setValue(3)
    window.div_deep.setValue(2)
    window.rebuild()
    assert (window.project.dividers.across, window.project.dividers.deep) == (3, 2)
    assert "6 compartments" in window.divider_info.text()
    window.div_full.setChecked(False)
    assert window.project.dividers.height > 0 and window.div_height.isVisible()
    window.div_height.setValue(12)
    assert window.project.dividers.height == 12
    window.undo_stack.undo()
    window.undo_stack.undo()
    assert window.project.dividers.height == 0
    window.shape_buttons[CYLINDER].click()
    assert not window.divider_box.isVisible()
    assert not validation_errors(window)


def test_new_tray_from_menu(window):
    new_button = [a for a in window.findChildren(type(window.export_action)) if a.text() == "New"][0]
    tray = [a for a in new_button.menu().actions() if "tray" in a.text()][0]
    tray.trigger()
    window.rebuild()
    assert window.project.name == "My tray"
    assert window.project.dividers.across == 3
    assert not validation_errors(window)
    new_button.trigger()                      # plain New = a box
    assert window.project.name == "My box"


def test_screw_post_controls(window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    window.width_spin.setValue(110)
    window.depth_spin.setValue(80)
    window.board_combo.setCurrentIndex(window.board_combo.findData("rpi-zero"))
    QTest.mouseClick(window.add_posts_button, Qt.MouseButton.LeftButton)
    window.rebuild()
    m = window.project.mounts[0]
    assert m.board == "rpi-zero" and m.screw == "M2.5"
    assert "up to 7 mm" in window.mount_info.text()
    window.post_length.setValue(10)
    assert "up to 11 mm" in window.mount_info.text()
    window.screw_combo.setCurrentIndex(window.screw_combo.findData("M3"))
    window.screw_combo.activated.emit(window.screw_combo.currentIndex())
    assert window.project.mounts[0].screw == "M3"
    assert "usually fixed with M2.5" in window.mount_info.text()
    turn = [b for b in window.mount_box.findChildren(type(window.add_posts_button))
            if b.text() == "Turn 90°"][0]
    turn.click()
    assert window.project.mounts[0].rotation == 90
    assert not validation_errors(window)
    window.undo_stack.undo()
    assert window.project.mounts[0].rotation == 0


def test_drag_board_moves_all_posts_together(window):
    from PySide6.QtCore import QPoint
    window.width_spin.setValue(150)
    window.depth_spin.setValue(100)
    window.add_mount("rpi-zero")
    window.rebuild()
    window.viewer.setCameraPosition(elevation=70)
    m = window.project.mounts[0]
    before = mounts_positions(m)
    x, y = window.viewer.project_point((m.u, m.v, window.project.bottom + m.length))
    start = QPoint(round(x), round(y))
    _drag(window.viewer, start, start + QPoint(60, 0))
    moved = window.project.mounts[0]
    after = mounts_positions(moved)
    assert moved.u != m.u or moved.v != m.v
    shift = (after[0][0] - before[0][0], after[0][1] - before[0][1])
    assert all(a == pytest.approx((b[0] + shift[0], b[1] + shift[1])) for a, b in zip(after, before))
    window.undo_stack.undo()
    assert (window.project.mounts[0].u, window.project.mounts[0].v) == (m.u, m.v)


def test_fix_button_moves_board_inside(window):
    window.width_spin.setValue(110)
    window.depth_spin.setValue(80)
    window.add_mount("rpi-ab")
    window._edit_mount("Move posts", "u", 15.0)
    window.rebuild()
    window.tabs.setCurrentIndex(4)
    row = next(i for i, issue in enumerate(window.issues) if issue.mount_id)
    window.issue_list.setCurrentRow(row)
    assert window.fix_button.isVisibleTo(window)
    window.fix_button.click()
    assert not validation_errors(window)


def mounts_positions(m):
    from threedn00b import mounts
    return mounts.post_positions(m)


def test_parts_on_top_field(window):
    window.width_spin.setValue(110)
    window.depth_spin.setValue(100)
    window.add_mount("rpi-zero")
    assert window.parts_height.value() == 4.0 and "5 mm of room" in window.mount_info.text()
    window.parts_height.setValue(8.5)
    assert window.project.mounts[0].parts_height == 8.5
    assert "9.5 mm of room" in window.mount_info.text()
    window.add_mount("single")
    assert not window.parts_height.isVisibleTo(window)


def test_lid_type_controls(window):
    window.lid_check.setChecked(True)
    form = window.lid_form
    assert form.isRowVisible(window.fit_combo) and not form.isRowVisible(window.lid_screw)
    window.lid_style.setCurrentIndex(window.lid_style.findData("screwed"))
    window.lid_style.activated.emit(window.lid_style.currentIndex())
    assert window.project.lid.style == "screwed"
    assert form.isRowVisible(window.lid_screw) and not form.isRowVisible(window.fit_combo)
    window.lid_screw.setCurrentIndex(window.lid_screw.findData("M4"))
    window.lid_screw.activated.emit(window.lid_screw.currentIndex())
    assert window.project.lid.screw == "M4"
    assert not validation_errors(window)
    window.undo_stack.undo()
    window.undo_stack.undo()
    assert window.project.lid.style == "push"


def test_snap_and_sliding_lid_controls(window):
    window.lid_check.setChecked(True)
    form = window.lid_form
    for style, lip in (("snap", True), ("sliding", False)):
        window.lid_style.setCurrentIndex(window.lid_style.findData(style))
        window.lid_style.activated.emit(window.lid_style.currentIndex())
        assert window.project.lid.style == style
        assert form.isRowVisible(window.fit_combo) and form.isRowVisible(window.lip_height) == lip
        assert not validation_errors(window)


def test_threaded_lid_controls(window):
    window.shape_buttons[CYLINDER].click()
    window.lid_check.setChecked(True)
    window.lid_style.setCurrentIndex(window.lid_style.findData("threaded"))
    window.lid_style.activated.emit(window.lid_style.currentIndex())
    assert window.project.lid.style == "threaded"
    form = window.lid_form
    assert form.isRowVisible(window.fit_combo) and not form.isRowVisible(window.lip_height)
    assert "jar" in window.lid_style_hint.text()
    assert not validation_errors(window)
    window.shape_buttons[BOX].click()
    assert any("round containers" in m for m in validation_errors(window))


def test_export_3mf_from_the_window(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from threedn00b import project_io as io
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path)))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    window.lid_check.setChecked(True)
    window.rebuild()
    window.format_combo.setCurrentIndex(window.format_combo.findData("3mf"))
    assert "3MF" in window.export_button.text()
    assert window.settings.value("export_format") == "3mf"
    window.export_button.click()
    assert [q["name"] for q in io.read_3mf(tmp_path / "my-box.3mf")] == ["My box body", "My box lid"]
    window.format_combo.setCurrentIndex(window.format_combo.findData("stl"))
    window.export_button.click()
    assert (tmp_path / "my-box-body.stl").exists() and (tmp_path / "my-box-lid.stl").exists()
