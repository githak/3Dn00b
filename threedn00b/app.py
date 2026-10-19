"""Application entry point: `3dn00b [project.3dn00b]` or `python -m threedn00b`."""

from __future__ import annotations

import ctypes.util
import os
import sys

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
    problem = check_display_libraries()
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

    from .gui.main_window import main_window_app
    return main_window_app(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
