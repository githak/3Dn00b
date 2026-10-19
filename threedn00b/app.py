"""Application entry point: `3dn00b [project.3dn00b]` or `python -m threedn00b`."""

from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from . import APP_NAME, __version__
    from .gui.viewer import prepare_opengl

    prepare_opengl()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("3dn00b")

    from .gui.main_window import main_window_app
    return main_window_app(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
