"""Screw posts for mounting circuit boards: board catalogue and placement rules.

Board coordinates are in mm from the board's centre, x along its length.
Hole positions come from the manufacturers' mechanical drawings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .model import (SCREWS, Mount, Project, flat_clearance, has_lip, lid_column_radius, post_diameter,
                    lid_screw_positions, lip_outer_offset, lip_wall)

BOARD_THICKNESS = 1.6     # standard circuit board thickness
STACK_AIR = 1.0           # extra room between a board's tallest part and the board above
ROTATIONS = (0, 90, 180, 270)

# Boards without screw holes rest on round supports and are kept in place by an
# L-shaped guide at each corner, which reaches a little above the board.
SUPPORT_DIAMETER = 5.0
GUIDE_GAP = 0.5           # room between the board's edges and the guides
GUIDE_WALL = 1.6          # thickness of a guide
GUIDE_ABOVE = 2.0         # how far the guides reach above the top of the board
GUIDE_OUT = GUIDE_GAP + GUIDE_WALL


@dataclass(frozen=True)
class Guides:
    """How long the arms of the corner guides are, measured from each corner: kept short
    where sockets or an antenna stick out past the board's edge."""
    along_length: float = 4.0    # along the long edges (x)
    along_end: float = 4.0       # along the ends (y)


@dataclass(frozen=True)
class Board:
    name: str
    size: tuple[float, float] | None       # None = a single post with no board
    holes: tuple[tuple[float, float], ...]  # with guides: where the supports go
    screw: str
    parts_height: float = 10.0   # tallest part on top of the board
    flat: bool = False           # only low parts on top: stacking above it can be approved
    tall_parts: str = ""         # what the tallest parts are, for messages
    short: str = ""              # short name for messages
    guides: Guides | None = None  # no screw holes: supports and corner guides hold it


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
    # Pico 2 and Pico 2 W checked against their datasheets: the same board and holes.
    "pico": Board("Raspberry Pi Pico / Pico W / Pico 2 / Pico 2 W", (51.0, 21.0),
                  _from_corner(51, 21, [(2.0, 4.8), (49.0, 4.8), (2.0, 16.2), (49.0, 16.2)]),
                  "M2", parts_height=4.0, flat=True, short="Pico"),
    # Uno R4 Minima and R4 WiFi checked against their datasheets: the same holes as the R3.
    "uno": Board("Arduino Uno R3 / R4", (68.6, 53.3),
                 _from_corner(68.6, 53.3, [(13.97, 2.54), (15.24, 50.8), (66.04, 7.62),
                                           (66.04, 35.56)]),
                 "M3", parts_height=11.0, tall_parts="USB and power sockets",
                 short="Arduino Uno"),
    # The Giga R1 WiFi (datasheet) has these six holes too, plus small ones it doesn't need.
    "mega": Board("Arduino Mega 2560 / Giga R1 WiFi", (101.6, 53.3),
                  _from_corner(101.6, 53.3, [(13.97, 2.54), (15.24, 50.8), (66.04, 7.62),
                                             (66.04, 35.56), (90.17, 50.8), (96.52, 2.54)]),
                  "M3", parts_height=11.0, tall_parts="USB and power sockets",
                  short="Arduino Mega"),
    # Arduino Nano, Nano Every and Nano ESP32 (datasheets): 43.18 x 17.78 mm, holes 1.65 to
    # 1.8 mm across, 1.27 mm from the edges. The USB socket is at one end (x = 0 here).
    "nano": Board("Arduino Nano / Nano Every / Nano ESP32", (43.18, 17.78),
                  _from_corner(43.18, 17.78, [(1.27, 1.27), (41.91, 1.27), (1.27, 16.51),
                                              (41.91, 16.51)]),
                  "M1.6", parts_height=4.0, tall_parts="USB socket", short="Arduino Nano"),
    # Espressif ESP32-S3-DevKitC-1, v1.0 and v1.1 (both dimension drawings, DXF): 62.87 x
    # 25.40 mm on the outline (the drawing's dimension, 62.74, starts 0.13 mm in) and no screw
    # holes. Its pin header rows run 1.27 mm from the long edges with their plastic under the
    # board, 3.05 mm wide and reaching 0.25 mm past the edge; nothing else is underneath. The
    # two micro USB sockets are at the end x = 0, 6.0 and 19.4 mm from the front edge (each
    # 8.2 mm wide), sticking out 0.87 mm; the module's antenna sticks out 6.28 mm past the
    # other end, 3.65 to 21.65 mm from the front edge. It rests on four supports between the
    # header rows (clear of the USB sockets' solder tabs, 1.55 to 5.77 mm from that end); the
    # guides' arms along the ends stay clear of the sockets and the antenna.
    "esp32-s3": Board("ESP32-S3-DevKitC-1 / DevKitC-1U", (62.87, 25.4),
                      _from_corner(62.87, 25.4, [(9.0, 7.0), (55.0, 7.0), (9.0, 18.4),
                                                 (55.0, 18.4)]),
                      "M3", parts_height=4.0, flat=True, tall_parts="module and USB sockets",
                      short="ESP32-S3 DevKitC-1", guides=Guides(along_length=4.0, along_end=1.5)),
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


