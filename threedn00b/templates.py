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
from .model import (BACK, BOTTOM, BOX, CYLINDER, FRONT, INSIDE, LEFT, LID, RECT, RIGHT,
                    SCREWED, SLIDING, SNAP, THREADED, VENT, Dividers, Hole, Mount, Project,
                    clamp_hole, default_project)


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

# Raspberry Pi 3 B+, 4 and 5 (85 x 56 mm). Socket positions from the official Raspberry Pi
# mechanical drawings (datasheets.raspberrypi.com), measured from the corner with the power
# and HDMI edge at the front:
#   front: micro USB / USB-C at 10.6 / 11.2, HDMI at 32 (Pi 3) or 26 + 39.5 (Pi 4) or
#          25.8 + 39.2 (Pi 5), audio at 53.5 / 54. The audio jack sticks out 2.6 mm.
#   right: USB and network across 1.5 to 54.5 (their order differs between models),
#          up to 16.5 mm tall; they stick out 2 mm (Pi 3) or 3 mm (Pi 4 and 5).
#   left:  micro SD card under the board at 28, sticking out 2.5 mm; the Pi 5's power
#          button at 18.4.
PI_ROOM = {"left": 3.0, "right": 3.5, "front": 3.0, "back": 1.5}   # room around the board


def pi_case(fan: bool = False, gpio: bool = False) -> Project:
    name = ("Raspberry Pi 5 case with fan" if fan else
            "Raspberry Pi case with GPIO slot" if gpio else "Raspberry Pi case")
    room = PI_ROOM
    p = _box(name, 85 + room["left"] + room["right"], 56 + room["front"] + room["back"], 32.0)
    m = _board(p, "rpi-ab", 6.0, u=(room["left"] - room["right"]) / 2,
               v=(room["front"] - room["back"]) / 2)
    pi_openings(p, m)
    if fan:
        # A 30 mm fan under the lid, over the Pi 5's processor (33.2 x 22.9 on the
        # drawing), held by four screws 24 mm apart, clear of the tall sockets.
        x, y = _floor_point(m, 33.2, 22.9)
        p.holes.append(Hole(surface=LID, diameter=26.0, u=x, v=y))
        p.holes += [Hole(surface=LID, diameter=3.4, u=x + dx, v=y + dy)
                    for dx in (-12.0, 12.0) for dy in (-12.0, 12.0)]
    else:
        # Air out over the processor (Pi 4 at 29 x 32.5, Pi 5 at 32.5 x 23.5).
        x, y = _floor_point(m, 31.0, 28.0)
        p.holes.append(Hole(surface=LID, kind=VENT, width=40.0, height=16.0, u=x, v=y,
                            rounding=1.0))
    if gpio:
        # A slot in the lid for a ribbon cable, as close to the 40-pin header as the
        # lid's lip allows (the header is centred between the mounting holes along the
        # back edge; the ribbon bends over the gap).
        x, y = _floor_point(m, 32.5, 52.5)
        slot = Hole(surface=LID, kind=RECT, width=56.0, height=6.0, u=x, v=y, rounding=1.5)
        slot.u, slot.v = clamp_hole(p, slot)
        p.holes.append(slot)
    return p


def pi_openings(p: Project, m: Mount) -> None:
    """All the openings a Raspberry Pi 3 B+ / 4 / 5 on posts `m` needs."""
    top = _top(p, m)
    _pi_front_opening(p, m)
    # USB and network sockets on the right edge (one opening fits every model's order).
    a, b = _facing(p, m, 85, 1.5), _facing(p, m, 85, 54.5)
    _opening(p, a[0], (a[1] + b[1]) / 2, top - 1.0, top + 17.5, abs(b[1] - a[1]))
    # The micro SD card (under the board) and, on a Pi 5, the power button beside it.
    a, b = _facing(p, m, 0, 16.0), _facing(p, m, 0, 35.0)
    _opening(p, a[0], (a[1] + b[1]) / 2, top - 4.5, top + 4.5, abs(b[1] - a[1]), rounding=2.0)


