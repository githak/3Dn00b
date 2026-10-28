"""Ready-made starting points: cases for common boards and everyday containers.

Each template is built from the board catalogue in mounts.py, so the box is
sized around the board, the posts match its holes, and the openings sit in
front of its sockets. Socket positions come from the manufacturers' drawings
(measured from the board's lower-left corner, like the holes); the openings
are made a little bigger than the plugs, since plugs vary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import mounts
from .model import (BACK, BOX, CYLINDER, FRONT, INSIDE, LEFT, LID, RECT, RIGHT,
                    SLIDING, SNAP, THREADED, VENT, Dividers, Hole, Mount, Project,
                    default_project)


@dataclass(frozen=True)
class Template:
    label: str
    description: str
    build: Callable[[], Project]


def _box(name: str, width: float, depth: float, height: float, corner: float = 3.0) -> Project:
    """A box measured inside, with a push-on lid that has a tab and a finger notch."""
    p = Project(shape=BOX, name=name, size_mode=INSIDE, width=width, depth=depth, height=height,
                wall=2.0, bottom=2.0, corner_radius=corner)
    p.lid.enabled, p.lid.lip_height, p.lid.opening = True, 4.0, "both"
    return p


def _board(p: Project, board: str, length: float, u: float, v: float, rotation: int = 0) -> Mount:
    m = mounts.new_mount(p, board)
    m.length, m.u, m.v, m.rotation = length, u, v, rotation
    p.mounts.append(m)
    return m


def _floor_point(m: Mount, x: float, y: float) -> tuple[float, float]:
    """A point measured from the board's lower-left corner, on the floor of the box."""
    w, d = mounts.board_size(m)
    return mounts._to_floor(m, x - w / 2, y - d / 2)


def _opening(p: Project, surface: str, along: float, z_low: float, z_high: float,
             width: float, rounding: float = 1.0) -> Hole:
    """A rectangular opening in a wall, centred at `along` (x for the front and back
    walls, y for the side walls) and reaching from z_low to z_high."""
    u = {FRONT: along, BACK: -along, LEFT: -along, RIGHT: along}[surface]
    hole = Hole(surface=surface, kind=RECT, width=width, height=z_high - z_low, u=u,
                v=(z_low + z_high) / 2 - p.outer_height / 2, rounding=rounding)
    p.holes.append(hole)
    return hole


def _top(p: Project, m: Mount) -> float:
    """Height (z) of the top of the board."""
    return mounts.board_bottom(p, m) + mounts.BOARD_THICKNESS


# ---- boards -------------------------------------------------------------------

def pi_case() -> Project:
    # 85 x 56 mm. Room around it: the USB and network sockets stick out about
    # 2 mm on the right, the SD card on the left.
    p = _box("Raspberry Pi case", 85 + 2.0 + 2.5, 56 + 3.0, 32.0)
    m = _board(p, "rpi-ab", 6.0, u=(2.0 - 2.5) / 2, v=0.0)
    top, low = _top(p, m), mounts.board_bottom(p, m)
    # Power, HDMI and audio along the front edge (Pi 3, 4 and 5 all fit in one opening).
    x0, _ = _floor_point(m, 3.5, 0)
    x1, _ = _floor_point(m, 59.0, 0)
    _opening(p, FRONT, (x0 + x1) / 2, top - 2.5, top + 7.5, x1 - x0, rounding=2.0)
    # USB and network sockets on the right edge.
    _, y0 = _floor_point(m, 85, 1.5)
    _, y1 = _floor_point(m, 85, 54.5)
    _opening(p, RIGHT, (y0 + y1) / 2, top - 1.0, top + 16.5, y1 - y0)
    # The micro SD card, under the board on the left edge.
    _, y = _floor_point(m, 0, 28.0)
    _opening(p, LEFT, y, low - 3.5, low + 1.0, 16.0, rounding=2.0)
    # Air out over the processor.
    p.holes.append(Hole(surface=LID, kind=VENT, width=40.0, height=16.0, rounding=1.0))
    return p


def pi_zero_case() -> Project:
    # 65 x 30 mm; the micro SD card sticks out a little on the left.
    p = _box("Raspberry Pi Zero case", 65 + 2.5 + 1.5, 30 + 3.0, 18.0, corner=2.5)
    m = _board(p, "rpi-zero", 4.0, u=(2.5 - 1.5) / 2, v=0.0)
    _zero_openings(p, m)
    p.holes.append(Hole(surface=LID, kind=VENT, width=30.0, height=10.0, rounding=1.0))
    return p


def _zero_openings(p: Project, m: Mount, camera: bool = True) -> None:
    """Mini HDMI, USB and power along the long edge; SD card and camera at the ends."""
    top = _top(p, m)
    sockets = ((12.4, 12.0, top - 3.0, top + 5.0),      # mini HDMI
               (41.4, 9.0, top - 2.5, top + 4.0),       # micro USB (data)
               (54.0, 9.0, top - 2.5, top + 4.0))       # micro USB (power)
    for x, width, z0, z1 in sockets:
        _opening(p, *_facing(p, m, x, 0), z0, z1, width, rounding=1.5)
    _opening(p, *_facing(p, m, 0, 16.9), top - 1.5, top + 3.0, 14.0)      # SD card
    if camera:
        _opening(p, *_facing(p, m, 65, 15.0), top - 0.5, top + 2.5, 18.0)  # camera cable


