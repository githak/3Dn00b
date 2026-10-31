"""The welcome tour: what 3Dn00b is (and isn't), then its parts, shown on screenshots.

The screenshots are taken live from a hidden example window, so they always
match the app as it is, and the part each page talks about is highlighted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, templates
from . import theme

SHOT_SIZE = QSize(1280, 800)     # size of the example window the screenshots come from


@dataclass(frozen=True)
class TourPage:
    title: str
    text: str
    step: int                                  # which step (page of the panel) to show
    targets: Callable[[object], list]          # window -> the widgets to highlight
    prepare: Callable[[object], None] = lambda window: None
    show_step: bool = True                     # also highlight the step's button in the rail

    def highlights(self, window) -> list:
        """The widgets to highlight: the page's own, plus its step in the rail."""
        widgets = list(self.targets(window))
        if self.show_step:
            widgets.insert(0, window.rail_buttons[self.step])
        return widgets


def _select_first_hole(window) -> None:
    if window.project.holes:
        window.select_hole(window.project.holes[0].id)


def _select_first_board(window) -> None:
    if window.project.mounts:
        window.select_mount(window.project.mounts[0].id)


def _select_nothing(window) -> None:
    window.select_hole(None)
    window.select_mount(None)


PAGES = (
    TourPage("Work through the steps",
             "The steps down the left side take you from an idea to a file you can print: "
             "Shape, Holes, Posts, Lid and Export. Click a step to open it, or press Ctrl+1 "
             "to Ctrl+5.", 0, lambda w: [w.rail], show_step=False),
    TourPage("Start with a shape or a template",
             "Pick a box or a round container, or start from a ready-made template: cases for "
             "Raspberry Pi and Arduino boards, storage boxes, trays and more. Then type the sizes "
             "in millimetres; the app shows both the outside size and the room inside.",
             0, lambda w: [w.start_card, w.size_card]),
    TourPage("Add holes, openings and vents",
             "Round holes for cables and screws, rectangles for USB plugs and switches, and air "
             "vents. Double-click a wall in the 3D view to put a hole right there, and drag it "
             "to move it. Common sizes are built in.",
             1, lambda w: [w.add_holes_card, w.hole_card], _select_first_hole),
    TourPage("Screw posts for circuit boards",
             "Choose a board and all its posts appear in the right pattern, ready for the screws "
             "to cut their own thread. An outline shows where the board will sit; drag it in the "
             "3D view to move the posts together.",
             2, lambda w: [w.add_posts_card, w.mount_card], _select_first_board),
    TourPage("Choose a lid",
             "Push-on, snap-on, sliding, screwed down or threaded. For tight lids, add a tab or a "
             "finger notch so they're easy to open.", 3, lambda w: [w.lid_card]),
    TourPage("See it in 3D",
             "The preview updates as you type. Drag to turn it, scroll to zoom and middle-drag "
             "to move it. The buttons in the corner show it from the front, the top or the side, "
             "and hide the lid.", 0, lambda w: [w.viewer], _select_nothing, show_step=False),
    TourPage("Check and export",
             "The app checks your design while you work and explains any problem in plain words. "
             "The status in the corner says when it's ready to print, and Export saves STL or 3MF "
             "files for your slicer.\n\nYou can take this tour again from the ? button at the top "
             "right, or by pressing F1.",
             4, lambda w: [w.check_card, w.status_badge, w.export_tool_button]),
)

HOW = (("shape", "Choose", "A box, a round container or a ready-made template."),
       ("holes", "Customise", "Sizes, holes, compartments, screw posts and a lid."),
       ("export", "Print", "Export a file and open it in your slicer."))
IS = ("A simple designer for things to 3D print: boxes, cases and round containers.",
      "Type sizes in millimetres, add holes, compartments, screw posts and a lid.",
      "Ready-made templates for Raspberry Pi and Arduino cases and everyday storage.",
      "It checks your design and explains problems in plain words.",
      "It saves STL or 3MF files that any slicer can print.")
IS_NOT = ("Not a CAD program: no sketches, constraints or free-form modelling.",
          "It can't open or edit STL files made elsewhere.",
          "It doesn't slice or talk to your printer: use your slicer for that "
          "(PrusaSlicer, Cura, OrcaSlicer…).")


# ---- screenshots -------------------------------------------------------------------