def _pi_front_opening(p: Project, m: Mount) -> None:
    """Power, HDMI and audio along the front edge: one opening fits the Pi 3, 4 and 5,
    tall enough for the moulded part of the plugs (a full-size HDMI plug is the largest)."""
    top = _top(p, m)
    a, b = _facing(p, m, 3.5, 0), _facing(p, m, 59.0, 0)
    _opening(p, a[0], (a[1] + b[1]) / 2, top - 3.0, top + 9.0, abs(b[1] - a[1]), rounding=2.0)


def pico_case() -> Project:
    # 51 x 21 mm. Tall posts leave room for pin headers soldered underneath.
    p = _box("Raspberry Pi Pico case", 51 + 2.0 + 1.5, 21 + 3.0, 21.0, corner=2.5)
    m = _board(p, "pico", 8.0, u=(2.0 - 1.5) / 2, v=0.0)
    top = _top(p, m)
    _opening(p, *_facing(p, m, 0, 10.5), top - 3.0, top + 5.0, 11.5, rounding=2.0)  # micro USB
    # A hole for the wires to whatever the Pico controls.
    p.holes.append(Hole(surface=RIGHT, diameter=6.0, v=top + 2.0 - p.outer_height / 2))
    return p


ESP32_SIZE = (51.5, 28.5, 47.0, 23.5)    # common 30-pin ESP32 DevKit: board and hole spacing


def esp32_case() -> Project:
    w, d, sx, sy = ESP32_SIZE
    p = _box("ESP32 case", w + 2.0 + 1.5, d + 3.0, 22.0, corner=2.5)
    m = Mount(board="custom", screw="M2", length=9.0, u=(2.0 - 1.5) / 2, v=0.0,
              board_width=w, board_depth=d, spacing_x=sx, spacing_y=sy, parts_height=5.0)
    p.mounts.append(m)
    top = _top(p, m)
    # USB (micro USB or USB-C) in the middle of one short end, next to the two buttons.
    _opening(p, *_facing(p, m, 0, d / 2), top - 3.0, top + 5.0, 12.5, rounding=2.0)
    p.holes.append(Hole(surface=RIGHT, diameter=6.0, v=top + 2.0 - p.outer_height / 2))
    return p


# Raspberry Pi Zero, Zero W and Zero 2 W (65 x 30 mm), from the official drawing: mini HDMI
# at 12.4, micro USB (data) at 41.4 and micro USB (power) at 54 along the front edge (the
# micro USB sockets stick out 1.35 mm); camera connector at 15 on the right edge; micro SD
# card (on top) at 16.7 on the left edge (not on the drawing; from NopSCADlib).

def pi_zero_case() -> Project:
    p = _box("Raspberry Pi Zero case", 65 + 2.5 + 1.5, 30 + 2.0 + 1.5, 18.0, corner=2.5)
    m = _board(p, "rpi-zero", 4.0, u=(2.5 - 1.5) / 2, v=(2.0 - 1.5) / 2)
    zero_openings(p, m)
    p.holes.append(Hole(surface=LID, kind=VENT, width=30.0, height=10.0, rounding=1.0))
    return p


