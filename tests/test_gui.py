"""GUI smoke tests. They need a display (run under `xvfb-run` on headless machines)."""

import os
import sys

import pytest

if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    pytest.skip("no display available", allow_module_level=True)

from PySide6.QtWidgets import QApplication  # noqa: E402

from threedn00b import project_io  # noqa: E402
from threedn00b.model import BOX, CYLINDER, FRONT, INSIDE  # noqa: E402
from threedn00b.gui.main_window import TAB_CHECK, TAB_TEXT  # noqa: E402


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))      # templates, backups
    from threedn00b.gui.viewer import prepare_opengl
    if QApplication.instance() is None:
        prepare_opengl()
    app = QApplication.instance() or QApplication([])
    from PySide6.QtCore import QSettings
    from threedn00b.gui.main_window import APP_NAME, MainWindow
    QSettings(APP_NAME, APP_NAME).clear()     # Qt keeps the settings file of the first test
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
    window.tabs.setCurrentIndex(TAB_CHECK)
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


def test_smoke_test_option():
    """The check the Debian package tests run after installing."""
    import subprocess
    result = subprocess.run([sys.executable, "-m", "threedn00b", "--smoke-test"],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert "smoke test: OK" in result.stdout


def test_custom_board_fields_follow_the_board(window):
    window.width_spin.setValue(100)
    window.depth_spin.setValue(70)
    form = window.mount_form
    window.add_mount("custom2")
    assert form.isRowVisible(window.spacing_x)
    assert form.labelForField(window.spacing_x).text() == "Holes apart (width)"
    window.spacing_y.setValue(-8)                        # negative allowed: other diagonal
    assert window.project.mounts[0].spacing_y == -8
    window.add_mount("custom1")
    assert form.labelForField(window.spacing_x).text() == "Hole from middle (width)"
    window.add_mount("rpi-zero")
    assert not form.isRowVisible(window.spacing_x)
    # All three were added in the middle, so the only problems are the overlaps.
    assert all("overlap" in m for m in validation_errors(window))


def test_about_box(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()))
    assert window.about_action.text() == "About"
    window.about_action.trigger()
    assert len(shown) == 1
    text = shown[0]
    assert "3Dn00b" in text and "beginners" in text
    assert text.endswith("<p><br>Vibe-coded by TheSpork, 2026</p>")   # last, after a blank line


def test_inside_corner_controls(window):
    form = window.shape_form
    assert not form.isRowVisible(window.inside_corner_size)          # sharp: no size
    window.inside_corners.setCurrentIndex(window.inside_corners.findData("angled"))
    window.inside_corners.activated.emit(window.inside_corners.currentIndex())
    assert window.project.inside_corners == "angled" and form.isRowVisible(window.inside_corner_size)
    window.inside_corner_size.setValue(4)
    assert window.project.inside_corner_size == 4
    assert not validation_errors(window)
    window.undo_stack.undo()
    window.undo_stack.undo()
    assert window.project.inside_corners == "sharp"


def test_hole_rounding_and_frame_controls(window):
    from threedn00b.model import BOTTOM, RECT
    window.add_hole(kind=RECT)
    hole = window.project.holes[0]
    assert hole.rounding == 1.0 and hole.strengthen        # new rectangles: both on
    form = window.hole_form
    assert form.isRowVisible(window.hole_rounding) and form.isRowVisible(window.hole_strengthen)
    window.common_sizes.activated.emit(window.common_sizes.findText("USB-C plug (12.5 × 7 mm)"))
    hole = window.project.holes[0]
    assert (hole.width, hole.height, hole.rounding) == (12.5, 7.0, 3.0)
    window.hole_strengthen.setChecked(False)
    assert not window.project.holes[0].strengthen
    window.undo_stack.undo()
    assert window.project.holes[0].strengthen
    window.hole_rounding.setValue(0)
    assert window.project.holes[0].rounding == 0
    assert not validation_errors(window)
    window.surface_combo.setCurrentIndex(window.surface_combo.findData(BOTTOM))
    window.surface_combo.activated.emit(window.surface_combo.currentIndex())
    assert not form.isRowVisible(window.hole_strengthen)    # frames are for walls only
    window.add_hole()
    assert not form.isRowVisible(window.hole_rounding)      # round holes have no corners


