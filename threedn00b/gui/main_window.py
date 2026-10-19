"""Main window: a small guided control panel next to a large 3D preview."""

from __future__ import annotations

import copy
import gc
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox,
                               QPushButton, QRadioButton, QSizePolicy, QSplitter,
                               QStyle, QTabWidget, QToolBar, QVBoxLayout, QWidget)

from .. import APP_NAME, geometry, picking, project_io, validation
from ..model import (BOTTOM, BOX, CYLINDER, FIT_LABELS, FIT_PRESETS, FRONT,
                     HOLE_DIAMETER_RANGE, INSIDE, LID, MIN_EDGE, OUTSIDE, SIDE,
                     SIZE_RANGE, SURFACE_LABELS, WALL_RANGE, Hole, Project,
                     clamp_hole, default_project, wall_limits)
from .viewer import Viewer

COMMON_HOLES = [
    ("Common sizes…", None),
    ("M3 screw (3.4 mm)", 3.4),
    ("M4 screw (4.5 mm)", 4.5),
    ("Thin cable (5 mm)", 5.0),
    ("Cable with plug (8 mm)", 8.0),
    ("Thick cable / grommet (12 mm)", 12.0),
]


class SnapshotCommand(QUndoCommand):
    """Undo step that swaps whole-project snapshots (simple and reliable)."""

    _ids: dict[str, int] = {}

    def __init__(self, window, before: dict, after: dict, label: str, merge_key: str | None):
        super().__init__(label)
        self.window, self.before, self.after, self.merge_key = window, before, after, merge_key

    def id(self):
        if self.merge_key is None:
            return -1
        return self._ids.setdefault(self.merge_key, len(self._ids) + 1)

    def mergeWith(self, other):
        if other.merge_key != self.merge_key:
            return False
        self.after = other.after
        return True

    def redo(self):
        self.window.restore(self.after)

    def undo(self):
        self.window.restore(self.before)


def spin(lo, hi, value=0.0, suffix=" mm", step=1.0, decimals=1):
    box = QDoubleSpinBox()
    box.setRange(lo, hi)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setSuffix(suffix)
    box.setValue(value)
    box.setAlignment(Qt.AlignmentFlag.AlignRight)
    return box


def hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #556;")
    return label


def set_quietly(widget, value):
    widget.blockSignals(True)
    if isinstance(widget, QDoubleSpinBox):
        widget.setValue(value)
    elif isinstance(widget, (QCheckBox, QRadioButton, QPushButton)):
        widget.setChecked(value)
    elif isinstance(widget, QLineEdit):
        if widget.text() != value:
            widget.setText(value)
    elif isinstance(widget, QComboBox):
        widget.setCurrentIndex(max(0, widget.findData(value)))
    widget.blockSignals(False)