def visible_rect(widget: QWidget, window: QWidget) -> QRect:
    """The part of `widget` you can see, in `window` coordinates (scrolled-away parts cut off)."""
    rect = QRect(QPoint(0, 0), widget.size())
    current = widget
    while current is not window and current.parentWidget() is not None:
        rect.translate(current.pos())
        current = current.parentWidget()
        rect = rect.intersected(current.rect())
    return rect


def highlight(shot: QPixmap, rects: list[QRect]) -> QPixmap:
    """Darken the screenshot except the given areas, and outline those in the accent colour."""
    out = QPixmap(shot)
    size = out.deviceIndependentSize()
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    spots = QPainterPath()
    for rect in rects:
        if not rect.isEmpty():
            spots.addRoundedRect(QRectF(rect).adjusted(-5, -5, 5, 5), 12, 12)
    spots = spots.simplified()
    everything = QPainterPath()
    everything.addRect(QRectF(0, 0, size.width(), size.height()))
    painter.fillPath(everything.subtracted(spots), QColor(4, 6, 9, 170))
    glow = QColor(theme.ACCENT)
    glow.setAlpha(80)
    painter.strokePath(spots, QPen(glow, 10))
    painter.strokePath(spots, QPen(QColor(theme.ACCENT), 3))
    painter.end()
    return out


def capture_tour(pages=PAGES) -> list[QPixmap]:
    """Screenshots of an example design (a Raspberry Pi case), one per tour page."""
    from .main_window import MainWindow, release_window
    demo = MainWindow(templates.from_template("pi"))
    demo.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)   # never seen
    demo.resize(SHOT_SIZE)
    demo.show()
    app = QApplication.instance()
    shots = []
    try:
        for page in pages:
            demo.tabs.setCurrentIndex(page.step)
            page.prepare(demo)
            for _ in range(3):
                app.processEvents()
            rects = [visible_rect(w, demo) for w in page.highlights(demo) if w.isVisible()]
            shots.append(highlight(demo.grab(), rects))
    finally:
        demo.undo_stack.setClean()
        demo.hide()
        release_window(demo)
    return shots


# ---- the dialog ----------------------------------------------------------------------

class Dots(QWidget):
    """Small dots showing which page of the tour you're on."""

    def __init__(self, count: int):
        super().__init__()
        self.count, self.current = count, 0
        self.setFixedSize(count * 14, 14)

    def set_current(self, index: int):
        self.current = index
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(self.count):
            painter.setBrush(QColor(theme.ACCENT if i == self.current else theme.BG5))
            radius = 4 if i == self.current else 3
            painter.drawEllipse(QPoint(i * 14 + 7, 7), radius, radius)


class WelcomeDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, show_at_startup: bool = False,
                 shots: list[QPixmap] | None = None):
        super().__init__(parent)
        self.setObjectName("welcome")
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setModal(True)
        self.resize(940, 700)
        self._shots = shots
        self._images: list[QLabel] = []

        self.pages = QStackedWidget()
        self.pages.addWidget(self._intro_page())
        for page in PAGES:
            self.pages.addWidget(self._tour_page(page))

        self.dots = Dots(self.pages.count())
        self.startup_check = QCheckBox("Show this welcome when 3Dn00b starts")
        self.startup_check.setChecked(show_at_startup)
        self.skip_button = QPushButton("Skip")
        self.skip_button.setObjectName("flat")
        self.skip_button.clicked.connect(self.accept)
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(lambda: self.go(self.pages.currentIndex() - 1))
        self.next_button = QPushButton()
        self.next_button.setObjectName("primary")
        self.next_button.setDefault(True)
        self.next_button.clicked.connect(self._next)
        for button in (self.skip_button, self.back_button, self.next_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumWidth(96)

        footer = QFrame()
        footer.setObjectName("welcomeFooter")
        row = QHBoxLayout(footer)
        row.setContentsMargins(24, 14, 24, 14)
        row.addWidget(self.startup_check)
        row.addStretch()
        row.addWidget(self.dots)
        row.addStretch()
        row.addWidget(self.skip_button)
        row.addWidget(self.back_button)
        row.addWidget(self.next_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.pages, 1)
        layout.addWidget(footer)
        self.go(0)

    # ---- pages ----
    def _intro_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(36, 32, 36, 20)
        layout.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(16)
        logo = QLabel()
        from .main_window import app_icon
        logo.setPixmap(app_icon().pixmap(64, 64))
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(4)
        title = QLabel(f"Welcome to {APP_NAME}")
        title.setObjectName("welcomeTitle")
        subtitle = QLabel("Design boxes, cases and containers for your 3D printer: no CAD "
                          "experience needed.")
        subtitle.setObjectName("welcomeText")
        subtitle.setWordWrap(True)
        words.addWidget(title)
        words.addWidget(subtitle)
        head.addLayout(words, 1)
        layout.addLayout(head)
        layout.addSpacing(6)
        cards = QHBoxLayout()
        cards.setSpacing(14)
        cards.addWidget(self._list_card("What it is", IS, "check", theme.SUCCESS))
        cards.addWidget(self._list_card("What it isn't", IS_NOT, "error", theme.MUTED))
        layout.addLayout(cards)
        layout.addSpacing(8)
        how = QLabel("HOW IT WORKS")
        how.setObjectName("cardTitle")
        layout.addWidget(how)
        steps = QHBoxLayout()
        steps.setSpacing(14)
        for number, (icon_name, title, text) in enumerate(HOW, 1):
            steps.addWidget(self._how_card(number, icon_name, title, text))
        layout.addLayout(steps)
        layout.addStretch()
        note = QLabel("The next pages show the parts of the app in a short tour. It takes "
                      "about a minute.")
        note.setObjectName("welcomeText")
        note.setWordWrap(True)
        layout.addWidget(note)
        return page

    def _how_card(self, number: int, icon_name: str, title: str, text: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(theme.pixmap(icon_name, theme.ACCENT_TEXT, 28))
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(3)
        heading = QLabel(f"{number}. {title}")
        heading.setStyleSheet("font-weight: 600;")
        body = QLabel(text)
        body.setObjectName("welcomeText")
        body.setWordWrap(True)
        words.addWidget(heading)
        words.addWidget(body)
        layout.addLayout(words, 1)
        return frame

    def _list_card(self, title: str, lines, icon_name: str, color: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(10)
        heading = QLabel(title.upper())
        heading.setObjectName("cardTitle")
        layout.addWidget(heading)
        for line in lines:
            row = QHBoxLayout()
            row.setSpacing(10)
            mark = QLabel()
            mark.setPixmap(theme.pixmap(icon_name, color, 18))
            row.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
            text = QLabel(line)
            text.setWordWrap(True)
            row.addWidget(text, 1)
            layout.addLayout(row)
        layout.addStretch()
        return frame

    def _tour_page(self, page: TourPage) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(36, 28, 36, 16)
        layout.setSpacing(10)
        step = QLabel(f"STEP {PAGES.index(page) + 1} OF {len(PAGES)}")
        step.setObjectName("cardTitle")
        title = QLabel(page.title)
        title.setObjectName("welcomeTitle")
        text = QLabel(page.text)
        text.setObjectName("welcomeText")
        text.setWordWrap(True)
        image = QLabel("Preparing the pictures…")
        image.setObjectName("welcomeShot")
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image.setMinimumHeight(300)
        # Ignored: the picture is scaled to the space, never the other way round.
        image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._images.append(image)
        for item in (step, title, text):
            layout.addWidget(item)
        layout.addSpacing(4)
        layout.addWidget(image, 1)
        return widget

    # ---- navigation ----
    def go(self, index: int):
        index = max(0, min(index, self.pages.count() - 1))
        if index > 0 and self._shots is None:
            self._load_shots()
        self.pages.setCurrentIndex(index)
        self.dots.set_current(index)
        last = index == self.pages.count() - 1
        self.back_button.setVisible(index > 0)
        self.skip_button.setVisible(not last)
        self.next_button.setText("Start designing" if last else
                                 "Take the tour" if index == 0 else "Next")
        self._show_shot(index)

    def _next(self):
        if self.pages.currentIndex() == self.pages.count() - 1:
            self.accept()
        else:
            self.go(self.pages.currentIndex() + 1)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Right:
            self._next()
        elif event.key() == Qt.Key.Key_Left:
            self.go(self.pages.currentIndex() - 1)
        else:
            super().keyPressEvent(event)

    def show_at_startup(self) -> bool:
        return self.startup_check.isChecked()

    # ---- screenshots ----
    def _load_shots(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._shots = capture_tour()
        except Exception:          # the tour still works without pictures
            self._shots = []
        finally:
            QApplication.restoreOverrideCursor()

    def _show_shot(self, index: int):
        if index == 0 or not self._shots or index - 1 >= len(self._shots):
            return
        label = self._images[index - 1]
        area = label.size()
        if area.width() < 50:
            area = QSize(860, 480)
        label.setPixmap(self._shots[index - 1].scaled(
            area, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._show_shot(self.pages.currentIndex())