def test_compartment_size_controls(window):
    window.div_across.setValue(3)
    sizes = window.width_sizes
    assert sizes.box.isVisible() and not sizes.form.isRowVisible(sizes.spins[0])
    sizes.custom.setChecked(True)
    d = window.project.dividers
    assert len(d.widths) == 2 and sizes.form.isRowVisible(sizes.spins[1])
    assert not sizes.form.isRowVisible(sizes.spins[2])
    sizes.spins[0].setValue(20)
    assert window.project.dividers.widths[0] == 20
    assert "the rest" in sizes.rest.text()
    window.div_across.setValue(4)                     # keeps the first sizes, adds one
    assert window.project.dividers.widths[:2] == [20, window.project.dividers.widths[1]]
    assert len(window.project.dividers.widths) == 3 and sizes.form.isRowVisible(sizes.spins[2])
    assert "Widths from the left: 20 +" in window.divider_info.text()
    assert not validation_errors(window)
    sizes.custom.setChecked(False)
    assert window.project.dividers.widths == []
    window.undo_stack.undo()
    assert len(window.project.dividers.widths) == 3
    window.div_deep.setValue(1)
    assert not window.depth_sizes.box.isVisible()     # one row: nothing to size


def test_easy_opening_control(window):
    window.lid_check.setChecked(True)
    form = window.lid_form
    assert form.isRowVisible(window.lid_opening)
    window.lid_opening.setCurrentIndex(window.lid_opening.findData("tab"))
    window.lid_opening.activated.emit(window.lid_opening.currentIndex())
    assert window.project.lid.opening == "tab"
    assert not validation_errors(window)
    window.lid_style.setCurrentIndex(window.lid_style.findData("screwed"))
    window.lid_style.activated.emit(window.lid_style.currentIndex())
    assert not form.isRowVisible(window.lid_opening)     # only for lids with a lip


def test_start_from_template(window):
    combo = window.template_combo
    combo.activated.emit(combo.findData("pi"))
    window.rebuild()
    p = window.project
    assert p.name == "Raspberry Pi case" and p.mounts and p.holes and p.lid.enabled
    assert combo.currentIndex() == 0                  # ready to pick again
    assert not validation_errors(window)
    window.undo_stack.undo()
    assert window.project.name == "My box" and not window.project.mounts


def test_template_headings_cannot_be_picked(window):
    combo = window.template_combo
    headings = [i for i in range(combo.count()) if combo.itemData(i) is None][1:]
    assert len(headings) == 3
    assert all(not combo.model().item(i).isEnabled() for i in headings)


def test_lid_side_controls(window):
    window.lid_check.setChecked(True)
    form = window.lid_form
    assert not form.isRowVisible(window.opening_side)        # nothing to place yet
    window.lid_opening.setCurrentIndex(window.lid_opening.findData("tab"))
    window.lid_opening.activated.emit(window.lid_opening.currentIndex())
    assert form.isRowVisible(window.opening_side) and not form.isRowVisible(window.slide_from)
    window.opening_side.setCurrentIndex(window.opening_side.findData("back"))
    window.opening_side.activated.emit(window.opening_side.currentIndex())
    assert window.project.lid.opening_side == "back"
    window.wall_spin.setValue(2.4)
    window.lid_style.setCurrentIndex(window.lid_style.findData("sliding"))
    window.lid_style.activated.emit(window.lid_style.currentIndex())
    assert form.isRowVisible(window.slide_from) and not form.isRowVisible(window.opening_side)
    window.slide_from.setCurrentIndex(window.slide_from.findData("right"))
    window.slide_from.activated.emit(window.slide_from.currentIndex())
    assert window.project.lid.slide_from == "right"
    assert "from the right" in window.lid_tip.text()
    assert not validation_errors(window)


def test_shape_after_template_starts_over(window):
    from threedn00b.model import default_project
    combo = window.template_combo
    combo.activated.emit(combo.findData("pi"))
    assert window.project.mounts and window.template_note.isVisibleTo(window)
    window.shape_buttons[BOX].click()                     # a plain box, not the Pi case
    plain = default_project(BOX)
    p = window.project
    assert (p.name, p.holes, p.mounts, p.lid.enabled, p.template) == (
        plain.name, [], [], False, "")
    assert (p.width, p.depth, p.height, p.size_mode) == (plain.width, plain.depth, plain.height,
                                                         plain.size_mode)
    assert not window.template_note.isVisibleTo(window)
    window.undo_stack.undo()                              # the Pi case comes back
    assert window.project.template == "pi" and window.project.mounts
    window.shape_buttons[CYLINDER].click()
    assert window.project.shape == CYLINDER and not window.project.holes
    assert window.project.name == "My container" and not window.project.mounts
    combo.activated.emit(combo.findData("jar"))           # a round template, then round again
    window.shape_buttons[CYLINDER].click()
    assert not window.project.lid.enabled and window.project.template == ""
    assert not validation_errors(window)