class MainWindow(QMainWindow):
    def __init__(self, project: Project | None = None):
        super().__init__()
        self.project = project or default_project()
        self.path: Path | None = None
        self.selected_id: str | None = None
        self._drag: dict | None = None
        self._drag_count = 0
        self.parts: geometry.Parts | None = None
        self.issues: list[validation.Issue] = []
        self.undo_stack = QUndoStack(self)
        self.undo_stack.cleanChanged.connect(self._update_title)
        self.settings = QSettings(APP_NAME, APP_NAME)

        self._rebuild_timer = QTimer(self, singleShot=True, interval=60)
        self._rebuild_timer.timeout.connect(self.rebuild)

        self.viewer = Viewer()
        self.viewer.drag_handler = self
        self.viewer.surfaceDoubleClicked.connect(self._on_surface_double_clicked)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_shape_tab(), "1  Shape")
        self.tabs.addTab(self._build_holes_tab(), "2  Holes")
        self.tabs.addTab(self._build_lid_tab(), "3  Lid")
        self.tabs.addTab(self._build_check_tab(), "4  Check && Export")
        self.tabs.setMinimumWidth(340)
        self.tabs.setMaximumWidth(460)

        splitter = QSplitter()
        splitter.addWidget(self.viewer)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([820, 380])
        splitter.setChildrenCollapsible(False)
        self.setCentralWidget(splitter)

        self._build_toolbar()
        self.status_badge = QLabel()
        self.statusBar().addPermanentWidget(self.status_badge)
        self.resize(1240, 780)

        self.refresh_controls()
        self.rebuild()
        self._update_title()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_toolbar(self):
        bar = QToolBar("Main")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(bar)
        style = self.style()

        def action(text, icon, slot, shortcut=None, tip=None):
            act = QAction(style.standardIcon(icon), text, self)
            act.triggered.connect(slot)
            if shortcut:
                act.setShortcut(shortcut)
            if tip:
                act.setToolTip(tip)
            bar.addAction(act)
            return act

        action("New", QStyle.StandardPixmap.SP_FileIcon, self.new_project, QKeySequence.StandardKey.New)
        action("Open", QStyle.StandardPixmap.SP_DialogOpenButton, self.open_project, QKeySequence.StandardKey.Open)
        action("Save", QStyle.StandardPixmap.SP_DialogSaveButton, self.save_project, QKeySequence.StandardKey.Save,
               "Save an editable project file")
        save_as = QAction("Save As…", self)
        save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_as.triggered.connect(self.save_project_as)
        self.addAction(save_as)
        bar.addSeparator()
        undo = self.undo_stack.createUndoAction(self, "Undo")
        undo.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        undo.setShortcut(QKeySequence.StandardKey.Undo)
        redo = self.undo_stack.createRedoAction(self, "Redo")
        redo.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        redo.setShortcut(QKeySequence.StandardKey.Redo)
        bar.addAction(undo)
        bar.addAction(redo)
        bar.addSeparator()
        action("Reset view", QStyle.StandardPixmap.SP_BrowserReload,
               lambda: self.viewer.reset_view(self.project))
        self.show_lid_action = QAction("Show lid", self, checkable=True, checked=True)
        self.show_lid_action.toggled.connect(self._on_show_lid)
        bar.addAction(self.show_lid_action)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        self.export_action = action("Export for printing…", QStyle.StandardPixmap.SP_DriveHDIcon,
                                    self.export_stl, QKeySequence("Ctrl+E"),
                                    "Save STL files you can open in your slicer")
        delete = QAction(self, shortcut=QKeySequence.StandardKey.Delete)
        delete.triggered.connect(self.remove_selected_hole)
        self.addAction(delete)

    def _build_shape_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel("<b>What are you making?</b>"))
        row = QHBoxLayout()
        self.shape_group = QButtonGroup(self)
        self.shape_buttons = {}
        for shape, text in ((BOX, "▭  Box"), (CYLINDER, "◯  Round container")):
            btn = QPushButton(text, checkable=True)
            btn.setMinimumHeight(40)
            self.shape_group.addButton(btn)
            self.shape_buttons[shape] = btn
            btn.clicked.connect(lambda _=False, s=shape: self.edit("Change shape", lambda p: p.set_shape(s)))
            row.addWidget(btn)
        layout.addLayout(row)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(
            lambda t: self.edit("Rename", lambda p: setattr(p, "name", t), merge="name"))
        form.addRow("Name", self.name_edit)
        layout.addLayout(form)

        layout.addWidget(QLabel("<b>The sizes below are</b>"))
        row = QHBoxLayout()
        self.mode_outside = QRadioButton("Outside size")
        self.mode_inside = QRadioButton("Inside space")
        for btn, mode in ((self.mode_outside, OUTSIDE), (self.mode_inside, INSIDE)):
            btn.toggled.connect(lambda on, m=mode: on and self.edit(
                "Change measuring", lambda p: p.set_size_mode(m)))
            row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)
        layout.addWidget(hint("Outside = how big the finished object is. "
                              "Inside = how much room there is for your things."))

        form = QFormLayout()
        self.width_spin = spin(*SIZE_RANGE)
        self.depth_spin = spin(*SIZE_RANGE)
        self.diameter_spin = spin(*SIZE_RANGE)
        self.height_spin = spin(*SIZE_RANGE)
        self.wall_spin = spin(*WALL_RANGE, step=0.2, decimals=2)
        self.bottom_spin = spin(*WALL_RANGE, step=0.2, decimals=2)
        self.corner_spin = spin(0.0, 150.0, step=1.0)
        self.width_spin.setToolTip("Left to right")
        self.depth_spin.setToolTip("Front to back")
        self.height_spin.setToolTip("Bottom to top, without the lid")
        self.corner_spin.setToolTip("How round the corners are when seen from above. 0 = sharp corners.")
        self.width_label, self.depth_label = QLabel("Width"), QLabel("Depth")
        self.diameter_label, self.corner_label = QLabel("Diameter"), QLabel("Rounded corners")
        form.addRow(self.width_label, self.width_spin)
        form.addRow(self.depth_label, self.depth_spin)
        form.addRow(self.diameter_label, self.diameter_spin)
        form.addRow("Height", self.height_spin)
        form.addRow("Wall thickness", self.wall_spin)
        form.addRow("Bottom thickness", self.bottom_spin)
        form.addRow(self.corner_label, self.corner_spin)
        layout.addLayout(form)
        for widget, attr, label in (
                (self.width_spin, "width", "Change width"),
                (self.depth_spin, "depth", "Change depth"),
                (self.diameter_spin, "diameter", "Change diameter"),
                (self.height_spin, "height", "Change height"),
                (self.wall_spin, "wall", "Change wall thickness"),
                (self.bottom_spin, "bottom", "Change bottom thickness"),
                (self.corner_spin, "corner_radius", "Change corners")):
            widget.valueChanged.connect(
                lambda value, a=attr, lbl=label: self.edit(lbl, lambda p: setattr(p, a, value), merge=a))

        self.size_summary = QLabel()
        self.size_summary.setWordWrap(True)
        self.size_summary.setFrameShape(QFrame.Shape.StyledPanel)
        self.size_summary.setStyleSheet("padding: 6px; background: #f4f6f9;")
        layout.addWidget(self.size_summary)
        layout.addStretch()
        return page

    def _build_holes_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(hint("Holes for cables, screws, buttons or air.\n"
                              "Tip: double-click a wall in the 3D view to put a hole right there."))
        self.add_hole_button = QPushButton("+  Add hole")
        self.add_hole_button.setMinimumHeight(34)
        # A lambda, because clicked() would otherwise pass its 'checked' flag as `surface`.
        self.add_hole_button.clicked.connect(lambda: self.add_hole())
        layout.addWidget(self.add_hole_button)
        self.hole_list = QListWidget()
        self.hole_list.setMaximumHeight(150)
        self.hole_list.currentRowChanged.connect(self._on_hole_row_changed)
        layout.addWidget(self.hole_list)

        self.hole_box = QWidget()
        form = QFormLayout(self.hole_box)
        form.setContentsMargins(0, 0, 0, 0)
        self.surface_combo = QComboBox()
        self.surface_combo.activated.connect(self._on_surface_changed)
        form.addRow("Where", self.surface_combo)
        self.hole_diameter = spin(*HOLE_DIAMETER_RANGE, step=0.5)
        self.hole_diameter.valueChanged.connect(
            lambda v: self._edit_hole("Change hole size", "diameter", v))
        form.addRow("Diameter", self.hole_diameter)
        self.common_sizes = QComboBox()
        for text, value in COMMON_HOLES:
            self.common_sizes.addItem(text, value)
        self.common_sizes.activated.connect(self._on_common_size)
        form.addRow("", self.common_sizes)
        self.u_label, self.v_label = QLabel(), QLabel()
        self.hole_u = spin(-500, 500, step=1.0)
        self.hole_v = spin(-500, 500, step=1.0)
        self.hole_u.valueChanged.connect(lambda v: self._edit_hole("Move hole", "u", v))
        self.hole_v.valueChanged.connect(lambda v: self._edit_hole("Move hole", "v", v))
        form.addRow(self.u_label, self.hole_u)
        form.addRow(self.v_label, self.hole_v)
        form.addRow("", hint("Measured from the middle of the surface. 0 = centred."))
        buttons = QHBoxLayout()
        center = QPushButton("Centre it")
        center.clicked.connect(self._center_hole)
        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove_selected_hole)
        buttons.addWidget(center)
        buttons.addWidget(remove)
        form.addRow(buttons)
        layout.addWidget(self.hole_box)
        self.hole_problem = hint("")
        self.hole_problem.setStyleSheet("color: #b02020;")
        layout.addWidget(self.hole_problem)
        layout.addStretch()
        return page

    def _build_lid_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.lid_check = QCheckBox("Add a lid")
        self.lid_check.setStyleSheet("font-weight: bold;")
        self.lid_check.toggled.connect(
            lambda on: self.edit("Turn lid on" if on else "Turn lid off",
                                 lambda p: setattr(p.lid, "enabled", on)))
        layout.addWidget(self.lid_check)
        layout.addWidget(hint("A push-on lid: a flat top with a lip that slides "
                              "into the box and holds by friction."))
        self.lid_box = QWidget()
        form = QFormLayout(self.lid_box)
        form.setContentsMargins(0, 0, 0, 0)
        self.fit_combo = QComboBox()
        for key in ("tight", "normal", "loose", "custom"):
            gap = f" ({FIT_PRESETS[key]:.2f} mm gap)" if key in FIT_PRESETS else ""
            self.fit_combo.addItem(FIT_LABELS[key] + gap, key)
        self.fit_combo.activated.connect(
            lambda _: self.edit("Change lid fit",
                                lambda p: setattr(p.lid, "fit", self.fit_combo.currentData())))
        form.addRow("Fit", self.fit_combo)
        self.gap_spin = spin(0.0, 1.5, step=0.05, decimals=2)
        self.gap_spin.setToolTip("Space between the lid's lip and the wall, on each side")
        self.gap_spin.valueChanged.connect(
            lambda v: self.edit("Change lid gap", lambda p: setattr(p.lid, "custom_gap", v), merge="gap"))
        self.gap_label = QLabel("Gap per side")
        form.addRow(self.gap_label, self.gap_spin)
        self.lid_thickness = spin(*WALL_RANGE, step=0.2, decimals=2)
        self.lid_thickness.valueChanged.connect(
            lambda v: self.edit("Change lid thickness", lambda p: setattr(p.lid, "thickness", v),
                                merge="lid_t"))
        form.addRow("Lid thickness", self.lid_thickness)
        self.lip_height = spin(1.0, 50.0, step=0.5)
        self.lip_height.setToolTip("How far the lip reaches down into the box")
        self.lip_height.valueChanged.connect(
            lambda v: self.edit("Change lip depth", lambda p: setattr(p.lid, "lip_height", v),
                                merge="lip"))
        form.addRow("Lip depth", self.lip_height)
        layout.addWidget(self.lid_box)
        layout.addWidget(hint(
            "Normal fits most printers. If your lid ends up too tight, choose Loose "
            "and print just the lid again; if it falls off, choose Tight.\n\n"
            "The lid is exported upside down, which is the best way to print it."))
        layout.addStretch()
        return page

    def _build_check_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.parts_summary = QLabel()
        self.parts_summary.setWordWrap(True)
        self.parts_summary.setFrameShape(QFrame.Shape.StyledPanel)
        self.parts_summary.setStyleSheet("padding: 6px; background: #f4f6f9;")
        layout.addWidget(self.parts_summary)
        layout.addWidget(QLabel("<b>Checks</b>"))
        self.issue_list = QListWidget()
        self.issue_list.setWordWrap(True)
        self.issue_list.currentRowChanged.connect(self._on_issue_row_changed)
        layout.addWidget(self.issue_list, 1)
        self.fix_button = QPushButton("Fix it")
        self.fix_button.clicked.connect(self._apply_fix)
        self.fix_button.setVisible(False)
        layout.addWidget(self.fix_button)
        self.export_button = QPushButton("Export for printing (STL)…")
        self.export_button.setMinimumHeight(40)
        self.export_button.clicked.connect(self.export_stl)
        layout.addWidget(self.export_button)
        self.export_hint = hint("")
        layout.addWidget(self.export_hint)
        layout.addWidget(hint("Checks catch problems in the design. They can't guarantee a "
                              "perfect print: that also depends on your printer, material "
                              "and slicer settings."))
        return page

    # ------------------------------------------------------------------
    # Editing + undo
    # ------------------------------------------------------------------
    def edit(self, label: str, change, merge: str | None = None):
        before = project_io.to_dict(self.project)
        trial = copy.deepcopy(self.project)
        change(trial)
        after = project_io.to_dict(trial)
        if after == before:
            return
        self.undo_stack.push(SnapshotCommand(self, before, after, label, merge))

    def restore(self, data: dict):
        self.project = project_io.from_dict(data)
        if self.selected_id and not self.project.hole(self.selected_id):
            self.selected_id = None
        self.refresh_controls()
        # Throttle (not debounce) so the preview keeps up while dragging or typing.
        if not self._rebuild_timer.isActive():
            self._rebuild_timer.start()
        self.viewer.set_hole_markers(self.project, self.selected_id, self._problem_holes())
        self._update_title()

    def _edit_hole(self, label, attr, value):
        hole_id = self.selected_id
        if hole_id is None:
            return
        self.edit(label, lambda p: setattr(p.hole(hole_id), attr, value), merge=f"{hole_id}:{attr}")

    # ------------------------------------------------------------------
    # Refreshing widgets from the model
    # ------------------------------------------------------------------
    def refresh_controls(self):
        p = self.project
        is_box = p.shape == BOX
        for shape, btn in self.shape_buttons.items():
            set_quietly(btn, shape == p.shape)
        set_quietly(self.name_edit, p.name)
        set_quietly(self.mode_outside, p.size_mode == OUTSIDE)
        set_quietly(self.mode_inside, p.size_mode == INSIDE)
        for widget, value in ((self.width_spin, p.width), (self.depth_spin, p.depth),
                              (self.diameter_spin, p.diameter), (self.height_spin, p.height),
                              (self.wall_spin, p.wall), (self.bottom_spin, p.bottom),
                              (self.corner_spin, p.corner_radius)):
            set_quietly(widget, value)
        for widget in (self.width_spin, self.width_label, self.depth_spin, self.depth_label,
                       self.corner_spin, self.corner_label):
            widget.setVisible(is_box)
        self.diameter_spin.setVisible(not is_box)
        self.diameter_label.setVisible(not is_box)
        self._refresh_size_summary()

        set_quietly(self.lid_check, p.lid.enabled)
        self.lid_box.setEnabled(p.lid.enabled)
        set_quietly(self.fit_combo, p.lid.fit)
        set_quietly(self.gap_spin, p.lid.gap)
        self.gap_spin.setEnabled(p.lid.fit == "custom")
        set_quietly(self.lid_thickness, p.lid.thickness)
        set_quietly(self.lip_height, p.lid.lip_height)
        self.refresh_holes()

    def _refresh_size_summary(self):
        p = self.project
        if p.shape == BOX:
            outer = f"{p.outer_width:g} × {p.outer_depth:g} × {p.outer_height:g} mm"
            inner = f"{p.inner_width:g} × {p.inner_depth:g} × {p.inner_height:g} mm"
        else:
            outer = f"⌀ {p.outer_diameter:g} × {p.outer_height:g} mm"
            inner = f"⌀ {p.outer_diameter - 2 * p.wall:g} × {p.inner_height:g} mm"
        text = f"<b>Outside:</b> {outer}<br><b>Inside space:</b> {inner}"
        if p.lid.enabled:
            text += f"<br><b>Height with lid on:</b> {p.closed_height:g} mm"
        self.size_summary.setText(text)

    def refresh_holes(self):
        p = self.project
        problems = self._problem_holes()
        self.hole_list.blockSignals(True)
        self.hole_list.clear()
        current = -1
        for i, hole in enumerate(p.holes):
            where = SURFACE_LABELS.get(hole.surface, hole.surface)
            mark = "⚠ " if hole.id in problems else ""
            item = QListWidgetItem(f"{mark}Hole {i + 1} · {where} · {hole.diameter:g} mm")
            self.hole_list.addItem(item)
            if hole.id == self.selected_id:
                current = i
        self.hole_list.setCurrentRow(current)
        self.hole_list.blockSignals(False)

        hole = p.hole(self.selected_id) if self.selected_id else None
        self.hole_box.setEnabled(hole is not None)
        self.surface_combo.blockSignals(True)
        self.surface_combo.clear()
        for s in p.surfaces():
            self.surface_combo.addItem(SURFACE_LABELS[s], s)
        if hole is not None and hole.surface not in p.surfaces():
            self.surface_combo.addItem(SURFACE_LABELS.get(hole.surface, hole.surface) + " (gone)",
                                       hole.surface)
        self.surface_combo.blockSignals(False)
        if hole is None:
            self.u_label.setText("Left / right")
            self.v_label.setText("Up / down")
            self.hole_problem.setText("")
            return
        set_quietly(self.surface_combo, hole.surface)
        set_quietly(self.hole_diameter, hole.diameter)
        if hole.surface == SIDE:
            self.u_label.setText("Around")
            self.hole_u.setSuffix("°")
        else:
            self.u_label.setText("Left / right")
            self.hole_u.setSuffix(" mm")
        self.v_label.setText("Front / back" if hole.surface in (BOTTOM, LID) else "Up / down")
        limits = wall_limits(p, hole.surface, hole.diameter, MIN_EDGE)
        if limits is None:
            u_lo, u_hi, v_lo, v_hi = -1.0, 1.0, -1.0, 1.0
        else:
            u_lo, u_hi, v_lo, v_hi = limits
        if hole.surface == SIDE:
            u_lo, u_hi = -180.0, 180.0
        # Never let the spin box silently change a value that is already out of range.
        self.hole_u.blockSignals(True)
        self.hole_u.setRange(min(u_lo, hole.u), max(u_hi, hole.u))
        self.hole_u.setWrapping(hole.surface == SIDE)
        self.hole_u.blockSignals(False)
        self.hole_v.blockSignals(True)
        self.hole_v.setRange(min(v_lo, hole.v), max(v_hi, hole.v))
        self.hole_v.blockSignals(False)
        set_quietly(self.hole_u, hole.u)
        set_quietly(self.hole_v, hole.v)
        msgs = [i.message for i in self.issues if i.hole_id == hole.id and i.level != validation.INFO]
        self.hole_problem.setText("\n".join("⚠ " + m for m in msgs))

    def _problem_holes(self) -> set:
        return {i.hole_id for i in self.issues if i.hole_id and i.level != validation.INFO}

    # ------------------------------------------------------------------
    # Rebuilding geometry and checks
    # ------------------------------------------------------------------
    def rebuild(self):
        p = self.project
        try:
            size_issues = validation.check_size(p)
            if validation.has_errors(size_issues):
                self.parts, self.issues = None, size_issues
            else:
                self.parts = geometry.build_parts(p)
                self.issues = validation.check(p, self.parts)
        except Exception as exc:   # never crash the editor because of geometry trouble
            self.parts = None
            self.issues = [validation.Issue(validation.ERROR, "Something went wrong building the shape.",
                                            f"Try different measurements. ({exc})")]
        self.viewer.set_parts(p, self.parts)
        self.viewer.set_hole_markers(p, self.selected_id, self._problem_holes())
        self._refresh_issues()
        self.refresh_holes()

    def _refresh_issues(self):
        icons = {validation.ERROR: QStyle.StandardPixmap.SP_MessageBoxCritical,
                 validation.WARNING: QStyle.StandardPixmap.SP_MessageBoxWarning,
                 validation.INFO: QStyle.StandardPixmap.SP_MessageBoxInformation}
        self.issue_list.blockSignals(True)
        self.issue_list.clear()
        for issue in self.issues:
            text = issue.message + (f"\n{issue.hint}" if issue.hint else "")
            item = QListWidgetItem(self.style().standardIcon(icons[issue.level]), text)
            self.issue_list.addItem(item)
        if not any(i.level != validation.INFO for i in self.issues):
            item = QListWidgetItem(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton),
                                   "No problems found.")
            self.issue_list.insertItem(0, item)
        self.issue_list.blockSignals(False)
        self.fix_button.setVisible(False)

        errors = sum(i.level == validation.ERROR for i in self.issues)
        warnings = sum(i.level == validation.WARNING for i in self.issues)
        if errors:
            badge = (f"<span style='color:#b02020'>✖ {errors} problem{'s' * (errors > 1)} to fix "
                     "before export</span>")
        elif warnings:
            badge = f"<span style='color:#a06000'>⚠ Ready, with {warnings} warning{'s' * (warnings > 1)}</span>"
        else:
            badge = "<span style='color:#207020'>✔ Ready to print</span>"
        self.status_badge.setText(badge + " — see Check & Export")
        self.export_action.setEnabled(not errors)
        self.export_button.setEnabled(not errors)
        self.export_hint.setText("Fix the problems marked ✖ above to export." if errors else
                                 "Each part is saved as its own STL file, placed flat side down.")
        self.tabs.setTabText(3, "4  Check && Export" + (" ✖" if errors else " ⚠" if warnings else ""))
        self._refresh_parts_summary()

    def _refresh_parts_summary(self):
        if self.parts is None:
            self.parts_summary.setText("<b>Nothing to print yet:</b> fix the problems below.")
            return
        lines = []
        names = {"body": "Box" if self.project.shape == BOX else "Container", "lid": "Lid"}
        for part, solid in self.parts.printable().items():
            lo = solid.bounding_box()
            size = " × ".join(f"{lo[i + 3] - lo[i]:.1f}" for i in range(3))
            lines.append(f"<b>{names[part]}:</b> {size} mm, about {solid.volume() / 1000:.0f} cm³ of plastic")
        holes = len(self.project.holes)
        lines.append(f"{holes} hole{'s' * (holes != 1)}")
        self.parts_summary.setText("<br>".join(lines))

    # ------------------------------------------------------------------
    # Hole actions
    # ------------------------------------------------------------------
    def select_hole(self, hole_id: str | None):
        self.selected_id = hole_id
        self.refresh_holes()
        self.viewer.set_hole_markers(self.project, self.selected_id, self._problem_holes())

    def add_hole(self, surface: str | None = None, u: float = 0.0, v: float = 0.0):
        p = self.project
        if surface is None:
            current = p.hole(self.selected_id) if self.selected_id else None
            surface = current.surface if current else (FRONT if p.shape == BOX else SIDE)
        diameter = picking.fitting_diameter(p, surface)
        if diameter is None:
            self.statusBar().showMessage(f"There's no room for a hole on the "
                                         f"{SURFACE_LABELS[surface].lower()}.", 5000)
            return
        hole = Hole(surface=surface, diameter=diameter, u=u, v=v)
        # Start somewhere valid: keep the clicked spot if it is safe, else the nearest safe one.
        pos = clamp_hole(p, hole) or clamp_hole(p, hole, MIN_EDGE)
        if pos:
            hole.u, hole.v = pos
        self.edit("Add hole", lambda proj: proj.holes.append(copy.deepcopy(hole)))
        self.tabs.setCurrentIndex(1)
        self.select_hole(hole.id)

    def remove_selected_hole(self):
        hole_id = self.selected_id
        if hole_id is None or not self.project.hole(hole_id):
            return
        self.selected_id = None
        self.edit("Remove hole", lambda p: p.holes.remove(p.hole(hole_id)))

    def _center_hole(self):
        hole_id = self.selected_id
        if hole_id is None:
            return

        def change(p):
            h = p.hole(hole_id)
            if h.surface != SIDE:
                h.u = 0.0
            h.v = 0.0
            pos = clamp_hole(p, h)
            if pos:
                h.u, h.v = pos
        self.edit("Centre hole", change)

    def _on_surface_changed(self, _index):
        hole_id = self.selected_id
        surface = self.surface_combo.currentData()
        if hole_id is None or surface is None:
            return

        def change(p):
            h = p.hole(hole_id)
            if h.surface == surface:
                return
            h.surface, h.u, h.v = surface, 0.0, 0.0
            pos = clamp_hole(p, h) or clamp_hole(p, h, MIN_EDGE)
            if pos:
                h.u, h.v = pos
        self.edit("Move hole to another surface", change)

    def _on_common_size(self, index):
        value = self.common_sizes.itemData(index)
        self.common_sizes.setCurrentIndex(0)
        if value is not None:
            self._edit_hole("Change hole size", "diameter", value)

    def _on_hole_row_changed(self, row):
        holes = self.project.holes
        self.select_hole(holes[row].id if 0 <= row < len(holes) else None)

    # ---- dragging holes in the 3D view (called by the Viewer) ----------
    def _hole_under(self, origin, direction, mesh_distance):
        return picking.hole_under_ray(self.project, origin, direction, mesh_distance,
                                      self.viewer.lid_offset, self.viewer.show_lid)

    def hole_at(self, origin, direction, mesh_distance) -> bool:
        return self._hole_under(origin, direction, mesh_distance) is not None

    def drag_begin(self, origin, direction, mesh_distance) -> bool:
        hole = self._hole_under(origin, direction, mesh_distance)
        if hole is None:
            return False
        self.tabs.setCurrentIndex(1)
        self.select_hole(hole.id)
        hit = picking.surface_hit(self.project, hole.surface, origin, direction,
                                  self.viewer.lid_offset)
        if hit is None:
            return True
        # Remember where on the hole it was grabbed, so it doesn't jump. Each drag
        # gets its own undo merge key, so one drag = one undo step.
        self._drag_count += 1
        self._drag = {"id": hole.id, "du": hole.u - hit[1], "dv": hole.v - hit[2],
                      "key": f"drag:{self._drag_count}"}
        return True

    def drag_move(self, origin, direction):
        drag = self._drag
        hole = self.project.hole(drag["id"]) if drag else None
        if hole is None:
            return
        hit = picking.surface_hit(self.project, hole.surface, origin, direction,
                                  self.viewer.lid_offset)
        if hit is None:
            return
        u, v, note = picking.snap_drag(self.project, hole, hit[1] + drag["du"], hit[2] + drag["dv"])
        moved = copy.deepcopy(hole)
        moved.u, moved.v = u, v
        # Keep it on the surface with a safe margin; dragging never makes a broken hole.
        pos = clamp_hole(self.project, moved) or clamp_hole(self.project, moved, MIN_EDGE)
        if pos is None:
            return
        if abs(pos[0] - u) > 0.05 or abs(pos[1] - v) > 0.05:
            note = "kept away from the edge"
        hole_id = hole.id
        self.edit("Move hole", lambda p: _set_position(p.hole(hole_id), pos), merge=drag["key"])
        name = f"Hole {self.project.holes.index(self.project.hole(hole_id)) + 1}"
        self.statusBar().showMessage(f"{name}: {note}" if note else name, 1500)

    def drag_end(self):
        self._drag = None
        self.rebuild()

    def _on_surface_double_clicked(self, part, point, normal):
        found = picking.surface_at(self.project, point, normal, part)
        if not found:
            return
        surface, u, v = found
        if picking.find_hole(self.project, surface, u, v):
            return
        u, v = picking.snap(surface, u, v)
        self.add_hole(surface, u, v)

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------
    def _issue_at(self, row):
        offset = 0 if any(i.level != validation.INFO for i in self.issues) else 1
        index = row - offset
        return self.issues[index] if 0 <= index < len(self.issues) else None

    def _on_issue_row_changed(self, row):
        issue = self._issue_at(row)
        self.fix_button.setVisible(bool(issue and issue.fix))
        if issue and issue.fix:
            self.fix_button.setText(issue.fix_label or "Fix it")
        if issue and issue.hole_id:
            self.select_hole(issue.hole_id)

    def _apply_fix(self):
        issue = self._issue_at(self.issue_list.currentRow())
        if not issue or not issue.fix or not issue.hole_id:
            return
        hole_id, (u, v) = issue.hole_id, issue.fix

        def change(p):
            h = p.hole(hole_id)
            h.u, h.v = u, v
        self.edit("Fix hole position", change)
        self.statusBar().showMessage("Hole moved. Press Ctrl+Z to undo.", 5000)

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------
    def _confirm_discard(self) -> bool:
        if self.undo_stack.isClean():
            return True
        answer = QMessageBox.question(
            self, APP_NAME, "Save your changes first?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def new_project(self):
        if not self._confirm_discard():
            return
        self._load(default_project(), None)

    def _load(self, project: Project, path: Path | None):
        self.project = project
        self.path = path
        self.selected_id = None
        self.undo_stack.clear()
        self.viewer._fitted_size = None
        self.refresh_controls()
        self.rebuild()
        self._update_title()

    def _last_dir(self) -> str:
        return self.settings.value("last_dir", str(Path.home()))

    def open_project(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open project", self._last_dir(),
                                              f"3Dn00b projects (*{project_io.PROJECT_SUFFIX})")
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path):
        try:
            project = project_io.load_project(path)
        except project_io.ProjectFileError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self.settings.setValue("last_dir", str(path.parent))
        self._load(project, path)

    def save_project(self) -> bool:
        if self.path is None:
            return self.save_project_as()
        try:
            project_io.save_project(self.project, self.path)
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Couldn't save the project:\n{exc}")
            return False
        self.undo_stack.setClean()
        self.statusBar().showMessage(f"Saved {self.path.name}", 4000)
        self._update_title()
        return True

    def save_project_as(self) -> bool:
        suggested = Path(self._last_dir()) / (project_io.safe_file_stem(self.project.name)
                                              + project_io.PROJECT_SUFFIX)
        path, _ = QFileDialog.getSaveFileName(self, "Save project", str(suggested),
                                              f"3Dn00b projects (*{project_io.PROJECT_SUFFIX})")
        if not path:
            return False
        path = Path(path)
        if path.suffix != project_io.PROJECT_SUFFIX:
            path = path.with_name(path.name + project_io.PROJECT_SUFFIX)
        self.path = path
        self.settings.setValue("last_dir", str(path.parent))
        return self.save_project()

    def export_stl(self):
        if validation.has_errors(self.issues):
            self.tabs.setCurrentIndex(3)
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder for the STL files",
                                                  self._last_dir())
        if not folder:
            return
        stem = project_io.safe_file_stem(self.project.name)
        existing = [Path(folder) / f"{stem}-{part}.stl" for part in ("body", "lid")]
        existing = [f for f in existing if f.exists()]
        if existing and QMessageBox.question(
                self, APP_NAME, "Replace these files?\n" + "\n".join(f.name for f in existing)
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            files = project_io.export_stl_files(self.project, folder)
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Couldn't export:\n{exc}")
            return
        self.settings.setValue("last_dir", folder)
        QMessageBox.information(self, APP_NAME, "Saved for printing:\n\n"
                                + "\n".join(f.name for f in files)
                                + f"\n\nin {folder}\n\nOpen these in your slicer to print them.")

    def _update_title(self, clean: bool | None = None):
        if clean is None:
            clean = self.undo_stack.isClean()
        name = self.path.name if self.path else self.project.name
        star = "" if clean else " •"
        self.setWindowTitle(f"{name}{star} — {APP_NAME}")

    def _on_show_lid(self, on):
        self.viewer.show_lid = on
        self.rebuild()

    def closeEvent(self, event):
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()


def _set_position(hole: Hole, pos) -> None:
    hole.u, hole.v = pos


def release_window(window: MainWindow) -> None:
    """Drop the window's geometry before Python shuts down.

    Qt may keep the window alive until the very end; if Manifold solids are
    still referenced then, the geometry library prints scary (but harmless)
    "leaked instance" warnings in the terminal.
    """
    window._rebuild_timer.stop()
    window.parts = None
    window.viewer.release_geometry()
    window.undo_stack.clear()
    window.deleteLater()


def main_window_app(argv) -> int:
    app = QApplication.instance() or QApplication(argv)
    window = MainWindow()
    if len(argv) > 1:
        window.open_path(Path(argv[1]))
    window.show()
    code = app.exec()
    release_window(window)
    del window
    gc.collect()
    return code
