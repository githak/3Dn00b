"""The app's look: one dark colour scheme, a style sheet and line icons.

Everything visual is defined here, so the rest of the GUI only names things
(object names like "card" or "primary") and never hard-codes colours.
"""

from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path
from string import Template

from PySide6.QtCore import QByteArray, QSize, QStandardPaths, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QWidget

# ---- colours ---------------------------------------------------------------------
# Cool, slightly blue greys from darkest (window chrome) to lightest (hover), one blue
# accent, and green / amber / red only for status.
BG0 = "#111318"          # window background behind everything
BG1 = "#161920"          # header, rail, status bar
BG2 = "#1c2028"          # cards
BG3 = "#232833"          # inputs, buttons
BG4 = "#2b313e"          # hover
BG5 = "#343b4a"          # pressed
BORDER = "#2a303c"
BORDER_STRONG = "#3a4252"
TEXT = "#e6e9ef"
MUTED = "#98a2b3"
FAINT = "#5f687a"
ACCENT = "#4c8dff"
ACCENT_HOVER = "#6a9fff"
ACCENT_PRESSED = "#3a78e6"
ACCENT_TEXT = "#9cc0ff"
ACCENT_SOFT = "rgba(76, 141, 255, 0.16)"
SUCCESS = "#35c48d"
WARNING = "#f2b54a"
DANGER = "#ff5f6d"

LEVEL_COLORS = {"ok": SUCCESS, "warning": WARNING, "error": DANGER, "info": ACCENT_TEXT}


def rgba(color: str, alpha: float) -> str:
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def gl_color(color: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    """A colour as the (r, g, b, a) floats the 3D view uses."""
    c = QColor(color)
    return c.redF(), c.greenF(), c.blueF(), alpha


# ---- icons -----------------------------------------------------------------------
# 24 x 24 line drawings, stroked in the colour asked for.
ICONS = {
    "new": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
           '<path d="M14 3v5h5"/><path d="M12 11.5v6M9 14.5h6"/>',
    "open": '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v7a2.5 2.5 0 0 1'
            '-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5z"/>',
    "save": '<path d="M5 3h11l3 3v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/>'
            '<path d="M7.5 3v4.5h7V3"/><rect x="7" y="13" width="10" height="8" rx="1"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "export": '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 20.5h14"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.6h.01"/>',
    "shape": '<path d="M12 2.8 20.5 7.4v9.2L12 21.2l-8.5-4.6V7.4z"/>'
             '<path d="M3.5 7.4 12 12l8.5-4.6M12 12v9.2"/>',
    "holes": '<rect x="3" y="3" width="18" height="18" rx="3.5"/><circle cx="9" cy="10" r="2.6"/>'
             '<rect x="12.5" y="13" width="5.5" height="4" rx="1"/>',
    "posts": '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" '
             'height="6" rx="1"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    "lid": '<rect x="2.5" y="5" width="19" height="4" rx="1.2"/>'
           '<path d="M4.5 9v9a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V9"/><path d="M10 13h4"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12.3 2.7 2.7L16.2 9"/>',
    "warning": '<path d="M10.3 4 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 4a2 2 0 0 '
               '0-3.4 0z"/><path d="M12 9.5v4"/><path d="M12 17h.01"/>',
    "error": '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>',
    "box": '<path d="M12 2.8 20.5 7.4v9.2L12 21.2l-8.5-4.6V7.4z"/>'
           '<path d="M3.5 7.4 12 12l8.5-4.6M12 12v9.2"/>',
    "cylinder": '<ellipse cx="12" cy="5.8" rx="7.5" ry="2.8"/>'
                '<path d="M4.5 5.8v12.4c0 1.55 3.36 2.8 7.5 2.8s7.5-1.25 7.5-2.8V5.8"/>',
    "round-hole": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5"/>',
    "rect-hole": '<rect x="3" y="6" width="18" height="12" rx="2"/><rect x="7.5" y="10" '
                 'width="9" height="4" rx="1"/>',
    "vent": '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M8 8.5v7M12 8.5v7M16 8.5v7"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "trash": '<path d="M4 7h16"/><path d="M10 11v6M14 11v6"/><path d="M6 7l1 12.5A1.5 1.5 0 0 0 '
             '8.5 21h7a1.5 1.5 0 0 0 1.5-1.5L18 7"/><path d="M9 7V4.5A1.5 1.5 0 0 1 10.5 3h3A1.5 '
             '1.5 0 0 1 15 4.5V7"/>',
    "center": '<circle cx="12" cy="12" r="7.5"/><circle cx="12" cy="12" r="1.5"/>'
              '<path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
    "rotate": '<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1L20.5 8.5"/><path d="M20.5 3.5v5h-5"/>',
    "fit": '<path d="M3 8V5a2 2 0 0 1 2-2h3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M8 '
           '21H5a2 2 0 0 1-2-2v-3"/>',
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "template": '<rect x="3" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="3" '
                'width="7.5" height="7.5" rx="1.5"/><rect x="3" y="13.5" width="7.5" height="7.5" '
                'rx="1.5"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5"/>',
    "chevron-down": '<path d="m6 9.5 6 6 6-6"/>',
    "chevron-up": '<path d="m6 14.5 6-6 6 6"/>',
    "tick": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
}


def _svg(name: str, color: str, stroke: float = 1.8) -> bytes:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
            f'stroke-linejoin="round">{ICONS[name]}</svg>').encode()