def zero_openings(p: Project, m: Mount, camera: bool = True) -> None:
    """Openings sized for the moulded part of the plugs, which goes into the wall."""
    top = _top(p, m)
    _opening(p, *_facing(p, m, 12.4, 0), top - 3.0, top + 6.0, 14.0, rounding=2.0)   # mini HDMI
    # Both micro USB sockets share one opening: they're only 12.6 mm apart, too close
    # for a strip of plastic between two plugs.
    a, b = _facing(p, m, 35.6, 0), _facing(p, m, 59.8, 0)
    _opening(p, a[0], (a[1] + b[1]) / 2, top - 2.5, top + 5.0, abs(b[1] - a[1]), rounding=2.0)
    _opening(p, *_facing(p, m, 0, 16.7), top - 1.5, top + 3.0, 14.0)      # SD card
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
    """Two Pi Zero 2 W crossing like a +, the upper one on taller posts.

    Placed so the cables can reach: the upper board's sockets face the right wall, right
    behind it, and its SD card the front wall. The lower board's sockets face the front
    wall; it sits as close to it as the upper board's front posts allow (they stand on
    the floor in front of the lower board), about 10 mm in, which a plug reaches through
    its opening. Its SD card faces the left wall.
    """
    width, depth = 65 + 2.5 + 2.5, 65 + 2.5 + 1.5
    p = _box("Two stacked Pi Zero 2 W", width, depth, 27.0, corner=3.0)
    # The upper board stands higher than the lower board's parts need (4 mm plus 1 mm of
    # air), so its SD card opening stays clear of the lower board's USB opening.
    upper = _board(p, "rpi-zero", 12.5, u=width / 2 - 2.0 - 15, v=-depth / 2 + 2.5 + 32.5,
                   rotation=90)
    front_post = min(y for _, y in mounts.post_positions(upper))
    lower = _board(p, "rpi-zero", 4.0, u=-width / 2 + 2.5 + 32.5,
                   v=front_post + mounts.post_radius(upper) + 0.5 + 15)
    zero_openings(p, lower, camera=False)
    zero_openings(p, upper, camera=False)
    p.holes.append(Hole(surface=LID, kind=VENT, width=24.0, height=24.0, rounding=1.0))
    return p


def pi_3a_case() -> Project:
    # 65 x 56 mm: the Pi 3 B+ front edge and SD card, and one USB socket on the right at
    # 31.5 (sticking out 2.5 mm); no network socket.
    room = dict(PI_ROOM, right=3.0)
    p = _box("Raspberry Pi 3 A+ case", 65 + room["left"] + room["right"],
             56 + room["front"] + room["back"], 24.0)
    m = _board(p, "rpi-3a", 6.0, u=(room["left"] - room["right"]) / 2,
               v=(room["front"] - room["back"]) / 2)
    top = _top(p, m)
    _pi_front_opening(p, m)
    _opening(p, *_facing(p, m, 65, 31.45), top - 1.0, top + 9.0, 18.0)          # USB
    _opening(p, *_facing(p, m, 0, 28.0), top - 5.0, top - 0.5, 15.0, rounding=2.0)  # SD
    p.holes.append(Hole(surface=LID, kind=VENT, width=30.0, height=14.0, rounding=1.0))
    return p


def arduino_case(board: str = "uno") -> Project:
    # USB B socket at 37.8 (Uno) or about 38.6 (Mega) and power jack at 7.6 on the left
    # edge (Arduino datasheets). The USB socket sticks out 6.4 mm, so the board sits 7 mm
    # in to let it drop into place.
    w, d = mounts.BOARDS[board].size
    name = "Arduino Mega case" if board == "mega" else "Arduino Uno case"
    p = _box(name, w + 7.0 + 1.9, d + 3.7, 26.0)
    m = _board(p, board, 5.0, u=(7.0 - 1.9) / 2, v=0.0)
    top = _top(p, m)
    _, y = _floor_point(m, 0, 38.2)
    _opening(p, LEFT, y, top - 0.5, top + 12.0, 14.0)               # USB B (Uno and Mega)
    # The jack sits 4.6 mm back from the wall, so the plug's moulded part goes into it.
    _, y = _floor_point(m, 0, 7.62)
    _opening(p, LEFT, y, top - 0.5, top + 12.0, 11.5, rounding=3.0)  # power jack
    return p


def project_box() -> Project:
    # A custom 4-hole board the user sets to their own, with holes for cables.
    p = _box("Project box", 80.0, 60.0, 35.0)
    m = mounts.new_mount(p, "custom")
    m.length = 6.0
    p.mounts.append(m)
    z = mounts.board_bottom(p, m) + 8.0 - p.outer_height / 2
    p.holes += [Hole(surface=LEFT, diameter=8.0, v=z), Hole(surface=RIGHT, diameter=8.0, v=z)]
    return p