def _facing(p: Project, m: Mount, x: float, y: float) -> tuple[str, float]:
    """The wall a point on the board's edge faces, and where along that wall it is."""
    w, d = mounts.board_size(m)
    # Which way the board's edge faces, before the board is turned.
    nx, ny = (-1, 0) if x == 0 else (1, 0) if x == w else (0, -1) if y == 0 else (0, 1)
    ox, oy = mounts._to_floor(m, nx, ny)
    cx, cy = mounts._to_floor(m, 0.0, 0.0)
    dx, dy = round(ox - cx), round(oy - cy)
    fx, fy = _floor_point(m, x, y)
    if dx:
        return (RIGHT if dx > 0 else LEFT), fy
    return (BACK if dy > 0 else FRONT), fx


def pi_zero_stack() -> Project:
    # Two boards crossing like a "+": the lower one left to right, the upper one front
    # to back on taller posts. Cables reach their sockets through the openings.
    p = _box("Two stacked Pi Zero 2 W", 70.0, 70.0, 24.0, corner=3.0)
    lower = _board(p, "rpi-zero", 4.0, u=0.0, v=0.0)
    # The upper board needs room for the lower board's parts, plus a little air.
    room = mounts.BOARD_THICKNESS + mounts.parts_height(lower) + mounts.STACK_AIR
    upper = _board(p, "rpi-zero", lower.length + room + 0.4, u=0.0, v=0.0, rotation=90)
    _zero_openings(p, lower, camera=False)
    _zero_openings(p, upper, camera=False)
    p.holes.append(Hole(surface=LID, kind=VENT, width=24.0, height=24.0, rounding=1.0))
    return p


def arduino_case() -> Project:
    # 68.6 x 53.3 mm. The USB socket sticks out 6.4 mm on the left, so the board
    # sits further in to let it drop into place.
    p = _box("Arduino Uno case", 68.6 + 6.5 + 1.9, 53.3 + 3.7, 26.0)
    m = _board(p, "uno", 5.0, u=(6.5 - 1.9) / 2, v=0.0)
    top = _top(p, m)
    _, y = _floor_point(m, 0, 37.8)
    _opening(p, LEFT, y, top - 0.5, top + 12.0, 13.0)               # USB B
    _, y = _floor_point(m, 0, 7.6)
    _opening(p, LEFT, y, top - 0.5, top + 11.5, 10.5, rounding=3.0)  # power jack
    return p


# ---- everyday containers ---------------------------------------------------------

def storage_box() -> Project:
    p = _box("Storage box", 100.0, 70.0, 50.0, corner=4.0)
    return p


def screw_sorter() -> Project:
    p = _box("Screw sorter", 140.0, 80.0, 25.0, corner=4.0)
    p.lid.style = SNAP
    p.wall = p.bottom = 1.6
    p.inside_corners, p.inside_corner_size = "rounded", 3.0
    # Short, medium and long screws, in two rows.
    p.dividers = Dividers(across=3, deep=2, thickness=1.6, widths=[30.0, 45.0])
    return p


def battery_box() -> Project:
    # 8 AA cells standing up, each in its own 15.5 mm square.
    cell, t = 15.5, 1.2
    p = _box("AA battery box", 4 * cell + 3 * t, 2 * cell + t, 52.0, corner=2.0)
    p.wall = p.bottom = 1.6
    p.lid.lip_height = 3.0
    p.dividers = Dividers(across=4, deep=2, thickness=t)
    return p


def pencil_cup() -> Project:
    p = default_project(CYLINDER)
    p.name, p.diameter, p.height = "Pencil cup", 75.0, 100.0
    p.inside_corners, p.inside_corner_size = "rounded", 4.0
    return p


def jar() -> Project:
    p = default_project(CYLINDER)
    p.name, p.diameter, p.height = "Jar with screw-on lid", 60.0, 70.0
    p.lid.enabled, p.lid.style = True, THREADED
    return p


def pencil_box() -> Project:
    p = Project(shape=BOX, name="Pencil box", width=200.0, depth=60.0, height=30.0, wall=2.4,
                corner_radius=3.0)
    p.lid.enabled, p.lid.style = True, SLIDING
    return p


TEMPLATES = {
    "pi": Template("Raspberry Pi 3 / 4 / 5 case",
                   "Posts for the board, openings for power, HDMI, USB, network and the SD card, "
                   "and a lid with an air vent.", pi_case),
    "pi-zero": Template("Raspberry Pi Zero / Zero 2 W case",
                        "Posts, openings for mini HDMI, USB, power, the SD card and the camera "
                        "cable, and a lid with an air vent.", pi_zero_case),
    "pi-zero-stack": Template("Two stacked Pi Zero 2 W (crossed)",
                              "Two boards crossing like a +, the upper one on taller posts, "
                              "with openings for both boards' cables and SD cards.",
                              pi_zero_stack),
    "arduino": Template("Arduino Uno case",
                        "Posts for the board and openings for the USB and power plugs. Make it "
                        "taller if you add a shield.", arduino_case),
    "storage": Template("Storage box with lid",
                        "A plain box with a push-on lid that's easy to open.", storage_box),
    "tray": Template("Shallow tray with compartments",
                     "Six equal compartments, no lid.", lambda: default_project("tray")),
    "sorter": Template("Screw sorter with snap-on lid",
                       "Compartments for short, medium and long screws, with rounded corners "
                       "so screws slide out easily.", screw_sorter),
    "batteries": Template("AA battery box",
                          "Eight AA batteries standing up, each in its own compartment.",
                          battery_box),
    "pencil-cup": Template("Pencil cup", "A round cup without a lid.", pencil_cup),
    "jar": Template("Jar with screw-on lid", "A round jar with a threaded lid.", jar),
    "pencil-box": Template("Pencil box with sliding lid",
                           "A long box whose lid slides in from the front.", pencil_box),
}
ELECTRONICS = ("pi", "pi-zero", "pi-zero-stack", "arduino")


def from_template(key: str) -> Project:
    return TEMPLATES[key].build()