def test_shape_change_keeps_your_own_holes(window):
    window.add_hole()
    window.shape_buttons[CYLINDER].click()               # your own design: just reshaped
    assert window.project.shape == CYLINDER and len(window.project.holes) == 1
    assert window.project.holes[0].surface == "side"


def test_welcome_tour(window):
    from PySide6.QtCore import QTimer
    from threedn00b.gui.welcome import PAGES, WelcomeDialog
    assert window.welcome_due()                            # first start: show it
    dialog = WelcomeDialog(window)
    dialog.show()
    assert not dialog.back_button.isVisible() and dialog.next_button.text() == "Take the tour"
    dialog.go(1)                                           # takes the pictures once
    assert len(dialog._shots) == len(PAGES)
    size = dialog._shots[0].size()
    assert all(not s.isNull() and s.size() == size for s in dialog._shots)
    for _ in PAGES[1:]:
        dialog._next()
    assert dialog.next_button.text() == "Start designing" and not dialog.skip_button.isVisible()
    dialog._next()
    assert dialog.result() == dialog.DialogCode.Accepted

    def close_tour(check):
        from PySide6.QtWidgets import QApplication
        tour = QApplication.activeModalWidget()
        tour.startup_check.setChecked(check)
        tour.accept()
    QTimer.singleShot(0, lambda: close_tour(False))
    window.show_welcome()
    assert not window.welcome_due()                        # seen, and not asked for again
    QTimer.singleShot(0, lambda: close_tour(True))
    window.welcome_action.trigger()                        # Help > Welcome tour (F1)
    assert window.welcome_due()                            # the user asked to see it each time


def test_tour_highlights_the_right_parts(window):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QPixmap
    from threedn00b import templates
    from threedn00b.gui.welcome import PAGES, highlight
    window._load(templates.from_template("pi"), None)
    for page in PAGES:
        window.tabs.setCurrentIndex(page.step)
        page.prepare(window)
        QApplication.processEvents()
        widgets = page.highlights(window)
        rects = page.rects(window)
        assert len(rects) == len(widgets)                  # everything named is on screen
        assert all(not r.isEmpty() and window.rect().contains(r.center()) for r in rects)
        # The step being explained is highlighted in the rail too, and it's the selected one.
        step = window.rail_buttons[page.step]
        assert (step in widgets) == page.show_step
        assert step.isChecked()
    plain = QPixmap(200, 100)
    plain.fill(QColor("#808080"))
    marked = highlight(plain, [QRect(20, 20, 60, 60)]).toImage()
    assert marked.pixelColor(50, 50).name() == "#808080"   # the highlighted part stays bright
    assert marked.pixelColor(150, 50).value() < 80         # the rest is darkened


