"""Start 3Dn00b from its Debian package, using the libraries bundled for this Python."""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
VERSION = f"py{sys.version_info[0]}.{sys.version_info[1]}"
VENDOR = os.path.join(ROOT, "vendor")

if not os.path.isdir(os.path.join(VENDOR, VERSION)):
    supported = sorted(d[2:] for d in os.listdir(VENDOR) if d.startswith("py"))
    sys.exit(f"3Dn00b works with Python {', '.join(supported)}, but this computer runs Python "
             f"{sys.version_info[0]}.{sys.version_info[1]}.\n"
             "Please install a 3Dn00b package made for your version of Linux.")

sys.path[:0] = [os.path.join(ROOT, "app"), os.path.join(VENDOR, VERSION),
                os.path.join(VENDOR, "common")]

from threedn00b.app import main  # noqa: E402

sys.exit(main())