@lru_cache(maxsize=None)
def pixmap(name: str, color: str = TEXT, size: int = 20, stroke: float = 1.8) -> QPixmap:
    ratio = 2.0          # sharp on high-resolution screens too
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    QSvgRenderer(QByteArray(_svg(name, color, stroke))).render(painter)
    painter.end()
    pm.setDevicePixelRatio(ratio)
    return pm


@lru_cache(maxsize=None)
def icon(name: str, color: str = TEXT, checked: str | None = None) -> QIcon:
    """An icon in `color` (greyed out when disabled, `checked` colour when checked)."""
    result = QIcon()
    for size in (16, 20, 24, 32):
        result.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
        result.addPixmap(pixmap(name, FAINT, size), QIcon.Mode.Disabled, QIcon.State.Off)
        if checked:
            for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
                result.addPixmap(pixmap(name, checked, size), mode, QIcon.State.On)
    return result


# ---- small images the style sheet points to ------------------------------------------

def _asset_files() -> dict[str, Path]:
    """Write the arrows, tick and switch images to a cache folder (the style sheet needs
    files) and return their paths."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    folder = Path(base or tempfile.gettempdir()) / "theme"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        folder = Path(tempfile.mkdtemp(prefix="3dn00b-theme-"))
    files = {
        "down": _svg("chevron-down", MUTED, 2.2),
        "up": _svg("chevron-up", MUTED, 2.2),
        "down-off": _svg("chevron-down", FAINT, 2.2),
        "tick": _svg("tick", "#ffffff", 3.0),
        "switch-off": (f'<svg xmlns="http://www.w3.org/2000/svg" width="36" height="20">'
                       f'<rect x="0.5" y="0.5" width="35" height="19" rx="9.5" fill="{BG4}" '
                       f'stroke="{BORDER_STRONG}"/><circle cx="10" cy="10" r="7" fill="{MUTED}"/>'
                       f'</svg>').encode(),
        "switch-on": (f'<svg xmlns="http://www.w3.org/2000/svg" width="36" height="20">'
                      f'<rect x="0.5" y="0.5" width="35" height="19" rx="9.5" fill="{ACCENT}" '
                      f'stroke="{ACCENT}"/><circle cx="26" cy="10" r="7" fill="#ffffff"/>'
                      f'</svg>').encode(),
    }
    paths = {}
    for key, data in files.items():
        path = folder / f"{key}.svg"
        try:
            if not path.exists() or path.read_bytes() != data:
                path.write_bytes(data)
        except OSError:
            pass
        paths[key] = path
    return paths


# ---- the style sheet ---------------------------------------------------------------

STYLE = Template("""
* { outline: 0; }
QDialogButtonBox { dialogbuttonbox-buttons-have-icons: 0; }
QDialogButtonBox QPushButton { min-width: 76px; }
QWidget { color: $TEXT; font-size: 10pt; }
QMainWindow, QWidget#central, QDialog, QMessageBox { background: $BG0; }
QToolTip { background: $BG3; color: $TEXT; border: 1px solid $BORDER_STRONG; padding: 6px 8px;
           border-radius: 6px; }

/* ---- header bar ---- */
QToolBar#header { background: $BG1; border: none; border-bottom: 1px solid $BORDER;
                  padding: 6px 12px; spacing: 2px; }
QToolBar#header::separator { background: $BORDER; width: 1px; margin: 9px 8px; }
QToolBar#header QToolButton { background: transparent; border: 1px solid transparent;
                              border-radius: 8px; padding: 6px 10px; color: $TEXT; }