def test_see_through_view(window):
    from threedn00b.gui.viewer import BACKGROUND, GhostMesh, ON_TOP_OPTIONS
    window.lid_check.setChecked(True)
    window.add_hole()
    window.rebuild()
    viewer = window.viewer
    assert not window.see_through_action.isChecked() and not viewer.see_through
    assert window.see_through_action.shortcut().toString() == "Ctrl+T"
    window.see_through_action.setChecked(True)
    assert viewer.see_through
    assert viewer._mesh_items and all(isinstance(m, GhostMesh) for m in viewer._mesh_items)
    assert all(m.opts["color"][3] < 0.5 for m in viewer._mesh_items)        # faint
    # The hole outlines are drawn on top (pyqtgraph keeps the options in a private field).
    assert all(m._GLGraphicsItem__glOpts == ON_TOP_OPTIONS for m in viewer._marker_items)
    shot = viewer.grabFramebuffer()
    assert not shot.isNull()
    window.see_through_action.setChecked(False)                 # back to solid
    assert not any(isinstance(m, GhostMesh) for m in viewer._mesh_items)
    image = viewer.grabFramebuffer()
    # Still draws normally afterwards: the box covers the middle of the view.
    c = image.pixelColor(image.width() // 2, image.height() // 2)
    assert (c.red(), c.green(), c.blue()) != BACKGROUND
    window.show_lid_action.trigger()                           # Lid (Ctrl+L) hides the lid
    assert "lid" not in viewer._solids


def choose(combo, data):
    combo.setCurrentIndex(combo.findData(data))
    combo.activated.emit(combo.currentIndex())


def test_printer_card_checks_and_remembers(window):
    from threedn00b.gui.main_window import MainWindow, release_window
    assert window.printer() is None
    assert not window.bed_row.isVisibleTo(window)
    window.tabs.setCurrentIndex(TAB_CHECK)
    choose(window.printer_combo, "prusa-mini")
    assert window.printer().name == "Prusa MINI+" and window.printer().width == 180
    window.width_spin.setValue(200)
    window.rebuild()
    assert any("doesn't fit" in i.message for i in window.issues)
    choose(window.printer_combo, "custom")
    assert window.bed_row.isVisibleTo(window)
    window.bed_w.setValue(300)
    assert window.printer().width == 300
    assert not any("doesn't fit" in i.message for i in window.issues)
    choose(window.nozzle_combo, 0.6)
    choose(window.material_combo, "PETG")
    window.price_spin.setValue(300)
    # The choice is kept for the next time 3Dn00b starts.
    again = MainWindow()
    try:
        p = again.printer()
        assert (p.width, p.nozzle) == (300, 0.6)
        assert again.material_combo.currentData() == "PETG"
        assert again.price_spin.value() == 300
    finally:
        release_window(again)


def test_plastic_estimate_and_wall_fix(window):
    window.lid_check.setChecked(True)
    window.rebuild()
    text = window.parts_summary.text()
    assert "g of PLA (" in text and "Cost" in text      # box + lid, and a price
    window.price_spin.setValue(0)
    assert "Cost" not in window.parts_summary.text()
    window.wall_spin.setValue(1.8)
    choose(window.printer_combo, "prusa-mk4")
    window.tabs.setCurrentIndex(TAB_CHECK)
    row = next(i for i, issue in enumerate(window.issues) if issue.fix_values)
    offset = 0 if any(i.level != "info" for i in window.issues) else 1
    window.issue_list.setCurrentRow(row + offset)
    assert window.fix_button.isVisibleTo(window)
    assert window.fix_button.text() == "Make them 2 mm"
    window.fix_button.click()
    assert window.project.wall == 2.0
    window.undo_stack.undo()
    assert window.project.wall == 1.8


def test_fit_test_card(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path)))
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a[2])))
    window.tabs.setCurrentIndex(TAB_CHECK)
    assert not window.fit_button.isEnabled()
    assert "Nothing to test yet" in window.fit_summary.text()
    assert window.fit_lid_check.isHidden() and window.fit_openings_check.isHidden()
    window.lid_check.setChecked(True)
    window.rebuild()
    assert window.fit_button.isEnabled() and not window.fit_lid_check.isHidden()
    assert "instead of" in window.fit_summary.text()
    assert window.fit_test_choice() == (True, False)
    window.fit_lid_check.setChecked(False)
    assert not window.fit_button.isEnabled()
    window.fit_lid_check.setChecked(True)
    window.fit_button.click()
    assert (tmp_path / "my-box-fit-test-box-top.stl").exists()
    assert (tmp_path / "my-box-fit-test-lid.stl").exists()
    assert "Print these first" in shown[-1]
    window.add_mount("rpi-ab")
    window.rebuild()
    assert window.fit_openings_check.text().startswith("Screw posts")
    window.format_combo.setCurrentIndex(window.format_combo.findData("3mf"))
    assert window.fit_button.text() == "Export fit test (3MF)…"


