"""Main window: a small guided control panel next to a large 3D preview."""

from __future__ import annotations

import copy
import gc
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox,
                               QMenu, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSpinBox,
                               QSplitter, QStyle, QTabWidget, QToolBar, QToolButton,
                               QVBoxLayout, QWidget)

from .. import (APP_NAME, __version__, geometry, mounts, picking, project_io, templates,
                validation)
from ..model import (ALONG_U, ALONG_V, BOTTOM, BOX, CYLINDER, FIT_LABELS, FIT_PRESETS,
                     FRONT, HOLE_DIAMETER_RANGE, HOLE_KIND_LABELS, INSIDE, LID, MIN_EDGE,
                     OUTSIDE, RECT, ROUND, SIDE, SIZE_RANGE, SURFACE_LABELS, VENT,
                     DIVIDER_RANGE, INSIDE_CORNER_LABELS, OPENING_LABELS, LID_STYLE_LABELS, SHARP, MAX_COMPARTMENTS, PUSH_ON, SCREWED, SCREWS, SLIDING,
                     SNAP, THREADED, TRAY_TEMPLATE, WALL_RANGE, Hole, Project,
                     clamp_hole, compartment_depths, compartment_widths, default_project,
                     has_set_sizes, hole_limits, resized_sizes)
from .viewer import Viewer

COMMON_HOLES = [
    ("Common sizes…", None),
    ("M3 screw (3.4 mm)", 3.4),
    ("M4 screw (4.5 mm)", 4.5),
    ("Thin cable (5 mm)", 5.0),
    ("Cable with plug (8 mm)", 8.0),
    ("Thick cable / grommet (12 mm)", 12.0),
]
# Typical sizes; real parts vary, which the panel tells the user.
COMMON_RECTS = [
    ("Common sizes…", None),
    ("USB-C plug (12.5 × 7 mm)", (12.5, 7.0, 3.0)),       # width, height, corner rounding
    ("Micro-USB plug (11 × 8 mm)", (11.0, 8.0, 1.5)),
    ("USB-A plug (16 × 8.5 mm)", (16.0, 8.5, 1.0)),
    ("Slide switch (9 × 4 mm)", (9.0, 4.0, 0.5)),
    ("Rocker switch (19 × 13 mm)", (19.0, 13.0, 0.5)),
]
NEW_HOLE_ROUNDING = 1.0     # corner radius of new rectangles and vents
RECT_SIZE_RANGE = (1.0, 150.0)
TAB_SHAPE, TAB_HOLES, TAB_POSTS, TAB_LID, TAB_CHECK = range(5)
# Labels and tips for the two spacing fields of each custom board.
CUSTOM_HOLE_LABELS = {
    "custom": (("Holes apart (width)", "Holes apart (depth)"),
               ("Centre to centre, left to right, measured on your board",
                "Centre to centre, front to back, measured on your board")),
    "custom2": (("Holes apart (width)", "Holes apart (depth)"),
                ("Centre to centre, left to right, measured on your board",
                 "0 if the holes are in a straight line; otherwise how far apart they are "
                 "front to back (negative flips the diagonal)")),
    "custom1": (("Hole from middle (width)", "Hole from middle (depth)"),
                ("How far the hole is from the middle of the board, left (-) or right (+)",
                 "How far the hole is from the middle of the board, front (-) or back (+)")),
}
LID_STYLE_HINTS = {
    PUSH_ON: "A flat top with a lip that slides into the box and holds by friction.",
    SNAP: "Like the push-on lid, with small ridges on its lip that click into grooves "
          "inside the walls.",
    SLIDING: "A flat panel that slides into grooves at the top of the walls, from the front. "
             "Only for boxes.",
    SCREWED: "A flat lid held by a screw in each corner. The box gets a column in each corner "
             "for the screws to bite into.",
    THREADED: "A screw-on lid, like a jar. The top of the container becomes a narrower neck "
              "with a thread. Only for round containers.",
}
CHECK_TAB_TITLE = "5 Check && Export"


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


def int_spin(lo: int, hi: int) -> QSpinBox:
    box = QSpinBox()
    box.setRange(lo, hi)
    box.setAlignment(Qt.AlignmentFlag.AlignRight)
    return box


def scrolling(page: QWidget) -> QScrollArea:
    """Let a tab scroll when it is taller than the window."""
    area = QScrollArea()
    area.setWidget(page)
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return area


def hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #556;")
    return label


def _ordinal(n: int) -> str:
    return {1: "st", 2: "nd", 3: "rd"}.get(n if n < 20 else n % 10, "th")


def _set_count(p: Project, attr: str, count: int):
    """Change the number of compartments, keeping set sizes for the ones that stay."""
    d = p.dividers
    sizes = "widths" if attr == "across" else "depths"
    if getattr(d, sizes):
        span = p.inner_width if attr == "across" else p.inner_depth
        setattr(d, sizes, resized_sizes(span, count, d.thickness, getattr(d, sizes)))
    setattr(d, attr, count)