QToolBar#header QToolButton:hover { background: $BG3; }
QToolBar#header QToolButton:pressed { background: $BG4; }
QToolBar#header QToolButton:disabled { color: $FAINT; }
QToolBar#header QToolButton[popupMode="1"] { padding-right: 22px; }
QToolBar#header QToolButton::menu-button { border: none; width: 18px; border-top-right-radius: 8px;
                                           border-bottom-right-radius: 8px; }
QToolBar#header QToolButton::menu-button:hover { background: $BG4; }
QToolBar#header QToolButton::menu-arrow { image: url("$down"); width: 12px; height: 12px; }
QToolBar#header QToolButton#primary { background: $ACCENT; border-color: $ACCENT; color: #ffffff;
                                      font-weight: 600; padding: 7px 16px; }
QToolBar#header QToolButton#primary:hover { background: $ACCENT_HOVER; border-color: $ACCENT_HOVER; }
QToolBar#header QToolButton#primary:pressed { background: $ACCENT_PRESSED; }
QToolBar#header QToolButton#primary:disabled { background: $BG3; border-color: $BORDER; color: $FAINT; }
QLabel#brand { font-size: 12pt; font-weight: 700; padding: 0 6px 0 2px; }
QLabel#docTitle { color: $MUTED; }

/* ---- step rail ---- */
QWidget#rail { background: $BG1; border-right: 1px solid $BORDER; }
QToolButton#railButton { background: transparent; border: none; border-radius: 10px;
                         padding: 9px 2px 7px 2px; color: $MUTED; font-size: 8.5pt; font-weight: 600; }
QToolButton#railButton:hover { background: $BG3; color: $TEXT; }
QToolButton#railButton:checked { background: $ACCENT_SOFT; color: $ACCENT_TEXT; }

/* ---- side panel ---- */
QWidget#panel { background: $BG0; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QLabel#pageTitle { font-size: 15pt; font-weight: 600; }
QLabel#pageSubtitle { color: $MUTED; }
QFrame#card { background: $BG2; border: 1px solid $BORDER; border-radius: 12px; }
QLabel#cardTitle { color: $MUTED; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }
QLabel#hint { color: $MUTED; }
QLabel#error { color: $DANGER; }
QLabel#error[level="ok"] { color: $MUTED; }
QLabel#error[level="warning"] { color: $WARNING; }
QLabel#summary { background: $BG1; border: 1px solid $BORDER; border-radius: 8px; padding: 9px 11px;
                 color: $TEXT; }
QLabel#callout { background: $ACCENT_SOFT_BG; border: 1px solid $ACCENT_SOFT_BORDER; border-radius: 8px;
                 padding: 9px 11px; color: $TEXT; }
QLabel#statusTitle { font-size: 13pt; font-weight: 600; }
QLabel#statusTitle[level="ok"] { color: $SUCCESS; }
QLabel#statusTitle[level="warning"] { color: $WARNING; }
QLabel#statusTitle[level="error"] { color: $DANGER; }

/* ---- inputs ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: $BG3; border: 1px solid $BORDER; border-radius: 7px; padding: 5px 9px;
    min-height: 20px; selection-background-color: $ACCENT; selection-color: #ffffff; }
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover { border-color: $BORDER_STRONG; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QComboBox:on {
    border-color: $ACCENT; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    color: $FAINT; background: $BG2; border-color: $BORDER; }
QSpinBox, QDoubleSpinBox { padding-right: 24px; }
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right; width: 22px; border: none;
    border-left: 1px solid $BORDER; border-top-right-radius: 7px; background: transparent; }
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; border: none;
    border-left: 1px solid $BORDER; border-bottom-right-radius: 7px; background: transparent; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: $BG4; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("$up"); width: 11px; height: 11px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("$down"); width: 11px; height: 11px; }
QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off, QDoubleSpinBox::up-arrow:disabled,
QDoubleSpinBox::up-arrow:off { image: none; }
QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off, QDoubleSpinBox::down-arrow:disabled,
QDoubleSpinBox::down-arrow:off { image: none; }
QComboBox { padding-right: 28px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 26px;
                       border: none; }
QComboBox::down-arrow { image: url("$down"); width: 12px; height: 12px; }
QComboBox::down-arrow:disabled { image: url("$down_off"); }
QComboBox QAbstractItemView { background: $BG2; border: 1px solid $BORDER_STRONG; border-radius: 8px;
                              padding: 4px; outline: 0; selection-background-color: $ACCENT_SOFT;
                              selection-color: $TEXT; }
QComboBox QAbstractItemView::item { padding: 6px 8px; min-height: 20px; border-radius: 5px; }
QComboBox QAbstractItemView::item:selected, QComboBox QAbstractItemView::item:hover {
    background: $ACCENT_SOFT; }
QComboBox QAbstractItemView::item:disabled { color: $FAINT; }

/* ---- buttons ---- */
QPushButton { background: $BG3; border: 1px solid $BORDER; border-radius: 8px; padding: 7px 14px;
              color: $TEXT; font-weight: 500; }