def test_text_step(window):
    from PySide6.QtTest import QTest
    from threedn00b.model import ENGRAVED, LID, RAISED
    window.add_label()
    assert window.tabs.currentIndex() == TAB_TEXT
    label = window.project.labels[0]
    assert (label.surface, label.style) == (FRONT, RAISED)     # no lid: on the front wall
    assert window.label_card.isVisible() and window.label_text.hasSelectedText()
    QTest.keyClicks(window.label_text, "Screws")                # types over "Text"
    assert window.project.labels[0].text == "Screws"
    window.undo_stack.undo()                                    # typing is one undo step
    assert window.project.labels[0].text == "Text"
    window.undo_stack.redo()
    window.label_size.setValue(10)
    window.label_style.setCurrentIndex(window.label_style.findData(ENGRAVED))
    window.label_style.activated.emit(window.label_style.currentIndex())
    assert window.project.labels[0].style == ENGRAVED and window.label_depth_name.text() == "Cut in"
    window.rebuild()
    assert "Screws · Front wall · engraved" in window.label_list.item(0).text()
    assert "1 text" in window.parts_summary.text()
    window.lid_check.setChecked(True)
    window.rebuild()
    window.label_surface.setCurrentIndex(window.label_surface.findData(LID))
    window.label_surface.activated.emit(window.label_surface.currentIndex())
    assert window.project.labels[0].surface == LID
    window._center_label()
    assert (window.project.labels[0].u, window.project.labels[0].v) == (0, 0)
    window.remove_selected_label()
    assert window.project.labels == [] and not window.label_card.isVisible()


def test_text_problem_fix(window):
    from threedn00b.model import LID, RAISED, ENGRAVED
    window.lid_check.setChecked(True)
    window.rebuild()
    window.add_label(LID)
    window._edit_label("Style", "style", RAISED)
    window.rebuild()
    assert "upside down" in window.label_problem.text() and window.label_problem.isVisible()
    window.tabs.setCurrentIndex(TAB_CHECK)
    row = next(i for i, issue in enumerate(window.issues) if issue.label_id)
    offset = 0 if any(i.level != "info" for i in window.issues) else 1
    window.issue_list.setCurrentRow(row + offset)
    assert window.fix_button.text() == "Engrave it instead"
    window.fix_button.click()
    assert window.project.labels[0].style == ENGRAVED


def test_drag_text(window):
    from PySide6.QtCore import QPoint
    window.add_label()
    window.rebuild()
    label = window.project.labels[0]
    window.select_label(None)
    window.tabs.setCurrentIndex(0)
    p = window.project
    x, y = window.viewer.project_point((label.u, -p.outer_depth / 2, p.outer_height / 2 + label.v))
    start = QPoint(round(x), round(y))
    _drag(window.viewer, start, start + QPoint(-40, 0))
    assert window.tabs.currentIndex() == TAB_TEXT and window.selected_label_id == label.id
    assert window.project.labels[0].u < label.u - 5
    window.undo_stack.undo()
    assert window.project.labels[0].u == label.u



def test_recent_designs(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    first, second = tmp_path / "first.3dn00b", tmp_path / "second.3dn00b"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(first), "")))
    window.width_spin.setValue(90)
    assert window.save_project()
    project_io.save_project(project_io.load_project(first), second)
    window.open_path(second)
    assert window.recent_files() == [second, first]           # newest first
    window._fill_recent_menu()
    texts = [a.text() for a in window.recent_menu.actions() if a.text()]
    assert texts[0].startswith("second") and texts[1].startswith("first")
    assert texts[-1] == "Clear the list"
    first.unlink()
    window._fill_recent_menu()                                # gone files are forgotten
    assert window.recent_files() == [second]
    window.width_spin.setValue(95)
    window.save_project()                                     # saving makes it the newest
    assert window.recent_files() == [second]
    window.recent_menu.actions()[-1].trigger()                # Clear the list
    window._fill_recent_menu()
    assert window.recent_files() == []
    assert not window.recent_menu.actions()[0].isEnabled()    # "No recent designs"