def set_quietly(widget, value):
    widget.blockSignals(True)
    if isinstance(widget, (QDoubleSpinBox, QSpinBox)):
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
        self.selected_mount_id: str | None = None
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
        self.tabs.addTab(scrolling(self._build_shape_tab()), "1 Shape")
        self.tabs.addTab(scrolling(self._build_holes_tab()), "2 Holes")
        self.tabs.addTab(scrolling(self._build_posts_tab()), "3 Posts")
        self.tabs.addTab(scrolling(self._build_lid_tab()), "4 Lid")
        self.tabs.addTab(scrolling(self._build_check_tab()), CHECK_TAB_TITLE)
        self.tabs.setMinimumWidth(420)
        self.tabs.setMaximumWidth(500)

        splitter = QSplitter()
        splitter.addWidget(self.viewer)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([800, 440])
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

        # A lambda, because triggered() would otherwise pass its 'checked' flag as `template`.
        new = action("New", QStyle.StandardPixmap.SP_FileIcon, lambda: self.new_project(),
                     QKeySequence.StandardKey.New, "Start a new design")
        menu = QMenu(self)
        for label, template in (("Box", BOX), ("Round container", CYLINDER),
                                ("Shallow tray with compartments", TRAY_TEMPLATE)):
            menu.addAction(label, lambda t=template: self.new_project(t))
        new.setMenu(menu)
        bar.widgetForAction(new).setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
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
        bar.addSeparator()
        self.about_action = action("About", QStyle.StandardPixmap.SP_MessageBoxInformation,
                                   self.show_about, tip="About 3Dn00b")
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
        self.template_combo = QComboBox()
        self.template_combo.addItem("Start from a template…", None)
        # Cases for boards first, then containers, with a line between.
        for keys in (templates.ELECTRONICS,
                     [k for k in templates.TEMPLATES if k not in templates.ELECTRONICS]):
            self.template_combo.insertSeparator(self.template_combo.count())
            for key in keys:
                t = templates.TEMPLATES[key]
                self.template_combo.addItem(t.label, key)
                self.template_combo.setItemData(self.template_combo.count() - 1, t.description,
                                                Qt.ItemDataRole.ToolTipRole)
        self.template_combo.setToolTip("Ready-made boxes, sized to fit: you can change "
                                       "everything afterwards.")
        self.template_combo.activated.connect(self._on_template)
        form.addRow("Template", self.template_combo)
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
        self.inside_corners = QComboBox()
        for key, text in INSIDE_CORNER_LABELS.items():
            self.inside_corners.addItem(text, key)
        self.inside_corners.setToolTip("Where the walls meet the floor (and each other). Rounded or "
                                       "angled corners are stronger and easier to clean.")
        self.inside_corners.activated.connect(
            lambda _: self.edit("Change inside corners", lambda p: setattr(
                p, "inside_corners", self.inside_corners.currentData())))
        self.inside_corner_size = spin(0.5, 20.0, step=0.5)
        self.inside_corner_size.setToolTip("How far the rounding or bevel reaches up the wall "
                                           "and across the floor")
        self.inside_corner_size.valueChanged.connect(
            lambda v: self.edit("Change inside corners",
                                lambda p: setattr(p, "inside_corner_size", v), merge="inside_size"))
        form.addRow("Inside corners", self.inside_corners)
        form.addRow("Corner size", self.inside_corner_size)
        self.shape_form = form
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

        layout.addWidget(QLabel("<b>Compartments</b>"))
        self.divider_box = QWidget()
        form = self.divider_form = QFormLayout(self.divider_box)
        form.setContentsMargins(0, 0, 0, 0)
        self.div_across = int_spin(1, MAX_COMPARTMENTS)
        self.div_deep = int_spin(1, MAX_COMPARTMENTS)
        self.div_across.setToolTip("How many compartments from left to right. 1 = no dividers.")
        self.div_deep.setToolTip("How many compartments from front to back. 1 = no dividers.")
        self.div_thickness = spin(*DIVIDER_RANGE, step=0.2, decimals=2)
        self.div_full = QCheckBox("Full height")
        self.div_height = spin(1.0, 300.0, step=1.0)
        self.div_height.setToolTip("Lower dividers make it easier to reach into the compartments")
        form.addRow("Left to right", self.div_across)
        self.width_sizes = self._compartment_sizes("widths", "width", "from the left")
        form.addRow(self.width_sizes.box)
        form.addRow("Front to back", self.div_deep)
        self.depth_sizes = self._compartment_sizes("depths", "depth", "from the front")
        form.addRow(self.depth_sizes.box)
        form.addRow("Divider thickness", self.div_thickness)
        form.addRow("Divider height", self.div_full)
        form.addRow("", self.div_height)
        self.div_across.valueChanged.connect(
            lambda v: self.edit("Change compartments", lambda p: _set_count(p, "across", v),
                                merge="div_across"))
        self.div_deep.valueChanged.connect(
            lambda v: self.edit("Change compartments", lambda p: _set_count(p, "deep", v),
                                merge="div_deep"))
        self.div_thickness.valueChanged.connect(
            lambda v: self.edit("Change divider thickness",
                                lambda p: setattr(p.dividers, "thickness", v), merge="div_t"))
        self.div_full.toggled.connect(self._on_divider_full)
        self.div_height.valueChanged.connect(
            lambda v: self.edit("Change divider height", lambda p: setattr(p.dividers, "height", v),
                                merge="div_h"))
        layout.addWidget(self.divider_box)
        self.divider_info = hint("")
        layout.addWidget(self.divider_info)
        layout.addStretch()
        return page

    def _build_holes_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(hint("Holes for cables, screws, USB ports, switches or air.\n"
                              "Tip: double-click a wall in the 3D view to put a hole right there, "
                              "and drag holes to move them."))
        row = QHBoxLayout()
        self.add_hole_button = QPushButton("+ Round hole")
        self.add_rect_button = QPushButton("+ Rectangle")
        self.add_vent_button = QPushButton("+ Air vent")
        self.add_vent_button.setToolTip("A row of slots that lets air in and out")
        for button in (self.add_hole_button, self.add_rect_button, self.add_vent_button):
            button.setMinimumHeight(34)
            row.addWidget(button)
        # Lambdas, because clicked() would otherwise pass its 'checked' flag as `surface`.
        self.add_hole_button.clicked.connect(lambda: self.add_hole())
        self.add_rect_button.clicked.connect(lambda: self.add_hole(kind=RECT))
        self.add_vent_button.clicked.connect(lambda: self.add_hole(kind=VENT))
        layout.addLayout(row)
        self.hole_list = QListWidget()
        self.hole_list.setMaximumHeight(150)
        self.hole_list.currentRowChanged.connect(self._on_hole_row_changed)
        layout.addWidget(self.hole_list)

        self.hole_box = QWidget()
        form = self.hole_form = QFormLayout(self.hole_box)
        form.setContentsMargins(0, 0, 0, 0)
        self.surface_combo = QComboBox()
        self.surface_combo.activated.connect(self._on_surface_changed)
        form.addRow("Where", self.surface_combo)
        self.kind_combo = QComboBox()
        for kind, label in HOLE_KIND_LABELS.items():
            self.kind_combo.addItem(label, kind)
        self.kind_combo.activated.connect(self._on_kind_changed)
        form.addRow("Shape", self.kind_combo)
        self.hole_diameter = spin(*HOLE_DIAMETER_RANGE, step=0.5)
        self.hole_diameter.valueChanged.connect(
            lambda v: self._edit_hole("Change hole size", "diameter", v))
        form.addRow("Diameter", self.hole_diameter)
        self.hole_width = spin(*RECT_SIZE_RANGE, step=0.5)
        self.hole_height = spin(*RECT_SIZE_RANGE, step=0.5)
        self.hole_width.valueChanged.connect(lambda v: self._edit_hole("Change hole size", "width", v))
        self.hole_height.valueChanged.connect(lambda v: self._edit_hole("Change hole size", "height", v))
        self.hole_width.setToolTip("Left to right (around, on a round wall)")
        self.hole_height.setToolTip("Up and down (front to back, on the bottom or lid)")
        form.addRow("Width", self.hole_width)
        form.addRow("Height", self.hole_height)
        self.vent_slot = spin(0.5, 20.0, step=0.5)
        self.vent_gap = spin(0.5, 20.0, step=0.5)
        self.vent_slot.valueChanged.connect(lambda v: self._edit_hole("Change slot width", "slot", v))
        self.vent_gap.valueChanged.connect(lambda v: self._edit_hole("Change gap", "gap", v))
        self.vent_gap.setToolTip("Plastic left between two slots")
        self.vent_direction = QComboBox()
        self.vent_direction.activated.connect(
            lambda _: self._edit_hole("Change slot direction", "slot_direction",
                                      self.vent_direction.currentData()))
        form.addRow("Slot width", self.vent_slot)
        form.addRow("Gap", self.vent_gap)
        form.addRow("Slots run", self.vent_direction)
        self.vent_info = hint("")
        form.addRow("", self.vent_info)
        self.common_sizes = QComboBox()
        self.common_sizes.activated.connect(self._on_common_size)
        self._common_kind = None
        form.addRow("", self.common_sizes)
        self.measure_hint = hint("Plugs and switches vary: measure yours and add a little room.")
        form.addRow("", self.measure_hint)
        self.hole_rounding = spin(0.0, 50.0, step=0.5)
        self.hole_rounding.setToolTip("Round corners are stronger: cracks start in sharp corners.\n"
                                      "0 = sharp corners.")
        self.hole_rounding.valueChanged.connect(
            lambda v: self._edit_hole("Change corner rounding", "rounding", v))
        form.addRow("Rounded corners", self.hole_rounding)
        self.hole_strengthen = QCheckBox("Thicker frame around it, inside")
        self.hole_strengthen.setToolTip(
            "Adds a frame on the inside of the wall around the opening, so a plug pushed in\n"
            "at an angle doesn't break the edge. Its sides slope at 45°, so it prints without support.")
        self.hole_strengthen.toggled.connect(
            lambda on: self._edit_hole("Strengthen hole edge", "strengthen", on))
        form.addRow("Strengthen", self.hole_strengthen)
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

    def _build_posts_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(hint("Screw posts hold a circuit board above the floor. Pick a board "
                              "to add all its posts at once, in the right pattern. "
                              "Drag the green outline in the 3D view to move them together. "
                              "Boards may overlap if one sits higher, on taller posts."))
        row = QHBoxLayout()
        self.board_combo = QComboBox()
        for key, board in mounts.BOARDS.items():
            self.board_combo.addItem(board.name, key)
        self.board_combo.setCurrentIndex(self.board_combo.findData("rpi-ab"))
        self.add_posts_button = QPushButton("+ Add")
        self.add_posts_button.setMinimumHeight(30)
        # A lambda, because clicked() would otherwise pass its 'checked' flag.
        self.add_posts_button.clicked.connect(lambda: self.add_mount(self.board_combo.currentData()))
        row.addWidget(self.board_combo, 1)
        row.addWidget(self.add_posts_button)
        layout.addLayout(row)
        self.mount_list = QListWidget()
        self.mount_list.setMaximumHeight(110)
        self.mount_list.currentRowChanged.connect(self._on_mount_row_changed)
        layout.addWidget(self.mount_list)

        self.mount_box = QWidget()
        form = self.mount_form = QFormLayout(self.mount_box)
        form.setContentsMargins(0, 0, 0, 0)
        self.screw_combo = QComboBox()
        for key, screw in mounts.SCREWS.items():
            self.screw_combo.addItem(f"{key} screw", key)
        self.screw_combo.activated.connect(
            lambda _: self._edit_mount("Change screw size", "screw", self.screw_combo.currentData()))
        form.addRow("Screw", self.screw_combo)
        self.post_length = spin(1.0, 100.0, step=0.5)
        self.post_length.setToolTip("How high the posts stand above the floor")
        self.post_length.valueChanged.connect(lambda v: self._edit_mount("Change post length", "length", v))
        form.addRow("Post length", self.post_length)
        self.parts_height = spin(0.0, 60.0, step=0.5)
        self.parts_height.setToolTip("Height of the tallest part on top of the board (sockets, pin "
                                     "headers). Another board can sit above it if there is this "
                                     "much room plus 1 mm.")
        self.parts_height.valueChanged.connect(
            lambda v: self._edit_mount("Change parts height", "parts_height", v))
        form.addRow("Parts on top", self.parts_height)
        self.board_w = spin(5.0, 300.0)
        self.board_d = spin(5.0, 300.0)
        # Negative values are allowed: for a 2-hole board they flip the diagonal, for a
        # 1-hole board they move the hole left or towards the front.
        self.spacing_x = spin(-300.0, 300.0, step=0.5)
        self.spacing_y = spin(-300.0, 300.0, step=0.5)
        for widget, attr, text in ((self.board_w, "board_width", "Board width"),
                                   (self.board_d, "board_depth", "Board depth"),
                                   (self.spacing_x, "spacing_x", "Holes apart (width)"),
                                   (self.spacing_y, "spacing_y", "Holes apart (depth)")):
            widget.valueChanged.connect(lambda v, a=attr: self._edit_mount("Change board", a, v))
            form.addRow(text, widget)
        self.spacing_x.setToolTip("Centre to centre, measured on your board")
        self.spacing_y.setToolTip("Centre to centre, measured on your board")
        self.mount_u = spin(-500, 500)
        self.mount_v = spin(-500, 500)
        self.mount_u.valueChanged.connect(lambda v: self._edit_mount("Move posts", "u", v))
        self.mount_v.valueChanged.connect(lambda v: self._edit_mount("Move posts", "v", v))
        form.addRow("Left / right", self.mount_u)
        form.addRow("Front / back", self.mount_v)
        buttons = QHBoxLayout()
        turn = QPushButton("Turn 90°")
        turn.setToolTip("Turn the board so its connectors face another wall")
        turn.clicked.connect(self._turn_mount)
        center = QPushButton("Centre it")
        center.clicked.connect(self._center_mount)
        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove_selected_mount)
        for button in (turn, center, remove):
            buttons.addWidget(button)
        form.addRow(buttons)
        layout.addWidget(self.mount_box)
        self.mount_info = hint("")
        layout.addWidget(self.mount_info)
        self.mount_problem = hint("")
        self.mount_problem.setStyleSheet("color: #b02020;")
        layout.addWidget(self.mount_problem)
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
        self.lid_box = QWidget()
        form = self.lid_form = QFormLayout(self.lid_box)
        form.setContentsMargins(0, 0, 0, 0)
        self.lid_style = QComboBox()
        for key, text in LID_STYLE_LABELS.items():
            self.lid_style.addItem(text, key)
        self.lid_style.activated.connect(
            lambda _: self.edit("Change lid type",
                                lambda p: setattr(p.lid, "style", self.lid_style.currentData())))
        form.addRow("Type", self.lid_style)
        self.lid_style_hint = hint("")
        form.addRow(self.lid_style_hint)
        self.lid_screw = QComboBox()
        for key in SCREWS:
            if key != "M1":
                self.lid_screw.addItem(f"{key} screws", key)
        self.lid_screw.activated.connect(
            lambda _: self.edit("Change lid screws",
                                lambda p: setattr(p.lid, "screw", self.lid_screw.currentData())))
        form.addRow("Screws", self.lid_screw)
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
        self.lid_opening = QComboBox()
        for key, text in OPENING_LABELS.items():
            self.lid_opening.addItem(text, key)
        self.lid_opening.setToolTip(
            "Makes a tight lid easier to open without prying at it:\n"
            "a tab sticks out of the lid at the front to push up with your thumb,\n"
            "a notch in the top of the front wall lets a finger get under the lid.")
        self.lid_opening.activated.connect(
            lambda _: self.edit("Change lid opening",
                                lambda p: setattr(p.lid, "opening", self.lid_opening.currentData())))
        form.addRow("Easy opening", self.lid_opening)
        layout.addWidget(self.lid_box)
        self.lid_tip = hint("")
        layout.addWidget(self.lid_tip)
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
        row = QHBoxLayout()
        row.addWidget(QLabel("File type"))
        self.format_combo = QComboBox()
        self.format_combo.addItem("STL (one file per part)", "stl")
        self.format_combo.addItem("3MF (all parts in one file)", "3mf")
        self.format_combo.setToolTip("STL works in every slicer. 3MF keeps the parts together, "
                                     "stores the size in millimetres and is smaller.")
        set_quietly(self.format_combo, self.settings.value("export_format", "stl"))
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        row.addWidget(self.format_combo, 1)
        layout.addLayout(row)
        self.export_button = QPushButton()
        self.export_button.setMinimumHeight(40)
        self.export_button.clicked.connect(self.export_stl)
        layout.addWidget(self.export_button)
        self._on_format_changed()
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
        if self.selected_mount_id and not self.project.mount(self.selected_mount_id):
            self.selected_mount_id = None
        self.refresh_controls()
        # Throttle (not debounce) so the preview keeps up while dragging or typing.
        if not self._rebuild_timer.isActive():
            self._rebuild_timer.start()
        self.viewer.set_hole_markers(self.project, self.selected_id, self._problem_holes())
        self.viewer.set_mount_markers(self.project, self.selected_mount_id, self._problem_mounts())
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
        set_quietly(self.inside_corners, p.inside_corners)
        set_quietly(self.inside_corner_size, p.inside_corner_size)
        self.shape_form.setRowVisible(self.inside_corner_size, p.inside_corners != SHARP)
        self._refresh_size_summary()
        self._refresh_dividers()

        set_quietly(self.lid_check, p.lid.enabled)
        self.lid_box.setEnabled(p.lid.enabled)
        style = p.lid.style
        set_quietly(self.lid_style, style)
        set_quietly(self.lid_screw, p.lid.screw)
        self.lid_form.setRowVisible(self.lid_screw, style == SCREWED)
        self.lid_form.setRowVisible(self.fit_combo, style != SCREWED)
        self.lid_form.setRowVisible(self.gap_spin, style != SCREWED)
        self.gap_spin.setToolTip("Extra room between the threads" if style == THREADED else
                                 "Space between the lid and the walls, on each side")
        self.lid_form.setRowVisible(self.lip_height, style in (PUSH_ON, SNAP))
        self.lid_form.setRowVisible(self.lid_opening, style in (PUSH_ON, SNAP))
        set_quietly(self.lid_opening, p.lid.opening)
        self.lid_style_hint.setText(LID_STYLE_HINTS[style])
        upside_down = "\n\nThe lid is exported upside down, which is the best way to print it."
        fit_tip = ("Normal fits most printers. If your lid ends up too tight, choose Loose and "
                   "print just the lid again; if it's too loose, choose Tight.")
        self.lid_tip.setText({
            PUSH_ON: fit_tip + upside_down,
            SNAP: fit_tip + " A looser fit also makes the click softer." + upside_down,
            SLIDING: fit_tip + "\n\nThe lid is printed flat. Slide it in from the front.",
            SCREWED: "Screws cut their own thread into the plastic. Tighten them gently, just "
                     "until the lid is snug." + upside_down,
            THREADED: fit_tip + " Screw it on clockwise; the thread rises 4 mm per turn."
                      + upside_down,
        }[style])
        set_quietly(self.fit_combo, p.lid.fit)
        set_quietly(self.gap_spin, p.lid.gap)
        self.gap_spin.setEnabled(p.lid.fit == "custom")
        set_quietly(self.lid_thickness, p.lid.thickness)
        set_quietly(self.lip_height, p.lid.lip_height)
        self.refresh_holes()
        self.refresh_mounts()

    def _compartment_sizes(self, attr: str, word: str, where: str) -> "SimpleNamespace":
        """A switch to set each compartment's size, with one box per compartment."""
        ui = SimpleNamespace(attr=attr, box=QWidget())
        layout = QVBoxLayout(ui.box)
        layout.setContentsMargins(0, 0, 0, 0)
        ui.custom = QCheckBox(f"Set each {word}")
        ui.custom.setToolTip(f"Give the compartments different {attr}, {where}; "
                             "the last one gets the rest of the room.")
        ui.custom.toggled.connect(lambda on: self._on_custom_sizes(attr, on))
        layout.addWidget(ui.custom)
        ui.form = QFormLayout()
        ui.form.setContentsMargins(16, 0, 0, 0)
        ui.spins = []
        for i in range(MAX_COMPARTMENTS - 1):
            box = spin(1.0, 1000.0, step=1.0)
            box.valueChanged.connect(
                lambda v, i=i: self.edit(f"Change compartment {word}",
                                         lambda p: getattr(p.dividers, attr).__setitem__(i, v),
                                         merge=f"div_{attr}{i}"))
            ui.form.addRow(f"{i + 1}{_ordinal(i + 1)} {where}", box)
            ui.spins.append(box)
        ui.rest = QLabel()
        ui.form.addRow("Last one", ui.rest)
        layout.addLayout(ui.form)
        return ui

    def _on_custom_sizes(self, attr: str, on: bool):
        def change(p):
            d = p.dividers
            count = d.across if attr == "widths" else d.deep
            span = p.inner_width if attr == "widths" else p.inner_depth
            setattr(d, attr, resized_sizes(span, count, d.thickness, []) if on else [])
        self.edit("Set compartment sizes" if on else "Make compartments the same size", change)

    def _refresh_sizes(self, ui, count: int, chosen: list[float], sizes: list[float]):
        custom = has_set_sizes(chosen, count)
        ui.box.setVisible(count > 1)
        set_quietly(ui.custom, custom)
        for i, box in enumerate(ui.spins):
            shown = custom and i < count - 1
            ui.form.setRowVisible(box, shown)
            if shown:
                set_quietly(box, chosen[i])
        ui.form.setRowVisible(ui.rest, custom)
        if custom:
            ui.rest.setText(f"the rest: {sizes[-1]:.1f} mm")
            ui.rest.setStyleSheet("" if sizes[-1] >= 3 else "color: #b02020;")

    def _on_template(self, index: int):
        key = self.template_combo.itemData(index)
        self.template_combo.setCurrentIndex(0)
        if key is None:
            return
        template = templates.TEMPLATES[key]
        fresh = template.build()
        self.selected_id = self.selected_mount_id = None
        self.edit(f"Start from “{template.label}”", lambda p: p.__dict__.update(fresh.__dict__))
        self.viewer._fitted_size = None          # show the whole new object
        self.rebuild()
        self.statusBar().showMessage(f"{template.label}: {template.description} "
                                     "Undo goes back to what you had.", 10000)

    def _refresh_dividers(self):
        p, d = self.project, self.project.dividers
        is_box = p.shape == BOX
        self.divider_box.setVisible(is_box)
        for widget, value in ((self.div_across, d.across), (self.div_deep, d.deep),
                              (self.div_thickness, d.thickness)):
            set_quietly(widget, value)
        set_quietly(self.div_full, d.height == 0)
        set_quietly(self.div_height, d.height if d.height > 0 else p.inner_height)
        self.divider_form.setRowVisible(self.div_height, d.height > 0)
        for widget in (self.div_thickness, self.div_full):
            widget.setEnabled(d.enabled)
        widths, depths = compartment_widths(p), compartment_depths(p)
        self._refresh_sizes(self.width_sizes, d.across, d.widths, widths)
        self._refresh_sizes(self.depth_sizes, d.deep, d.depths, depths)
        if not is_box:
            self.divider_info.setText("Dividers are available for boxes.")
        elif not d.enabled:
            self.divider_info.setText("Set more than 1 to split the box into compartments.")
        elif len(set(round(w, 1) for w in widths)) == len(set(round(x, 1) for x in depths)) == 1:
            count = d.across * d.deep
            self.divider_info.setText(f"{count} compartments, each {widths[0]:.1f} × "
                                      f"{depths[0]:.1f} mm inside.")
        else:
            def listed(sizes):
                sizes = [round(x, 1) for x in sizes]
                if len(set(sizes)) == 1:
                    return f"{sizes[0]:g} mm each"
                return " + ".join(f"{x:g}" for x in sizes) + " mm"
            self.divider_info.setText(f"{d.across * d.deep} compartments inside. "
                                      f"Widths from the left: {listed(widths)}. "
                                      f"Depths from the front: {listed(depths)}.")

    def _on_divider_full(self, full: bool):
        height = 0.0 if full else round(self.project.inner_height / 2, 1)
        self.edit("Change divider height", lambda p: setattr(p.dividers, "height", height))

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
            item = QListWidgetItem(f"{mark}Hole {i + 1} · {where} · {hole.size_label}")
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
        set_quietly(self.kind_combo, hole.kind)
        is_round, is_vent = hole.kind == ROUND, hole.kind == VENT
        is_rect = not is_round
        set_quietly(self.hole_diameter, hole.diameter)
        set_quietly(self.hole_width, hole.width)
        set_quietly(self.hole_height, hole.height)
        set_quietly(self.vent_slot, hole.slot)
        set_quietly(self.vent_gap, hole.gap)
        flat = hole.surface in (BOTTOM, LID)
        self.vent_direction.blockSignals(True)
        self.vent_direction.clear()
        self.vent_direction.addItem("Front to back" if flat else "Up and down", ALONG_V)
        self.vent_direction.addItem("Left to right" if flat else "Sideways", ALONG_U)
        self.vent_direction.blockSignals(False)
        set_quietly(self.vent_direction, hole.slot_direction)
        if is_vent:
            tip = "" if flat or hole.slot_direction == ALONG_V else (
                " Up-and-down slots print more cleanly in walls.")
            self.vent_info.setText(f"{hole.slot_count} slots fit in this vent.{tip}")
        self.hole_form.setRowVisible(self.hole_diameter, is_round)
        self.hole_form.setRowVisible(self.hole_width, is_rect)
        self.hole_form.setRowVisible(self.hole_height, is_rect)
        for widget in (self.vent_slot, self.vent_gap, self.vent_direction, self.vent_info):
            self.hole_form.setRowVisible(widget, is_vent)
        self.hole_form.setRowVisible(self.common_sizes, not is_vent)
        self.hole_form.setRowVisible(self.measure_hint, hole.kind == RECT)
        set_quietly(self.hole_rounding, hole.rounding)
        set_quietly(self.hole_strengthen, hole.strengthen)
        self.hole_form.setRowVisible(self.hole_rounding, is_rect)
        self.hole_form.setRowVisible(self.hole_strengthen, not flat)
        self.hole_height.setToolTip("Front to back" if hole.surface in (BOTTOM, LID) else "Up and down")
        if self._common_kind != hole.kind:
            self._common_kind = hole.kind
            self.common_sizes.clear()
            for text, value in (COMMON_RECTS if hole.kind == RECT else COMMON_HOLES):
                self.common_sizes.addItem(text, value)
        if hole.surface == SIDE:
            self.u_label.setText("Around")
            self.hole_u.setSuffix("°")
        else:
            self.u_label.setText("Left / right")
            self.hole_u.setSuffix(" mm")
        self.v_label.setText("Front / back" if hole.surface in (BOTTOM, LID) else "Up / down")
        limits = hole_limits(p, hole, MIN_EDGE)
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

    def refresh_mounts(self):
        p = self.project
        problems = self._problem_mounts()
        self.mount_list.blockSignals(True)
        self.mount_list.clear()
        current = -1
        for i, m in enumerate(p.mounts):
            mark = "⚠ " if m.id in problems else ""
            count = len(mounts.post_positions(m))
            self.mount_list.addItem(f"{mark}Posts {i + 1} · {mounts.label(m)} · {m.screw} × {count}")
            if m.id == self.selected_mount_id:
                current = i
        self.mount_list.setCurrentRow(current)
        self.mount_list.blockSignals(False)
        m = p.mount(self.selected_mount_id) if self.selected_mount_id else None
        self.mount_box.setEnabled(m is not None)
        if m is None:
            self.mount_info.setText("" if p.mounts else "No posts yet.")
            self.mount_problem.setText("")
            for widget in (self.board_w, self.board_d, self.spacing_x, self.spacing_y):
                self.mount_form.setRowVisible(widget, False)
            return
        set_quietly(self.screw_combo, m.screw)
        is_custom = mounts.is_custom(m)
        labels, tips = CUSTOM_HOLE_LABELS.get(m.board, CUSTOM_HOLE_LABELS["custom"])
        for widget, text, tip in zip((self.spacing_x, self.spacing_y), labels, tips):
            self.mount_form.labelForField(widget).setText(text)
            widget.setToolTip(tip)
        self.mount_form.setRowVisible(self.parts_height, mounts.board_size(m) is not None)
        for widget, value in ((self.post_length, m.length), (self.parts_height, mounts.parts_height(m)),
                              (self.board_w, m.board_width),
                              (self.board_d, m.board_depth), (self.spacing_x, m.spacing_x),
                              (self.spacing_y, m.spacing_y)):
            set_quietly(widget, value)
        for widget in (self.board_w, self.board_d, self.spacing_x, self.spacing_y):
            self.mount_form.setRowVisible(widget, is_custom)
        for widget, value in ((self.mount_u, m.u), (self.mount_v, m.v)):
            widget.blockSignals(True)
            widget.setRange(-p.inner_width / 2 if widget is self.mount_u else -p.inner_depth / 2,
                            p.inner_width / 2 if widget is self.mount_u else p.inner_depth / 2)
            widget.setRange(min(widget.minimum(), value), max(widget.maximum(), value))
            widget.blockSignals(False)
            set_quietly(widget, value)
        info = f"Use {m.screw} screws up to {mounts.max_screw_length(m):g} mm long."
        if mounts.board_size(m):
            info += (" The board rests on top of the posts; the green outline shows where it "
                     "goes (it isn't printed).")
        if mounts.board_size(m):
            info += (f" Another board can sit above this one if there is "
                     f"{mounts.room_above(m):g} mm of room.")
        if m.screw != mounts.BOARDS[m.board].screw and not (m.board == "single" or is_custom):
            info += f" This board is usually fixed with {mounts.BOARDS[m.board].screw} screws."
        self.mount_info.setText(info)
        msgs = [i.message for i in self.issues if i.mount_id == m.id and i.level != validation.INFO]
        self.mount_problem.setText("\n".join("⚠ " + msg for msg in msgs))

    def _problem_mounts(self) -> set:
        return {i.mount_id for i in self.issues if i.mount_id and i.level != validation.INFO}

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
        self.viewer.set_mount_markers(p, self.selected_mount_id, self._problem_mounts())
        self._refresh_issues()
        self.refresh_holes()
        self.refresh_mounts()

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
                                 "Parts are placed flat side down, ready to print.")
        self.tabs.setTabText(TAB_CHECK, CHECK_TAB_TITLE + (" ✖" if errors else " ⚠" if warnings else ""))
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
        line = f"{holes} hole{'s' * (holes != 1)}"
        posts = sum(len(mounts.post_positions(m)) for m in self.project.mounts)
        if posts:
            line += f", {posts} screw post{'s' * (posts != 1)}"
        lines.append(line)
        self.parts_summary.setText("<br>".join(lines))

    # ------------------------------------------------------------------
    # Hole actions
    # ------------------------------------------------------------------
    def select_hole(self, hole_id: str | None):
        self.selected_id = hole_id
        if hole_id is not None and self.selected_mount_id is not None:
            self.select_mount(None)
        self.refresh_holes()
        self.viewer.set_hole_markers(self.project, self.selected_id, self._problem_holes())

    def select_mount(self, mount_id: str | None):
        self.selected_mount_id = mount_id
        if mount_id is not None and self.selected_id is not None:
            self.select_hole(None)
        self.refresh_mounts()
        self.viewer.set_mount_markers(self.project, self.selected_mount_id, self._problem_mounts())

    def add_hole(self, surface: str | None = None, u: float = 0.0, v: float = 0.0,
                 kind: str = ROUND):
        p = self.project
        if surface is None:
            current = p.hole(self.selected_id) if self.selected_id else None
            surface = current.surface if current else (FRONT if p.shape == BOX else SIDE)
        if kind in (RECT, VENT):
            size = (picking.fitting_rect if kind == RECT else picking.fitting_vent)(p, surface)
            hole = Hole(surface=surface, kind=kind, u=u, v=v, rounding=NEW_HOLE_ROUNDING,
                        strengthen=kind == RECT)
            if size:
                hole.width, hole.height = size
        else:
            size = picking.fitting_diameter(p, surface)
            hole = Hole(surface=surface, diameter=size or 0.0, u=u, v=v)
        if size is None:
            self.statusBar().showMessage(f"There's no room for a hole on the "
                                         f"{SURFACE_LABELS[surface].lower()}.", 5000)
            return
        # Start somewhere valid: keep the clicked spot if it is safe, else the nearest safe one.
        pos = clamp_hole(p, hole) or clamp_hole(p, hole, MIN_EDGE)
        if pos:
            hole.u, hole.v = pos
        self.edit("Add hole", lambda proj: proj.holes.append(copy.deepcopy(hole)))
        self.tabs.setCurrentIndex(TAB_HOLES)
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
        hole_id = self.selected_id
        if value is None or hole_id is None:
            return
        if isinstance(value, tuple):
            def change(p):
                h = p.hole(hole_id)
                h.width, h.height, h.rounding = value
            self.edit("Change hole size", change)
        else:
            self._edit_hole("Change hole size", "diameter", value)

    def _on_kind_changed(self, _index):
        hole_id, kind = self.selected_id, self.kind_combo.currentData()
        if hole_id is None:
            return

        def change(p):
            h = p.hole(hole_id)
            if h.kind == kind:
                return
            if h.kind == ROUND and h.rounding == 0:
                h.rounding = NEW_HOLE_ROUNDING
            h.kind = kind
            if kind == VENT:
                size = picking.fitting_vent(p, h.surface)
                if size:
                    h.width, h.height = size
            # Keep it on the surface after the size changes.
            pos = clamp_hole(p, h) or clamp_hole(p, h, MIN_EDGE)
            if pos:
                h.u, h.v = pos
        self.edit("Change hole shape", change)

    def _on_hole_row_changed(self, row):
        holes = self.project.holes
        self.select_hole(holes[row].id if 0 <= row < len(holes) else None)

    # ---- screw posts -----------------------------------------------------
    def add_mount(self, board: str):
        m = mounts.new_mount(self.project, board)
        if mounts.clamp_mount(self.project, m, m.u, m.v) is None:
            self.statusBar().showMessage(f"The {mounts.label(m)} doesn't fit in this box. "
                                         "It's added anyway so you can see why.", 6000)
        self.edit("Add posts", lambda p: p.mounts.append(copy.deepcopy(m)))
        self.tabs.setCurrentIndex(TAB_POSTS)
        self.select_mount(m.id)

    def remove_selected_mount(self):
        mount_id = self.selected_mount_id
        if mount_id is None or not self.project.mount(mount_id):
            return
        self.selected_mount_id = None
        self.edit("Remove posts", lambda p: p.mounts.remove(p.mount(mount_id)))

    def _edit_mount(self, label, attr, value):
        mount_id = self.selected_mount_id
        if mount_id is None:
            return
        self.edit(label, lambda p: setattr(p.mount(mount_id), attr, value),
                  merge=f"{mount_id}:{attr}")

    def _turn_mount(self):
        mount_id = self.selected_mount_id
        if mount_id is None:
            return

        def change(p):
            m = p.mount(mount_id)
            m.rotation = (m.rotation + 90) % 360
            pos = mounts.clamp_mount(p, m, m.u, m.v)
            if pos:
                m.u, m.v = pos
        self.edit("Turn posts", change)

    def _center_mount(self):
        mount_id = self.selected_mount_id
        if mount_id is None:
            return

        def change(p):
            m = p.mount(mount_id)
            pos = mounts.clamp_mount(p, m, 0.0, 0.0)
            m.u, m.v = pos if pos else (0.0, 0.0)
        self.edit("Centre posts", change)

    def _on_mount_row_changed(self, row):
        items = self.project.mounts
        self.select_mount(items[row].id if 0 <= row < len(items) else None)

    # ---- dragging holes in the 3D view (called by the Viewer) ----------
    def _hole_under(self, origin, direction, mesh_distance):
        return picking.hole_under_ray(self.project, origin, direction, mesh_distance,
                                      self.viewer.lid_offset, self.viewer.show_lid)

    def hole_at(self, origin, direction, mesh_distance) -> bool:
        return (self._hole_under(origin, direction, mesh_distance) is not None
                or picking.mount_under_ray(self.project, origin, direction, mesh_distance) is not None)

    def drag_begin(self, origin, direction, mesh_distance) -> bool:
        hole = self._hole_under(origin, direction, mesh_distance)
        if hole is None:
            return self._mount_drag_begin(origin, direction, mesh_distance)
        self.tabs.setCurrentIndex(TAB_HOLES)
        self.select_hole(hole.id)
        hit = picking.surface_hit(self.project, hole.surface, origin, direction,
                                  self.viewer.lid_offset)
        if hit is None:
            return True
        # Remember where on the hole it was grabbed, so it doesn't jump. Each drag
        # gets its own undo merge key, so one drag = one undo step.
        self._drag_count += 1
        self._drag = {"id": hole.id, "du": hole.u - hit[1], "dv": hole.v - hit[2],
                      "key": f"drag:{self._drag_count}", "type": "hole"}
        return True

    def _mount_drag_begin(self, origin, direction, mesh_distance) -> bool:
        m = picking.mount_under_ray(self.project, origin, direction, mesh_distance)
        if m is None:
            return False
        self.tabs.setCurrentIndex(TAB_POSTS)
        self.select_mount(m.id)
        hit = picking.mount_plane_hit(self.project, m, origin, direction)
        self._drag_count += 1
        self._drag = {"id": m.id, "du": m.u - hit[1], "dv": m.v - hit[2],
                      "key": f"drag:{self._drag_count}", "type": "mount"}
        return True

    def _mount_drag_move(self, origin, direction):
        drag = self._drag
        m = self.project.mount(drag["id"])
        if m is None:
            return
        hit = picking.mount_plane_hit(self.project, m, origin, direction)
        if hit is None:
            return
        u, v = hit[1] + drag["du"], hit[2] + drag["dv"]
        notes = []
        if abs(u) <= picking.SNAP_MM:
            u = 0.0
            notes.append("centred left to right")
        if abs(v) <= picking.SNAP_MM:
            v = 0.0
            notes.append("centred front to back")
        # Keep the whole board inside the box with room around it.
        pos = mounts.clamp_mount(self.project, m, u, v)
        if pos is None:
            return
        if abs(pos[0] - u) > 0.05 or abs(pos[1] - v) > 0.05:
            notes = ["kept away from the walls"]
        mount_id = m.id
        self.edit("Move posts", lambda p: _set_position(p.mount(mount_id), pos), merge=drag["key"])
        name = validation.mount_name(self.project, self.project.mount(mount_id))
        self.statusBar().showMessage(f"{name}: {', '.join(notes)}" if notes else name, 1500)

    def drag_move(self, origin, direction):
        drag = self._drag
        if drag and drag["type"] == "mount":
            self._mount_drag_move(origin, direction)
            return
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
        elif issue and issue.mount_id:
            self.select_mount(issue.mount_id)

    def _apply_fix(self):
        issue = self._issue_at(self.issue_list.currentRow())
        if issue and issue.fix and issue.mount_id:
            mount_id, pos = issue.mount_id, issue.fix
            self.edit("Fix post position", lambda p: _set_position(p.mount(mount_id), pos))
            self.statusBar().showMessage("Posts moved. Press Ctrl+Z to undo.", 5000)
            return
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

    def new_project(self, template: str = BOX):
        if not self._confirm_discard():
            return
        self._load(default_project(template), None)

    def _load(self, project: Project, path: Path | None):
        self.project = project
        self.path = path
        self.selected_id = None
        self.selected_mount_id = None
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

    def _on_format_changed(self, _index=None):
        fmt = self.format_combo.currentData()
        self.settings.setValue("export_format", fmt)
        self.export_button.setText(f"Export for printing ({fmt.upper()})…")

    def export_stl(self):
        """Export the printable parts in the chosen file type (STL or 3MF)."""
        if validation.has_errors(self.issues):
            self.tabs.setCurrentIndex(TAB_CHECK)
            return
        fmt = self.format_combo.currentData()
        folder = QFileDialog.getExistingDirectory(
            self, f"Choose a folder for the {fmt.upper()} file{'s' * (fmt == 'stl')}", self._last_dir())
        if not folder:
            return
        stem = project_io.safe_file_stem(self.project.name)
        if fmt == "3mf":
            existing = [Path(folder) / f"{stem}.3mf"]
        else:
            existing = [Path(folder) / f"{stem}-{part}.stl" for part in ("body", "lid")]
        existing = [f for f in existing if f.exists()]
        if existing and QMessageBox.question(
                self, APP_NAME, "Replace these files?\n" + "\n".join(f.name for f in existing)
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            if fmt == "3mf":
                files = [project_io.export_3mf_file(self.project, folder)]
            else:
                files = project_io.export_stl_files(self.project, folder)
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Couldn't export:\n{exc}")
            return
        self.settings.setValue("last_dir", folder)
        QMessageBox.information(self, APP_NAME, "Saved for printing:\n\n"
                                + "\n".join(f.name for f in files)
                                + f"\n\nin {folder}\n\nOpen these in your slicer to print them.")

    def about_text(self) -> str:
        return (f"<h3>{APP_NAME} {__version__}</h3>"
                "<p>A simple designer for 3D printing, made for beginners. Pick a box or a "
                "round container, type the sizes, add holes, vents, compartments, screw "
                "posts and a lid, and export files for your slicer. No CAD knowledge "
                "needed: the app checks your design and explains problems in plain words.</p>"
                "<p>Free software under the GNU GPL version 3.</p>"
                "<p><br>Vibe-coded by TheSpork, 2026</p>")

    def show_about(self):
        box = QMessageBox(self)
        box.setWindowTitle(f"About {APP_NAME}")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(self.about_text())
        box.setIconPixmap(QApplication.windowIcon().pixmap(64, 64))
        box.exec()

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
