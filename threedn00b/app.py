"""Application entry point: `3dn00b [project.3dn00b]` or `python -m threedn00b`."""

from __future__ import annotations

import ctypes.util
import os
import sys
from pathlib import Path

MISSING_XCB_CURSOR = """\
3Dn00b can't open its window: a system library Qt needs (libxcb-cursor) is missing.

Install it, then start 3Dn00b again:

  Debian / Ubuntu / Mint:  sudo apt install libxcb-cursor0
  Fedora:                  sudo dnf install xcb-util-cursor
  Arch / Manjaro:          sudo pacman -S xcb-util-cursor
  openSUSE:                sudo zypper install libxcb-cursor0
"""


def check_display_libraries() -> str | None:
    """Return a friendly error message if Qt will fail to open a window.

    Since Qt 6.5 the X11 ("xcb") backend needs libxcb-cursor, which many
    desktops don't install by default. Qt's own error message is cryptic,
    so detect it up front. On Wayland we can simply use the Wayland backend.
    """
    if not sys.platform.startswith("linux"):
        return None
    platform = os.environ.get("QT_QPA_PLATFORM", "")
    if platform and not platform.startswith("xcb"):
        return None
    if ctypes.util.find_library("xcb-cursor"):
        return None
    if not platform and os.environ.get("WAYLAND_DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "wayland"
        return None
    return MISSING_XCB_CURSOR


BROKEN_PYSIDE = """\
3Dn00b can't start safely: PySide6 {version} has a bug that crashes the app on
Python {python} (it shows up while dragging holes).

Fix it by reinstalling 3Dn00b's requirements, which picks a working version:

  .venv/bin/pip install -e .
"""


def check_pyside_version() -> str | None:
    """PySide6 6.12.0 drops a reference to None on every OpenGL buffer upload.

    Python 3.12+ never frees None, so only older Pythons crash.
    """
    if sys.version_info >= (3, 12):
        return None
    import PySide6
    if PySide6.__version__ == "6.12.0":
        return BROKEN_PYSIDE.format(version=PySide6.__version__,
                                    python=".".join(map(str, sys.version_info[:2])))
    return None


def install_error_handler() -> None:
    """Show unexpected errors in a dialog instead of letting Qt abort the app."""
    import traceback

    def handler(exc_type, exc, tb):
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        print(details, file=sys.stderr)
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is None:
            return
        box = QMessageBox(QMessageBox.Icon.Warning, "3Dn00b",
                          "Something went wrong. Your last change may not have been applied.\n\n"
                          "You can keep working. Please save your project, and report this "
                          "if it happens again.")
        box.setDetailedText(details)
        box.exec()

    sys.excepthook = handler


def main() -> int:
    problem = check_display_libraries() or check_pyside_version()
    if problem:
        print(problem, file=sys.stderr)
        return 1

    from PySide6.QtWidgets import QApplication

    from . import APP_NAME, __version__
    from .gui.viewer import prepare_opengl

    prepare_opengl()
    install_error_handler()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("3dn00b")
    from PySide6.QtGui import QIcon
    icon = QIcon.fromTheme("3dn00b")
    app.setWindowIcon(icon if not icon.isNull() else
                      QIcon(str(Path(__file__).parent / "resources" / "3dn00b.svg")))

    from .gui.main_window import main_window_app
    if "--smoke-test" in sys.argv:
        return smoke_test(app)
    return main_window_app(sys.argv)


def smoke_test(app) -> int:
    """Check an installation works: window, 3D view, geometry and export. Used by packaging."""
    import tempfile

    from PySide6.QtCore import QTimer

    from . import project_io
    from .gui.main_window import MainWindow, release_window
    from .model import FRONT, default_project

    result = {"code": 1}
    window = MainWindow()
    window.show()

    def check():
        try:
            window.lid_check.setChecked(True)
            window.add_hole(FRONT)
            window.rebuild()
            image = window.viewer.grabFramebuffer()
            assert not image.isNull() and image.width() > 100, "the 3D view didn't draw"
            from .gui.welcome import PAGES, capture_tour
            shots = capture_tour()
            assert len(shots) == len(PAGES) and not shots[0].isNull(), "no welcome tour pictures"
            with tempfile.TemporaryDirectory() as tmp:
                stl = project_io.export_stl_files(window.project, tmp)
                three_mf = project_io.export_3mf_file(window.project, tmp)
                assert all(f.stat().st_size > 1000 for f in stl + [three_mf]), "export failed"
                fit = project_io.export_fit_test(window.project, tmp)
                assert len(fit) == 3, "fit test export failed"     # openings, top, lid ring
                project_io.save_project(default_project(), Path(tmp) / "test.3dn00b")
            from .text import outline
            assert outline("Æøå 3D", 8) is not None, "the font for text is missing"
            print("3Dn00b smoke test: OK")
            result["code"] = 0
        except Exception as exc:          # report and fail, but don't hang
            print(f"3Dn00b smoke test FAILED: {exc!r}", file=sys.stderr)
        window.undo_stack.setClean()
        app.quit()

    QTimer.singleShot(500, check)
    app.exec()
    release_window(window)
    return result["code"]


if __name__ == "__main__":
    sys.exit(main())