def test_save_and_start_from_my_template(window, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    from threedn00b import userdata
    from threedn00b.gui.main_window import MANAGE_TEMPLATES, MyTemplatesDialog
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Screw box", True)))
    window.width_spin.setValue(111)
    assert window.save_as_my_template()
    combo = window.template_combo
    keys = [combo.itemData(i) for i in range(combo.count())]
    assert combo.itemText(1) == "My templates" and keys[2] == "my:Screw box"
    assert MANAGE_TEMPLATES in keys
    window.width_spin.setValue(70)
    combo.activated.emit(2)                                   # start from it
    assert window.project.width == 111 and window.project.template == "my:Screw box"
    assert "your “Screw box” template" in window.template_note.text()
    window._on_shape_clicked(CYLINDER)                        # starts over, like a template
    assert window.project.shape == CYLINDER and window.project.holes == []
    window.undo_stack.undo()
    assert window.project.width == 111
    # Saving again under the same name asks first.
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    assert not window.save_as_my_template()
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    dialog = MyTemplatesDialog(window)
    assert dialog.list.count() == 1 and dialog.remove_button.isEnabled()
    dialog.remove()
    assert dialog.list.count() == 0 and userdata.my_templates() == []
    dialog.accept()
    window._fill_template_combo()
    assert "My templates" not in [combo.itemText(i) for i in range(combo.count())]


def test_backup_and_recovery(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from threedn00b.gui.autosave import leftover_backups
    from threedn00b.userdata import autosave_dir
    window.width_spin.setValue(101)
    assert window._autosave_timer.isActive()                  # a backup is on its way
    window._write_autosave()
    assert window.autosave.path.exists()
    assert leftover_backups() == []                           # this window's own: not offered
    # A backup left by a 3Dn00b that crashed (no lock), from a saved file.
    lost = default_design(width=133.0)
    file = tmp_path / "lost.3dn00b"
    project_io.save_project(lost, file)
    import json
    left = autosave_dir() / "crashed.autosave"
    left.write_text(json.dumps({"saved_at": 1.0, "file": str(file),
                                "project": project_io.to_dict(lost)}))
    window.undo_stack.setClean()
    assert not window.autosave.path.exists()                  # saved: no backup needed
    monkeypatch.setattr(QMessageBox, "exec", lambda box: box.defaultButton().click())
    assert window.offer_recovery(leftover_backups())          # Recover
    assert window.project.width == 133.0 and window.path == file
    assert not window.undo_stack.isClean()                    # still has to be saved
    assert not left.exists() and window.autosave.path.exists()
    # Throwing a backup away deletes it.
    left.write_text(json.dumps({"saved_at": 1.0, "file": None,
                                "project": project_io.to_dict(lost)}))
    monkeypatch.setattr(QMessageBox, "exec", lambda box: 0)
    assert not window.offer_recovery(leftover_backups())
    assert not left.exists()
    window.close_autosave()                                   # closing normally
    assert not window.autosave.path.exists()


def default_design(**kw):
    from threedn00b.model import default_project
    p = default_project(BOX)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def test_sizes_in_the_3d_view(window):
    from threedn00b.gui.viewer import MeasureLabel
    viewer = window.viewer
    window.rebuild()

    def labels():
        return [i.text for i in viewer._measure_items if isinstance(i, MeasureLabel)]
    assert labels() == ["80 mm", "60 mm", "40 mm"]            # on by default
    window.add_hole()
    window.rebuild()
    assert labels() == ["80 mm", "60 mm", "40 mm", "40 mm", "20 mm"]   # and the hole's place
    window.sizes_action.trigger()                             # Ctrl+M
    assert labels() == [] and window.settings.value("view/sizes", type=bool) is False
    window.sizes_action.trigger()
    assert len(labels()) == 5
    image = viewer.grabFramebuffer()
    assert not image.isNull()


def test_delete_key_removes_text_on_the_text_step(window):
    window.add_hole()
    window.add_label()
    assert window.tabs.currentIndex() == TAB_TEXT
    window._delete_selected()
    assert window.project.labels == [] and len(window.project.holes) == 1


def test_cut_through_text_in_the_text_step(window):
    from threedn00b.model import CUT_THROUGH, LID
    window.add_label()
    style = window.label_style
    style.setCurrentIndex(style.findData(CUT_THROUGH))
    style.activated.emit(style.currentIndex())
    assert window.project.labels[0].style == CUT_THROUGH
    assert not window.label_depth.isVisibleTo(window)            # it goes right through
    assert window.label_style_hint.isVisibleTo(window)
    window.rebuild()
    assert "cut through" in window.label_list.item(0).text()
    window.lid_check.setChecked(True)
    window.rebuild()
    surface = window.label_surface
    surface.setCurrentIndex(surface.findData(LID))
    surface.activated.emit(surface.currentIndex())
    assert window.project.labels[0].style == CUT_THROUGH          # stays cut through on the lid


def test_size_lines_follow_the_view(window):
    from threedn00b.gui.viewer import MeasureLabel
    viewer = window.viewer
    window.rebuild()

    def width_label_y():
        return next(i.pos[1] for i in viewer._measure_items
                    if isinstance(i, MeasureLabel) and i.text == "80 mm")
    assert width_label_y() < 0                                     # along the front
    viewer.setCameraPosition(azimuth=100)                          # look from behind
    assert width_label_y() > 0                                     # now along the back
    viewer.orbit(-160, 0)                                          # turn round with the mouse
    assert width_label_y() < 0