QPushButton:hover { background: $BG4; border-color: $BORDER_STRONG; }
QPushButton:pressed { background: $BG5; }
QPushButton:disabled { color: $FAINT; background: $BG2; border-color: $BORDER; }
QPushButton#primary { background: $ACCENT; border-color: $ACCENT; color: #ffffff; font-weight: 600; }
QPushButton#primary:hover { background: $ACCENT_HOVER; border-color: $ACCENT_HOVER; }
QPushButton#primary:pressed { background: $ACCENT_PRESSED; }
QPushButton#primary:disabled { background: $BG3; border-color: $BORDER; color: $FAINT; }
QPushButton#danger { background: transparent; color: $DANGER; border-color: $DANGER_BORDER; }
QPushButton#danger:hover { background: $DANGER_SOFT; }
QPushButton#danger:disabled { color: $FAINT; border-color: $BORDER; }
QPushButton#tile { background: $BG3; border: 1px solid $BORDER; border-radius: 10px; padding: 10px 8px;
                   font-weight: 600; }
QPushButton#tile:hover { background: $BG4; border-color: $BORDER_STRONG; }
QPushButton#tile:checked { background: $ACCENT_SOFT; border-color: $ACCENT; color: $ACCENT_TEXT; }
QPushButton#statusChip { background: transparent; border: 1px solid $BORDER; border-radius: 11px;
                         padding: 3px 12px; font-weight: 600; color: $MUTED; }
QPushButton#statusChip[level="ok"] { color: $SUCCESS; border-color: $SUCCESS_BORDER;
                                      background: $SUCCESS_SOFT; }
QPushButton#statusChip[level="warning"] { color: $WARNING; border-color: $WARNING_BORDER;
                                           background: $WARNING_SOFT; }
QPushButton#statusChip[level="error"] { color: $DANGER; border-color: $DANGER_BORDER;
                                         background: $DANGER_SOFT; }

/* ---- check boxes, switches and segmented choices ---- */
QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid $BORDER_STRONG;
                       background: $BG3; }
QCheckBox::indicator:hover { border-color: $ACCENT; }
QCheckBox::indicator:checked { background: $ACCENT; border-color: $ACCENT; image: url("$tick"); }
QCheckBox::indicator:disabled { background: $BG2; border-color: $BORDER; }
QCheckBox::indicator:checked:disabled { background: $BG5; border-color: $BG5; }
QCheckBox:disabled { color: $FAINT; }
QCheckBox#switch { font-weight: 600; spacing: 10px; }
QCheckBox#switch::indicator { width: 36px; height: 20px; border: none; border-radius: 10px;
                              background: transparent; image: url("$switch_off"); }
QCheckBox#switch::indicator:checked { image: url("$switch_on"); background: transparent; }
QPushButton#segmentLeft, QPushButton#segmentRight { background: $BG3; border: 1px solid $BORDER;
                                                    padding: 7px 12px; font-weight: 500; color: $MUTED; }
QPushButton#segmentLeft { border-radius: 0; border-top-left-radius: 8px; border-bottom-left-radius: 8px; }
QPushButton#segmentRight { border-radius: 0; border-top-right-radius: 8px;
                           border-bottom-right-radius: 8px; border-left: none; }
QPushButton#segmentLeft:hover, QPushButton#segmentRight:hover { background: $BG4; color: $TEXT; }
QPushButton#segmentLeft:checked, QPushButton#segmentRight:checked {
    background: $ACCENT_SOFT; color: $ACCENT_TEXT; border-color: $ACCENT; }
QPushButton#segmentRight:checked { border-left: 1px solid $ACCENT; }

/* ---- lists ---- */
QListWidget { background: $BG1; border: 1px solid $BORDER; border-radius: 8px; padding: 4px; }
QListWidget::item { padding: 7px 8px; border-radius: 6px; margin: 1px 0; color: $TEXT; }
QListWidget::item:hover { background: $BG3; }
QListWidget::item:selected { background: $ACCENT_SOFT; color: $TEXT; }

