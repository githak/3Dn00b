"""Screw posts for mounting circuit boards: board catalogue and placement rules.

Board coordinates are in mm from the board's centre, x along its length.
Hole positions come from the manufacturers' mechanical drawings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .model import (SCREWS, Mount, Project, flat_clearance, has_lip, lid_column_radius,
                    lid_screw_positions, lip_outer_offset, lip_wall)

BOARD_THICKNESS = 1.6     # standard circuit board thickness
STACK_AIR = 1.0           # extra room between a board's tallest part and the board above
ROTATIONS = (0, 90, 180, 270)


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
    "custom2": Board("Custom board (2 holes)", None, (), "M3", parts_height=10.0,
                     tall_parts="parts", short="custom board"),
    "custom1": Board("Custom board (1 hole)", None, (), "M3", parts_height=10.0,
                     tall_parts="parts", short="custom board"),
}
# Boards whose size and holes the user types in. For "custom1" the spacing fields
# say where the single hole is, measured from the middle of the board.
CUSTOM_BOARDS = ("custom", "custom2", "custom1")
# Starting sizes for a new custom board: (width, depth, spacing_x, spacing_y).
CUSTOM_STARTS = {"custom": (60.0, 40.0, 52.0, 32.0), "custom2": (30.0, 20.0, 24.0, 0.0),
                 "custom1": (20.0, 20.0, 0.0, 0.0)}


def is_custom(m: Mount) -> bool:
    return m.board in CUSTOM_BOARDS


def board_size(m: Mount) -> tuple[float, float] | None:
    if is_custom(m):
        return m.board_width, m.board_depth
    return BOARDS[m.board].size


def _local_holes(m: Mount):
    hx, hy = m.spacing_x / 2, m.spacing_y / 2
    if m.board == "custom":
        return ((-hx, -hy), (hx, -hy), (-hx, hy), (hx, hy))
    if m.board == "custom2":
        return ((-hx, -hy), (hx, hy))       # in a line, or diagonal if spacing_y isn't 0
    if m.board == "custom1":
        return ((m.spacing_x, m.spacing_y),)
    return BOARDS[m.board].holes


def holes_on_board(m: Mount) -> bool:
    """Do all of a custom board's holes lie inside the board?"""
    w, d = board_size(m)
    return all(abs(x) < w / 2 and abs(y) < d / 2 for x, y in _local_holes(m))


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


COLUMN_ROOM = 0.5      # room kept between a board and a lid screw column


def column_clearance(project: Project, m: Mount, u: float | None = None,
                     v: float | None = None) -> float:
    """Room (mm) between the set and the lid's screw columns (large if there are none)."""
    columns = lid_screw_positions(project)
    if not columns:
        return 1e9
    du = 0.0 if u is None else u - m.u
    dv = 0.0 if v is None else v - m.v
    r = lid_column_radius(project)
    corners = board_corners(m)
    room = 1e9
    for cx, cy in columns:
        if corners:
            x0, x1 = min(c[0] for c in corners) + du, max(c[0] for c in corners) + du
            y0, y1 = min(c[1] for c in corners) + dv, max(c[1] for c in corners) + dv
            gap = math.hypot(max(x0 - cx, 0.0, cx - x1), max(y0 - cy, 0.0, cy - y1)) - r
        else:
            gap = min(math.dist((cx, cy), (x + du, y + dv)) for x, y in post_positions(m)) \
                - r - post_radius(m)
        room = min(room, gap)
    return room


def needed_clearance(project: Project, m: Mount) -> float:
    """Room needed around the set: a little air, plus the lid's lip if the board reaches it."""
    need = 1.0 if board_size(m) else 0.0
    if has_lip(project) and board_size(m):
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

    def fits(x, y):
        return (clearance(project, m, x, y) >= need - 1e-6
                and column_clearance(project, m, x, y) >= COLUMN_ROOM - 1e-6)

    # Walk straight towards the middle (which handles walls and rounded corners) ...
    for i in range(101):
        x, y = u * (1 - i / 100), v * (1 - i / 100)
        if fits(x, y):
            return round(x, 2), round(y, 2)
    # ... else look around the floor for the nearest spot that fits.
    best = None
    steps = 30
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            x, y = lim_x * i / steps, lim_y * j / steps
            d = math.hypot(x - u, y - v)
            if (best is None or d < best[0]) and fits(x, y):
                best = (d, x, y)
    return (round(best[1], 2), round(best[2], 2)) if best else None


def new_mount(project: Project, board: str) -> Mount:
    """A new set of posts, placed in the middle of the floor."""
    spec = BOARDS[board]
    m = Mount(board=board, screw=spec.screw)
    if board in CUSTOM_STARTS:
        m.board_width, m.board_depth, m.spacing_x, m.spacing_y = CUSTOM_STARTS[board]
    pos = clamp_mount(project, m, 0.0, 0.0)
    if pos is None and board_size(m):
        m.rotation = 90                      # try it the other way round
        pos = clamp_mount(project, m, 0.0, 0.0)
        if pos is None:
            m.rotation = 0
    if pos:
        m.u, m.v = pos
    return m