def board_corners(m: Mount, grow: float = 0.0) -> list[tuple[float, float]]:
    """Corners of the board outline on the floor (empty for a single post), optionally
    grown by `grow` all round."""
    size = board_size(m)
    if size is None:
        return []
    w, d = size[0] / 2 + grow, size[1] / 2 + grow
    return [_to_floor(m, x, y) for x, y in ((-w, -d), (w, -d), (w, d), (-w, d))]


def has_guides(m: Mount) -> bool:
    """Is it a board with no screw holes, held by supports and corner guides?"""
    return BOARDS[m.board].guides is not None


def outline_corners(m: Mount) -> list[tuple[float, float]]:
    """Corners of the area the board takes up on the floor, its corner guides included."""
    return board_corners(m, GUIDE_OUT if has_guides(m) else 0.0)


def guide_shapes(m: Mount) -> list[list[tuple[float, float]]]:
    """The corner guides seen from above: two rectangles (floor corners, counter-clockwise)
    for each corner, one along the long edge and one along the end."""
    guides = BOARDS[m.board].guides
    if guides is None:
        return []
    w, d = board_size(m)
    hw, hd = w / 2, d / 2
    out = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for x0, y0 in ((hw - guides.along_length, hd + GUIDE_GAP),
                           (hw + GUIDE_GAP, hd - guides.along_end)):
                x1, y1 = hw + GUIDE_OUT, hd + GUIDE_OUT
                pts = [(sx * x, sy * y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
                if sx * sy < 0:
                    pts.reverse()                       # mirrored once: turn back round
                out.append([_to_floor(m, x, y) for x, y in pts])
    return out


def half_extents(m: Mount) -> tuple[float, float]:
    """Half width/depth of the area the set covers on the floor."""
    pts = outline_corners(m) or post_positions(m)
    r = SCREWS[m.screw].post / 2
    hx = max(abs(x - m.u) for x, _ in pts)
    hy = max(abs(y - m.v) for _, y in pts)
    if not board_corners(m):
        hx, hy = hx + r, hy + r
    return hx, hy


def post_radius(m: Mount) -> float:
    if has_guides(m):
        return SUPPORT_DIAMETER / 2
    return post_diameter(m.screw, m.inserts) / 2


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


def holder_top(project: Project, m: Mount) -> float:
    """Height (z) of the top of what is printed for the board: the posts, or the guides."""
    if has_guides(m):
        return board_top(project, m) + GUIDE_ABOVE
    return board_bottom(project, m)


def footprint_box(m: Mount) -> tuple[float, float, float, float]:
    """(x_min, x_max, y_min, y_max) covered on the floor; exact, as boards turn in 90° steps."""
    hx, hy = half_extents(m)
    return m.u - hx, m.u + hx, m.v - hy, m.v + hy


def label(m: Mount) -> str:
    return BOARDS[m.board].name


def clearance(project: Project, m: Mount, u: float | None = None, v: float | None = None) -> float:
    """Room (mm) between the set and the walls; negative means it doesn't fit.

    Measures from the board's corners (or its corner guides) when there is a board, else
    from the posts.
    """
    du = 0.0 if u is None else u - m.u
    dv = 0.0 if v is None else v - m.v
    corners = outline_corners(m)
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
    corners = outline_corners(m)
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
        top = max(board_top(project, m), holder_top(project, m))
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