/* ---- scroll bars ---- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px 2px 2px 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0 2px 2px 2px; }
QScrollBar::handle { background: $BG4; border-radius: 4px; }
QScrollBar::handle:vertical { min-height: 32px; }
QScrollBar::handle:horizontal { min-width: 32px; }
QScrollBar::handle:hover { background: $BORDER_STRONG; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

/* ---- menus, status bar, splitter ---- */
QMenu { background: $BG2; border: 1px solid $BORDER_STRONG; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 7px 22px 7px 12px; border-radius: 5px; }
QMenu::item:selected { background: $ACCENT_SOFT; }
QMenu::separator { height: 1px; background: $BORDER; margin: 4px 6px; }
QStatusBar { background: $BG1; border-top: 1px solid $BORDER; color: $MUTED; min-height: 32px;
             padding: 0 10px; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: $MUTED; padding: 0 4px; }
QSplitter::handle { background: $BORDER; }
QSplitter::handle:hover { background: $ACCENT; }
QTabWidget::pane { border: none; }

/* ---- floating controls over the 3D view ---- */
QFrame#viewOverlay { background: $OVERLAY; border: 1px solid $BORDER; border-radius: 10px; }
QFrame#viewOverlay QToolButton { background: transparent; border: none; border-radius: 7px;
                                 padding: 5px 9px; color: $MUTED; font-weight: 600; }
QFrame#viewOverlay QToolButton:hover { background: $BG4; color: $TEXT; }
QFrame#viewOverlay QToolButton:checked { background: $ACCENT_SOFT; color: $ACCENT_TEXT; }
QFrame#viewOverlay QToolButton:disabled { color: $FAINT; }
QFrame#overlayDivider { background: $BORDER; }
QLabel#viewHint { color: $MUTED; background: $OVERLAY; border: 1px solid $BORDER; border-radius: 8px;
                  padding: 5px 10px; font-size: 9pt; }
""")


def style_sheet() -> str:
    files = {key.replace("-", "_"): path.as_posix() for key, path in _asset_files().items()}
    values = {name: value for name, value in globals().items() if name.isupper()
              and isinstance(value, str)}
    values.update(
        ACCENT_SOFT_BG=rgba(ACCENT, 0.10), ACCENT_SOFT_BORDER=rgba(ACCENT, 0.28),
        SUCCESS_SOFT=rgba(SUCCESS, 0.10), SUCCESS_BORDER=rgba(SUCCESS, 0.40),
        WARNING_SOFT=rgba(WARNING, 0.10), WARNING_BORDER=rgba(WARNING, 0.40),
        DANGER_SOFT=rgba(DANGER, 0.12), DANGER_BORDER=rgba(DANGER, 0.40),
        OVERLAY=rgba(BG1, 0.88), **files)
    return STYLE.substitute(values)


def palette() -> QPalette:
    """Colours for anything the style sheet doesn't reach (dialogs, native parts)."""
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: BG1, QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: BG3, QPalette.ColorRole.AlternateBase: BG2,
        QPalette.ColorRole.Text: TEXT, QPalette.ColorRole.Button: BG3,
        QPalette.ColorRole.ButtonText: TEXT, QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Highlight: ACCENT, QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: BG3, QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: FAINT, QPalette.ColorRole.Link: ACCENT_TEXT,
        QPalette.ColorRole.Light: BG4, QPalette.ColorRole.Midlight: BG3,
        QPalette.ColorRole.Mid: BORDER, QPalette.ColorRole.Dark: BG0,
        QPalette.ColorRole.Shadow: "#000000",
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(FAINT))
    return p


def apply(app: QApplication) -> None:
    """Give the whole application the dark look (once)."""
    if app.property("n00bTheme"):
        return
    app.setStyle("Fusion")
    app.setPalette(palette())
    font = app.font()
    if font.pointSizeF() < 10:
        font.setPointSizeF(10)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)
    app.setStyleSheet(style_sheet())
    app.setProperty("n00bTheme", True)


def repolish(widget: QWidget) -> None:
    """Re-apply the style sheet after changing an object name or a property it uses."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_level(widget: QWidget, level: str) -> None:
    """Colour a status widget: level is "ok", "warning", "error" or ""."""
    if widget.property("level") != level:
        widget.setProperty("level", level)
        repolish(widget)


ICON_SIZE = QSize(18, 18)