def breadboard_box() -> Project:
    # A half-size (400-point) breadboard, 82.5 x 54.5 mm, stuck to the floor with its
    # own sticky back, with holes at both ends for wires.
    p = _box("Breadboard box", 86.0, 58.0, 35.0)
    z = p.bottom + 15.0 - p.outer_height / 2
    p.holes = [Hole(surface=LEFT, diameter=10.0, v=z), Hole(surface=RIGHT, diameter=10.0, v=z)]
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


def plant_pot() -> Project:
    p = default_project(CYLINDER)
    p.name, p.diameter, p.height = "Plant pot", 100.0, 90.0
    p.inside_corners, p.inside_corner_size = "rounded", 5.0
    # Drainage: one hole in the middle and four around it.
    p.holes = [Hole(surface=BOTTOM, diameter=6.0)]
    p.holes += [Hole(surface=BOTTOM, diameter=6.0, u=u, v=v)
                for u, v in ((22.0, 0.0), (-22.0, 0.0), (0.0, 22.0), (0.0, -22.0))]
    return p


def money_box() -> Project:
    # A screwed-down lid, so it can be opened, with a slot big enough for any coin.
    p = _box("Money box", 80.0, 60.0, 80.0, corner=4.0)
    p.lid.style, p.lid.opening = SCREWED, "none"
    p.holes.append(Hole(surface=LID, kind=RECT, width=32.0, height=4.0, rounding=2.0))
    return p


def pill_box() -> Project:
    # Seven compartments, one for each day of the week.
    p = _box("Weekly pill box", 7 * 20.0 + 6 * 1.2, 28.0, 20.0, corner=3.0)
    p.wall = p.bottom = 1.6
    p.lid.style, p.lid.lip_height = SNAP, 4.0
    p.inside_corners, p.inside_corner_size = "rounded", 4.0       # pills slide out easily
    p.dividers = Dividers(across=7, thickness=1.2)
    return p


def card_box() -> Project:
    # Room for a stack of 85 x 55 mm business cards, with a little play.
    return _box("Business card box", 89.0, 59.0, 30.0, corner=3.0)


def dice_box() -> Project:
    p = _box("Dice box", 40.0, 40.0, 40.0, corner=4.0)
    p.lid.style = SNAP
    return p


def desk_organiser() -> Project:
    p = Project(shape=BOX, name="Desk organiser", size_mode=INSIDE, width=160.0, depth=90.0,
                height=90.0, wall=2.0, bottom=2.0, corner_radius=5.0)
    p.inside_corners, p.inside_corner_size = "rounded", 4.0
    # Pens, a phone, and the rest (notes, cards).
    p.dividers = Dividers(across=3, thickness=2.0, widths=[40.0, 70.0])
    return p


def charging_box() -> Project:
    # Hides chargers and cables, with holes for the cables at both ends and the back.
    p = _box("Charging box", 160.0, 100.0, 60.0, corner=5.0)
    z = p.bottom + 10.0 - p.outer_height / 2
    p.holes = [Hole(surface=s, diameter=14.0, v=z) for s in (LEFT, RIGHT, BACK)]
    p.holes.append(Hole(surface=LID, kind=RECT, width=60.0, height=8.0, rounding=4.0))
    return p


def parts_box() -> Project:
    # Sixteen small compartments for beads, bits, resistors or LEGO pieces.
    p = _box("Parts box", 4 * 25.0 + 3 * 1.2, 4 * 25.0 + 3 * 1.2, 25.0, corner=3.0)
    p.wall = p.bottom = 1.6
    p.lid.style = SNAP
    p.inside_corners, p.inside_corner_size = "rounded", 3.0
    p.dividers = Dividers(across=4, deep=4, thickness=1.2)
    return p


def craft_box() -> Project:
    p = _box("Craft box", 3 * 45.0 + 2 * 1.6, 3 * 40.0 + 2 * 1.6, 40.0, corner=4.0)
    p.wall = p.bottom = 1.6
    p.dividers = Dividers(across=3, deep=3, thickness=1.6)
    return p


