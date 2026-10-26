"""Screw posts for mounting circuit boards: board catalogue and placement rules.

Board coordinates are in mm from the board's centre, x along its length.
Hole positions come from the manufacturers' mechanical drawings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .model import Mount, Project, flat_clearance, lip_outer_offset, lip_wall

BOARD_THICKNESS = 1.6     # standard circuit board thickness
STACK_AIR = 1.0           # extra room between a board's tallest part and the board above
ROTATIONS = (0, 90, 180, 270)


@dataclass(frozen=True)
class Screw:
    pilot: float          # hole the screw cuts its own thread into
    post: float           # outside diameter of the post


# Pilot holes are a little smaller than the screw so it cuts a thread into the
# plastic; posts are wide enough to leave a strong wall around the hole.
SCREWS = {
    "M1": Screw(pilot=0.9, post=3.5),
    "M2": Screw(pilot=1.7, post=5.0),
    "M2.5": Screw(pilot=2.2, post=6.0),
    "M3": Screw(pilot=2.6, post=7.0),
    "M4": Screw(pilot=3.5, post=9.0),
}


@dataclass(frozen=True)
class Board:
    name: str
    size: tuple[float, float] | None       # None = a single post with no board
    holes: tuple[tuple[float, float], ...]
    screw: str
    parts_height: float = 10.0   # tallest part on top of the board
    flat: bool = False           # only low parts on top: stacking above it can be approved
    tall_parts: str = ""         # what the tallest parts are, for messages
    short: str = ""              # short name for messages


def _from_corner(width, depth, holes):
    """Convert hole positions measured from the board's lower-left corner."""
    return tuple((x - width / 2, y - depth / 2) for x, y in holes)


BOARDS = {
    "single": Board("Single post", None, ((0.0, 0.0),), "M3", parts_height=0.0, flat=True, short="single post"),
    "rpi-ab": Board("Raspberry Pi 3 B / 3 B+ / 4 / 5", (85.0, 56.0),
                    _from_corner(85, 56, [(3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)]),
                    "M2.5", parts_height=16.0, tall_parts="USB and network sockets",
                    short="Pi 3/4/5"),
    "rpi-3a": Board("Raspberry Pi 3 A+", (65.0, 56.0),
                    _from_corner(65, 56, [(3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)]),
                    "M2.5", parts_height=8.0, tall_parts="USB socket", short="Pi 3 A+"),
    "rpi-zero": Board("Raspberry Pi Zero / Zero W / Zero 2 W", (65.0, 30.0),
                      _from_corner(65, 30, [(3.5, 3.5), (61.5, 3.5), (3.5, 26.5), (61.5, 26.5)]),
                      "M2.5", parts_height=4.0, flat=True, short="Pi Zero"),
    "pico": Board("Raspberry Pi Pico / Pico W / Pico 2", (51.0, 21.0),
                  _from_corner(51, 21, [(2.0, 4.8), (49.0, 4.8), (2.0, 16.2), (49.0, 16.2)]),
                  "M2", parts_height=4.0, flat=True, short="Pico"),
    "uno": Board("Arduino Uno", (68.6, 53.3),
                 _from_corner(68.6, 53.3, [(13.97, 2.54), (15.24, 50.8), (66.04, 7.62),
                                           (66.04, 35.56)]),
                 "M3", parts_height=11.0, tall_parts="USB and power sockets",
                 short="Arduino Uno"),
    "custom": Board("Custom board (4 holes)", None, (), "M3", parts_height=10.0,
                    tall_parts="parts", short="custom board"),
}


def board_size(m: Mount) -> tuple[float, float] | None:
    if m.board == "custom":
        return m.board_width, m.board_depth
    return BOARDS[m.board].size


def _local_holes(m: Mount):
    if m.board == "custom":
        hx, hy = m.spacing_x / 2, m.spacing_y / 2
        return ((-hx, -hy), (hx, -hy), (-hx, hy), (hx, hy))
    return BOARDS[m.board].holes


def _to_floor(m: Mount, x: float, y: float) -> tuple[float, float]:
    a = math.radians(m.rotation)
    c, s = math.cos(a), math.sin(a)
    return m.u + x * c - y * s, m.v + x * s + y * c


def post_positions(m: Mount) -> list[tuple[float, float]]:
    """Centres of the posts on the floor."""
    return [_to_floor(m, x, y) for x, y in _local_holes(m)]