def pick_box() -> Project:
    # Guitar picks are about 26 x 31 mm.
    p = _box("Guitar pick box", 36.0, 36.0, 16.0, corner=4.0)
    p.lid.style, p.lid.lip_height = SNAP, 4.0
    return p


def small_tin() -> Project:
    p = default_project(CYLINDER)
    p.name, p.diameter, p.height = "Small screw-top tin", 45.0, 30.0
    p.lid.enabled, p.lid.style = True, THREADED
    p.inside_corners, p.inside_corner_size = "rounded", 3.0
    return p


def soap_dish() -> Project:
    p = Project(shape=BOX, name="Soap dish", size_mode=INSIDE, width=100.0, depth=70.0,
                height=15.0, wall=2.0, bottom=2.0, corner_radius=8.0)
    p.inside_corners, p.inside_corner_size = "rounded", 4.0
    # Slots in the bottom so the water runs off.
    p.holes = [Hole(surface=BOTTOM, kind=VENT, width=70.0, height=40.0, slot=3.0, gap=4.0,
                    rounding=1.5)]
    return p


def key_tray() -> Project:
    p = default_project(CYLINDER)
    p.name, p.diameter, p.height = "Key tray", 120.0, 20.0
    p.inside_corners, p.inside_corner_size = "rounded", 6.0
    return p


def toothbrush_cup() -> Project:
    p = default_project(CYLINDER)
    p.name, p.diameter, p.height = "Toothbrush cup", 70.0, 100.0
    p.inside_corners, p.inside_corner_size = "rounded", 5.0
    p.holes = [Hole(surface=BOTTOM, diameter=6.0)]                 # lets water drain
    return p


def tea_box() -> Project:
    # Two kinds of tea bags in their paper envelopes (about 60 x 75 mm).
    p = _box("Tea bag box", 2 * 66.0 + 1.6, 82.0, 70.0, corner=4.0)
    p.dividers = Dividers(across=2, thickness=1.6)
    return p


def remote_holder() -> Project:
    # Three slots for remote controls, standing up.
    p = Project(shape=BOX, name="Remote control holder", size_mode=INSIDE,
                width=3 * 55.0 + 2 * 2.0, depth=35.0, height=70.0, wall=2.0, bottom=2.0,
                corner_radius=4.0)
    p.inside_corners, p.inside_corner_size = "rounded", 4.0
    p.dividers = Dividers(across=3, thickness=2.0)
    return p