def board_corners(m: Mount) -> list[tuple[float, float]]:
    """Corners of the board outline on the floor (empty for a single post)."""
    size = board_size(m)
    if size is None:
        return []
    w, d = size[0] / 2, size[1] / 2
    return [_to_floor(m, x, y) for x, y in ((-w, -d), (w, -d), (w, d), (-w, d))]


def half_extents(m: Mount) -> tuple[float, float]:
    """Half width/depth of the area the set covers on the floor."""
    pts = board_corners(m) or post_positions(m)
    r = SCREWS[m.screw].post / 2
    hx = max(abs(x - m.u) for x, _ in pts)
    hy = max(abs(y - m.v) for _, y in pts)
    if not board_corners(m):
        hx, hy = hx + r, hy + r
    return hx, hy


def post_radius(m: Mount) -> float:
    return SCREWS[m.screw].post / 2


def board_bottom(project: Project, m: Mount) -> float:
    """Height (z) where the board rests: on top of the posts."""
    return project.bottom + m.length


def max_screw_length(m: Mount) -> float:
    """Longest screw that fits: through the board and down the post, not into the floor."""
    return math.floor((m.length + (BOARD_THICKNESS if board_size(m) else 0.0) - 0.5) * 2) / 2


def parts_height(m: Mount) -> float:
    """Height of the tallest part on top of the board."""
    return m.parts_height if m.parts_height >= 0 else BOARDS[m.board].parts_height


def room_above(m: Mount) -> float:
    """Room a board needs above it before another board can sit there."""
    return parts_height(m) + STACK_AIR


def board_top(project: Project, m: Mount) -> float:
    """Height (z) of the top surface of the board (or of the posts, for a single post)."""
    return board_bottom(project, m) + (BOARD_THICKNESS if board_size(m) else 0.0)


def footprint_box(m: Mount) -> tuple[float, float, float, float]:
    """(x_min, x_max, y_min, y_max) covered on the floor; exact, as boards turn in 90° steps."""
    hx, hy = half_extents(m)
    return m.u - hx, m.u + hx, m.v - hy, m.v + hy


def label(m: Mount) -> str:
    return BOARDS[m.board].name


def clearance(project: Project, m: Mount, u: float | None = None, v: float | None = None) -> float:
    """Room (mm) between the set and the walls; negative means it doesn't fit.

    Measures from the board's corners when there is a board, else from the posts.
    """
    du = 0.0 if u is None else u - m.u
    dv = 0.0 if v is None else v - m.v
    corners = board_corners(m)
    if corners:
        return min(flat_clearance(project, "bottom", x + du, y + dv) for x, y in corners)
    r = post_radius(m)
    return min(flat_clearance(project, "bottom", x + du, y + dv) - r for x, y in post_positions(m))


def needed_clearance(project: Project, m: Mount) -> float:
    """Room needed around the set: a little air, plus the lid's lip if the board reaches it."""
    need = 1.0 if board_size(m) else 0.0
    if project.lid.enabled and board_size(m):
        top = board_bottom(project, m) + BOARD_THICKNESS
        if top > project.outer_height - project.lid.lip_height - project.lid.gap:
            need = max(need, lip_outer_offset(project) + lip_wall(project) + project.lid.gap)
    return need


def clamp_mount(project: Project, m: Mount, u: float, v: float) -> tuple[float, float] | None:
    """Nearest position to (u, v) where the set fits with the room it needs."""
    need = needed_clearance(project, m)
    hx, hy = half_extents(m)
    lim_x = project.inner_width / 2 - hx - need
    lim_y = project.inner_depth / 2 - hy - need
    if lim_x < 0 or lim_y < 0:
        return None
    u, v = min(max(u, -lim_x), lim_x), min(max(v, -lim_y), lim_y)
    for _ in range(150):
        if clearance(project, m, u, v) >= need - 1e-6:
            return round(u, 2), round(v, 2)
        u *= 0.97
        v *= 0.97
    return None


def new_mount(project: Project, board: str) -> Mount:
    """A new set of posts, placed in the middle of the floor."""
    spec = BOARDS[board]
    m = Mount(board=board, screw=spec.screw)
    if board == "single":
        m.length = 6.0
    pos = clamp_mount(project, m, 0.0, 0.0)
    if pos is None and board_size(m):
        m.rotation = 90                      # try it the other way round
        pos = clamp_mount(project, m, 0.0, 0.0)
        if pos is None:
            m.rotation = 0
    if pos:
        m.u, m.v = pos
    return m