TEMPLATES = {
    "pi": Template("Raspberry Pi 3 / 4 / 5 case",
                   "Posts for the board, openings for power, HDMI, audio, USB, network, the SD "
                   "card and the Pi 5's power button, and a lid with an air vent.", pi_case),
    "pi5-fan": Template("Raspberry Pi 5 case with a 30 mm fan",
                        "Like the Pi 3 / 4 / 5 case, with a 30 mm fan in the lid blowing onto "
                        "the processor. The fan's wires go to the Pi's 5 V and ground pins.",
                        lambda: pi_case(fan=True)),
    "pi-gpio": Template("Raspberry Pi 3 / 4 / 5 case with GPIO slot",
                        "Like the Pi 3 / 4 / 5 case, with a slot in the lid over the 40-pin "
                        "header for a ribbon cable.", lambda: pi_case(gpio=True)),
    "pi-zero": Template("Raspberry Pi Zero / Zero 2 W case",
                        "Posts, openings for mini HDMI, USB, power, the SD card and the camera "
                        "cable, and a lid with an air vent.", pi_zero_case),
    "pi-zero-stack": Template("Two stacked Pi Zero 2 W (crossed)",
                              "Two boards crossing, the upper one on taller posts, placed so "
                              "every cable reaches: the upper board's sockets face the right "
                              "wall, the lower board's the front wall.", pi_zero_stack),
    "pi-3a": Template("Raspberry Pi 3 A+ case",
                      "Posts, openings for power, HDMI, audio, USB and the SD card, and a lid "
                      "with an air vent.", pi_3a_case),
    "arduino": Template("Arduino Uno case",
                        "Posts for the board and openings for the USB and power plugs. Make it "
                        "taller if you add a shield.", arduino_case),
    "mega": Template("Arduino Mega 2560 case",
                     "Posts for all six holes and openings for the USB and power plugs. Make it "
                     "taller if you add a shield.", lambda: arduino_case("mega")),
    "pico": Template("Raspberry Pi Pico case",
                     "Posts tall enough for pin headers underneath, an opening for the USB plug "
                     "and a hole for wires.", pico_case),
    "esp32": Template("ESP32 DevKit case",
                      "For the common 30-pin ESP32 boards. Boards differ: measure yours and "
                      "change the board size and hole spacing in the Posts tab.", esp32_case),
    "project-box": Template("Project box for your own board",
                            "Posts for a 4-hole board (set its size and hole spacing in the "
                            "Posts tab) and a cable hole at each end.", project_box),
    "breadboard": Template("Half-size breadboard box",
                           "For a 400-point breadboard (stick it down with its own sticky "
                           "back), with holes for wires at both ends.", breadboard_box),
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
    "pills": Template("Weekly pill box",
                      "Seven compartments, one per day, with rounded corners and a snap-on lid.",
                      pill_box),
    "cards": Template("Business card box", "Fits a stack of 85 × 55 mm cards.", card_box),
    "dice": Template("Dice box", "A small box with a snap-on lid.", dice_box),
    "money": Template("Money box",
                      "A coin slot in the lid; unscrew the lid to get the money out.", money_box),
    "desk": Template("Desk organiser",
                     "Three tall compartments: pens, a phone, and notes.", desk_organiser),
    "charging": Template("Charging box",
                         "Hides chargers and cables: cable holes at the ends and the back, and "
                         "a slot in the lid for a phone cable.", charging_box),
    "plant-pot": Template("Plant pot",
                          "A round pot with drainage holes. Stand it on a saucer.", plant_pot),
    "parts": Template("Parts box (4 × 4)",
                      "Sixteen small compartments for beads, bits or resistors, with a "
                      "snap-on lid.", parts_box),
    "craft": Template("Craft box (3 × 3)", "Nine compartments with a push-on lid.", craft_box),
    "picks": Template("Guitar pick box", "A small box with a snap-on lid.", pick_box),
    "tin": Template("Small screw-top tin",
                    "A little round tin with a threaded lid, for earbuds or pills.", small_tin),
    "soap": Template("Soap dish", "Slots in the bottom let the water run off, so put it where "
                     "it can drip, such as the edge of the sink.", soap_dish),
    "keys": Template("Key tray", "A shallow round tray for keys and coins.", key_tray),
    "toothbrush": Template("Toothbrush cup", "A tall cup with a hole for water to drain.",
                           toothbrush_cup),
    "tea": Template("Tea bag box", "Two compartments for tea bags in envelopes, with a lid.",
                    tea_box),
    "remotes": Template("Remote control holder", "Three slots for remote controls.",
                        remote_holder),
    "pencil-cup": Template("Pencil cup", "A round cup without a lid.", pencil_cup),
    "jar": Template("Jar with screw-on lid", "A round jar with a threaded lid.", jar),
    "pencil-box": Template("Pencil box with sliding lid",
                           "A long box whose lid slides in from the front.", pencil_box),
}
# How the list is grouped in the app: (heading, template keys).
GROUPS = (
    ("Cases for boards", ("pi", "pi-gpio", "pi5-fan", "pi-3a", "pi-zero", "pi-zero-stack", "pico",
                          "arduino", "mega", "esp32", "breadboard", "project-box")),
    ("Storage", ("storage", "tray", "sorter", "parts", "craft", "batteries", "pills", "cards",
                 "dice", "picks", "tin", "money")),
    ("Around the house", ("desk", "remotes", "charging", "tea", "plant-pot", "pencil-cup",
                          "toothbrush", "soap", "keys", "jar", "pencil-box")),
)
ELECTRONICS = GROUPS[0][1]


def from_template(key: str) -> Project:
    project = TEMPLATES[key].build()
    project.template = key
    return project
