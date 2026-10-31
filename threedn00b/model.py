"""Parametric object model.

Everything a project *means* lives here: the base shape, its measurements,
the holes the user added (with where they sit), and the lid. This module has
no knowledge of meshes, Qt or files, so it is easy to test.

Coordinate system (millimetres): X = width (left -> right), Y = depth
(front -> back), Z = up. The origin is the centre of the bottom face.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

BOX = "box"
CYLINDER = "cylinder"
SHAPES = (BOX, CYLINDER)

OUTSIDE = "outside"
INSIDE = "inside"

# Surfaces a hole can sit on. "side" is the round wall of a cylinder.
FRONT, BACK, LEFT, RIGHT, SIDE, BOTTOM, LID = (
    "front", "back", "left", "right", "side", "bottom", "lid")
BOX_SURFACES = (FRONT, BACK, LEFT, RIGHT, BOTTOM, LID)
CYLINDER_SURFACES = (SIDE, BOTTOM, LID)
SURFACE_LABELS = {
    FRONT: "Front wall", BACK: "Back wall", LEFT: "Left wall",
    RIGHT: "Right wall", SIDE: "Round wall", BOTTOM: "Bottom", LID: "Lid",
}

# Lid fit presets: gap between the lid's lip and the box wall, per side.
FIT_PRESETS = {"tight": 0.15, "normal": 0.25, "loose": 0.40}
FIT_LABELS = {"tight": "Tight", "normal": "Normal", "loose": "Loose",
              "custom": "Custom"}

# Allowed input ranges (also used by the GUI spin boxes).
SIZE_RANGE = (10.0, 300.0)
WALL_RANGE = (0.8, 10.0)
HOLE_DIAMETER_RANGE = (1.0, 100.0)

ROUND, RECT, VENT = "round", "rect", "vent"
HOLE_KIND_LABELS = {ROUND: "Round", RECT: "Rectangle", VENT: "Air vent"}
# Air vents: slots run along v ("up and down" on a wall) or along u ("sideways").
ALONG_V, ALONG_U = "along_v", "along_u"
# Hard minimum of material kept between a hole and the edge of its surface.
# Closer than this is not allowed at all; the validator also warns when the
# margin is below the comfortable value returned by comfortable_margin().
MIN_EDGE = 0.4


@dataclass
class Hole:
    """A round or rectangular opening through one surface."""
    surface: str = FRONT
    diameter: float = 8.0          # round holes
    # Position measured from the centre of the surface:
    #  walls:          u = left/right (as seen from outside), v = up/down
    #  round wall:     u = angle in degrees (0 = front, 90 = right), v = up/down
    #  bottom and lid: u = left/right, v = towards the back (as seen from above)
    u: float = 0.0
    v: float = 0.0
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    kind: str = ROUND
    width: float = 12.0            # rectangles and vents: size along u (left/right, or around)
    height: float = 6.0            # rectangles and vents: size along v (up/down, or front/back)
    slot: float = 2.0              # vents: width of each slot
    gap: float = 2.0               # vents: plastic left between slots
    slot_direction: str = ALONG_V  # vents: which way the slots run
    rounding: float = 0.0          # rectangles and vents: radius of the corners (0 = sharp)
    strengthen: bool = False       # wall openings: a thicker frame around it on the inside

    @property
    def half_extents(self) -> tuple[float, float]:
        """Half the size along u and v (for a round hole: the radius twice).

        For a vent this is its whole area, so every placement rule treats the
        vent like one rectangle.
        """
        if self.kind == ROUND:
            return self.diameter / 2, self.diameter / 2
        return self.width / 2, self.height / 2

    @property
    def size_label(self) -> str:
        if self.kind == VENT:
            return f"vent {self.width:g} × {self.height:g} mm, {self.slot_count} slots"
        if self.kind == RECT:
            return f"{self.width:g} × {self.height:g} mm"
        return f"{self.diameter:g} mm"

    @property
    def slot_count(self) -> int:
        """How many slots of a vent fit across its area (at least one)."""
        across = self.width if self.slot_direction == ALONG_V else self.height
        if self.slot <= 0:
            return 1
        return max(1, int((across + self.gap + 1e-9) // (self.slot + self.gap)))

    def slot_rects(self) -> list[tuple[float, float, float, float]]:
        """A vent's slots as (du, dv, width, height): offsets in mm from its centre."""
        n, pitch = self.slot_count, self.slot + self.gap
        first = -(n - 1) * pitch / 2
        if self.slot_direction == ALONG_V:
            return [(first + i * pitch, 0.0, self.slot, self.height) for i in range(n)]
        return [(0.0, first + i * pitch, self.width, self.slot) for i in range(n)]


@dataclass(frozen=True)
class Screw:
    pilot: float          # hole the screw cuts its own thread into
    post: float           # outside diameter of a post or column around it
    nominal: float        # the screw's own diameter (M3 = 3 mm)

    @property
    def clearance(self) -> float:
        """Hole the screw slides through freely (in the lid)."""
        return self.nominal + 0.4


# Pilot holes are a little smaller than the screw so it cuts a thread into the
# plastic; posts are wide enough to leave a strong wall around the hole.
SCREWS = {
    "M1": Screw(pilot=0.9, post=3.5, nominal=1.0),
    "M2": Screw(pilot=1.7, post=5.0, nominal=2.0),
    "M2.5": Screw(pilot=2.2, post=6.0, nominal=2.5),
    "M3": Screw(pilot=2.6, post=7.0, nominal=3.0),
    "M4": Screw(pilot=3.5, post=9.0, nominal=4.0),
}

# Help for opening a push-on or snap-on lid, at the front.
OPENING_LABELS = {
    "none": "Nothing extra",
    "tab": "Tab on the lid",
    "notch": "Finger notch in the box",
    "both": "Tab and notch",
}
TAB_WIDTH, TAB_REACH = 20.0, 5.0            # lid tab: width, how far it sticks out
NOTCH_WIDTH, NOTCH_DEPTH = 16.0, 3.0        # finger notch in the top of the front wall

PUSH_ON, SNAP, SLIDING, SCREWED, THREADED = "push", "snap", "sliding", "screwed", "threaded"
LID_STYLE_LABELS = {
    PUSH_ON: "Push-on (friction fit)",
    SNAP: "Snap-on (clicks into place)",
    SLIDING: "Sliding (boxes only)",
    SCREWED: "Screwed down",
    THREADED: "Threaded (round containers only)",
}
THREAD_PITCH = 4.0     # mm the threaded lid moves per turn
THREAD_DEPTH = 1.2     # how far the thread stands out; with this pitch the flanks stay under 45°
THREAD_TURNS = 2.25    # length of the thread on the neck, in turns
CAP_WALL = 2.0         # wall of the threaded lid's skirt
CAP_TOP_GAP = 0.3      # room between the neck's rim and the inside of the lid's top
SNAP_BUMP = 0.5        # how far the snap-on lid's ridges stick out from its lip
SNAP_RIDGE = 1.2       # height of those ridges
SLIDE_TOP = 1.2        # wall left above a sliding lid's groove


@dataclass
class Lid:
    enabled: bool = False
    style: str = PUSH_ON           # PUSH_ON: lip that holds by friction; SCREWED: flat, with screws
    screw: str = "M3"              # screwed lids: key of SCREWS
    fit: str = "normal"            # key of FIT_PRESETS, or "custom"
    custom_gap: float = 0.25       # used when fit == "custom"
    thickness: float = 2.0         # thickness of the flat top
    lip_height: float = 5.0        # how far the lip reaches down into the box
    opening: str = "none"          # push-on and snap-on lids: key of OPENING_LABELS
    opening_side: str = FRONT      # where the tab and notch are: FRONT, BACK, LEFT or RIGHT
    slide_from: str = FRONT        # sliding lids: the side the lid slides in from

    @property
    def gap(self) -> float:
        if self.fit in FIT_PRESETS:
            return FIT_PRESETS[self.fit]
        return self.custom_gap


@dataclass
class Dividers:
    """Walls inside a box that split it into compartments, evenly or at set sizes."""
    across: int = 1                # compartments from left to right
    deep: int = 1                  # compartments from front to back
    thickness: float = 1.6
    height: float = 0.0            # 0 = full height; otherwise height above the bottom
    # Set sizes (inside, mm) of all but the last compartment, from the left and from
    # the front; the last one gets the rest. Empty = all the same size.
    widths: list[float] = field(default_factory=list)
    depths: list[float] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return self.across > 1 or self.deep > 1


@dataclass
class Mount:
    """Screw posts on the floor: a single post, or a set matching a circuit board.

    All posts of a set move and turn together. See mounts.py for the board
    catalogue and the placement rules.
    """
    board: str = "rpi-ab"          # key of mounts.BOARDS
    screw: str = "M2.5"            # key of mounts.SCREWS
    length: float = 6.0            # height of the posts above the floor
    u: float = 0.0                 # centre of the set: left/right
    v: float = 0.0                 # centre of the set: towards the back
    rotation: int = 0              # 0, 90, 180 or 270 degrees, seen from above
    # Only for custom boards (see mounts.CUSTOM_BOARDS):
    board_width: float = 60.0
    board_depth: float = 40.0
    spacing_x: float = 52.0        # distance between the holes, left to right
    spacing_y: float = 32.0        # distance between the holes, front to back
    #   (for a 1-hole board: where the hole is, measured from the board's middle)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    # Height of the tallest part on top of the board; boards stacked above need
    # this much room plus a little air. Negative = the board's usual value.
    parts_height: float = -1.0


@dataclass
class Project:
    shape: str = BOX
    size_mode: str = OUTSIDE       # do the numbers below describe outside or inside?
    width: float = 80.0            # box only
    depth: float = 60.0            # box only
    diameter: float = 60.0         # cylinder only
    height: float = 40.0           # height of the body, without the lid
    wall: float = 2.0
    bottom: float = 2.0
    corner_radius: float = 4.0     # box only, outside corners (seen from above)
    # Inside corners (walls to floor, and walls to each other in boxes): SHARP,
    # ROUNDED (a fillet) or ANGLED (a 45° chamfer). Both make the corners stronger.
    inside_corners: str = "sharp"
    inside_corner_size: float = 2.0
    lid: Lid = field(default_factory=Lid)
    holes: list[Hole] = field(default_factory=list)
    name: str = "My box"
    dividers: Dividers = field(default_factory=Dividers)   # boxes only
    mounts: list[Mount] = field(default_factory=list)
    # The template this design was started from ("" = none). Choosing Box or Round
    # container then starts over with a plain one rather than reshaping the template.
    # Older versions ignore it, so files stay readable there.
    template: str = ""

    def mount(self, mount_id: str) -> Mount | None:
        return next((m for m in self.mounts if m.id == mount_id), None)

    # ---- derived measurements -------------------------------------------
    def _to_outer(self, value: float, walls: float) -> float:
        return value + walls if self.size_mode == INSIDE else value

    @property
    def outer_width(self) -> float:
        if self.shape == CYLINDER:
            return self.outer_diameter
        return self._to_outer(self.width, 2 * self.wall)

    @property
    def outer_depth(self) -> float:
        if self.shape == CYLINDER:
            return self.outer_diameter
        return self._to_outer(self.depth, 2 * self.wall)

    @property
    def outer_diameter(self) -> float:
        return self._to_outer(self.diameter, 2 * self.wall)

    @property
    def outer_height(self) -> float:
        return self._to_outer(self.height, self.bottom)

    @property
    def inner_width(self) -> float:
        return self.outer_width - 2 * self.wall

    @property
    def inner_depth(self) -> float:
        return self.outer_depth - 2 * self.wall

    @property
    def inner_height(self) -> float:
        return self.outer_height - self.bottom

    @property
    def outer_corner_radius(self) -> float:
        if self.shape == CYLINDER:
            return self.outer_diameter / 2
        return max(0.0, min(self.corner_radius,
                            self.outer_width / 2, self.outer_depth / 2))

    @property
    def inner_corner_radius(self) -> float:
        """Rounding of the inside vertical corners, seen from above."""
        return max(0.0, self.outer_corner_radius - self.wall, inside_fillet(self))

    @property
    def closed_height(self) -> float:
        """Total height with the lid on."""
        if not self.lid.enabled or self.lid.style == SLIDING:
            return self.outer_height           # a sliding lid sits inside the walls
        if self.lid.style == THREADED and self.shape == CYLINDER:
            return self.outer_height + CAP_TOP_GAP + self.lid.thickness
        return self.outer_height + self.lid.thickness

    def surfaces(self) -> tuple[str, ...]:
        surfaces = BOX_SURFACES if self.shape == BOX else CYLINDER_SURFACES
        if not self.lid.enabled:
            surfaces = tuple(s for s in surfaces if s != LID)
        return surfaces

    def hole(self, hole_id: str) -> Hole | None:
        return next((h for h in self.holes if h.id == hole_id), None)

    def set_shape(self, shape: str) -> None:
        """Change the base shape, moving wall holes to the matching wall."""
        if shape == self.shape:
            return
        angles = {FRONT: 0.0, RIGHT: 90.0, BACK: 180.0, LEFT: -90.0}
        if shape == CYLINDER:
            # Keep the overall footprint similar.
            self.diameter = round(min(self.width, self.depth), 2)
            self.shape = shape
            radius = self.outer_diameter / 2
            for hole in self.holes:
                if hole.surface in angles:
                    # Turn a sideways offset (mm) into the matching angle.
                    a = angles[hole.surface] + math.degrees(hole.u / radius)
                    hole.surface, hole.u = SIDE, round((a + 180.0) % 360.0 - 180.0, 1)
        else:
            radius = self.outer_diameter / 2
            self.width = self.depth = self.diameter
            self.shape = shape
            for hole in self.holes:
                if hole.surface == SIDE:
                    a = (hole.u + 180.0) % 360.0 - 180.0
                    hole.surface = (FRONT if -45 <= a < 45 else RIGHT if 45 <= a < 135
                                    else LEFT if -135 <= a < -45 else BACK)
                    offset = (a - angles[hole.surface] + 180.0) % 360.0 - 180.0
                    hole.u = round(math.radians(offset) * radius, 1)

    def set_size_mode(self, mode: str) -> None:
        """Switch between outside/inside numbers without changing the object."""
        if mode == self.size_mode:
            return
        w, d, dia, h = (self.outer_width, self.outer_depth,
                        self.outer_diameter, self.outer_height)
        if mode == INSIDE:
            w, d, dia, h = (w - 2 * self.wall, d - 2 * self.wall,
                            dia - 2 * self.wall, h - self.bottom)
        self.size_mode = mode
        self.width, self.depth, self.diameter, self.height = (
            round(w, 2), round(d, 2), round(dia, 2), round(h, 2))


# ---------------------------------------------------------------------------
# Placement helpers shared by geometry, validation and the GUI.
# ---------------------------------------------------------------------------

def comfortable_margin(project: Project) -> float:
    """Material we would like to keep around a hole."""
    return max(1.5, project.wall)


SHARP, ROUNDED, ANGLED = "sharp", "rounded", "angled"
INSIDE_CORNER_LABELS = {SHARP: "Sharp (90°)", ROUNDED: "Rounded", ANGLED: "Angled (45°)"}


def inside_fillet(project: Project) -> float:
    """Size of the rounding or bevel in the inside corners (0 when they are sharp)."""
    return project.inside_corner_size if project.inside_corners != SHARP else 0.0


def corner_rounding(hole: Hole) -> float:
    """Radius actually used for the corners of a rectangular opening."""
    if hole.kind == ROUND:
        return 0.0
    return max(0.0, min(hole.rounding, *hole.half_extents))


FRAME_RIM = 2.0        # flat band of the strengthening frame around an opening


def frame_thickness(project: Project) -> float:
    """How far a strengthening frame stands out from the inside of the wall."""
    return max(1.2, min(project.wall, 3.0))


def has_frame(project: Project, hole: Hole) -> bool:
    return hole.strengthen and hole.surface in (FRONT, BACK, LEFT, RIGHT, SIDE)


def divider_fillet(project: Project) -> float:
    """Rounding where dividers meet the floor and the walls (0 if they stay sharp)."""
    f = inside_fillet(project)
    if f <= 0 or not has_dividers(project):
        return 0.0
    if divider_top(project) - project.bottom < f + 1.0:
        return 0.0      # too low to round: the joints stay sharp
    return f


def floor_inset(project: Project, height: float) -> float:
    """How far the inside corner reaches in from the wall, `height` mm above the floor."""
    f = inside_fillet(project)
    if f <= 0 or height >= f:
        return 0.0
    if project.inside_corners == ANGLED:
        return f - height
    return f - math.sqrt(f * f - (f - height) ** 2)


def has_lip(project: Project) -> bool:
    """Push-on and snap-on lids have a lip that reaches down inside the walls."""
    return project.lid.enabled and project.lid.style in (PUSH_ON, SNAP)


def has_lid_tab(project: Project) -> bool:
    return has_lip(project) and project.lid.opening in ("tab", "both")


def has_finger_notch(project: Project) -> bool:
    return has_lip(project) and project.lid.opening in ("notch", "both")


# The sides a lid can slide in from, or where its tab and notch can be. The angle
# turns something made at the front (facing -y) to that side, seen from above.
SIDE_LABELS = {FRONT: "Front", BACK: "Back", LEFT: "Left", RIGHT: "Right"}
SIDE_ANGLES = {FRONT: 0.0, RIGHT: 90.0, BACK: 180.0, LEFT: -90.0}


def side_span(project: Project, side: str) -> tuple[float, float]:
    """(Length of that side, distance from the middle to it), measured outside."""
    if project.shape != BOX:
        return project.outer_diameter, project.outer_diameter / 2
    if side in (FRONT, BACK):
        return project.outer_width, project.outer_depth / 2
    return project.outer_depth, project.outer_width / 2


def notch_size(project: Project) -> tuple[float, float]:
    """Width and depth of the finger notch (it stays within the lid's lip)."""
    length, _ = side_span(project, project.lid.opening_side)
    return (min(NOTCH_WIDTH, 0.4 * length),
            max(0.0, min(NOTCH_DEPTH, project.lid.lip_height - 0.5)))


def has_threaded_lid(project: Project) -> bool:
    return project.lid.enabled and project.lid.style == THREADED and project.shape == CYLINDER


@dataclass(frozen=True)
class ThreadSizes:
    """Measurements of a threaded neck and lid (radii and heights in mm)."""
    outer: float           # outside of the container and of the lid
    crest: float           # outside of the neck's thread
    root: float            # neck surface between the thread turns
    opening: float         # inside of the neck
    clearance: float       # room between the threads of neck and lid
    shoulder: float        # height where the neck starts
    slope_bottom: float    # height where the inside starts narrowing towards the neck
    thread_from: float
    thread_to: float


def thread_sizes(project: Project) -> ThreadSizes:
    outer = project.outer_diameter / 2
    clearance = project.lid.gap + 0.2           # threads need a bit more room than a lip
    crest = outer - CAP_WALL - clearance
    root = crest - THREAD_DEPTH
    inside = outer - project.wall
    opening = min(root - max(1.6, project.wall), inside)
    h = project.outer_height
    shoulder = h - (THREAD_TURNS * THREAD_PITCH + 2.0)
    # Inside, the wall narrows towards the neck at 45° so it prints without support.
    slope_bottom = shoulder - (inside - opening)
    return ThreadSizes(outer, crest, root, opening, clearance, shoulder, slope_bottom,
                       shoulder + 1.0, h - 0.8)


def has_snap_lid(project: Project) -> bool:
    return project.lid.enabled and project.lid.style == SNAP


def has_sliding_lid(project: Project) -> bool:
    return project.lid.enabled and project.lid.style == SLIDING


def slide_engage(project: Project) -> float:
    """How far a sliding lid reaches into each side wall."""
    return round(project.wall / 2, 2)


def slide_groove(project: Project) -> tuple[float, float]:
    """(bottom, top) height of the groove a sliding lid runs in."""
    top = project.outer_height - SLIDE_TOP
    return top - project.lid.thickness - 2 * project.lid.gap, top


def lid_top_z(project: Project) -> float:
    """Height of the top face of the lid when it is on."""
    if has_threaded_lid(project):
        return project.outer_height + CAP_TOP_GAP + project.lid.thickness
    if has_sliding_lid(project):
        return slide_groove(project)[0] + project.lid.gap + project.lid.thickness
    return project.outer_height + project.lid.thickness


def lid_ceiling(project: Project) -> float:
    """Highest point things inside the box may reach without touching the lid."""
    if has_sliding_lid(project):
        return slide_groove(project)[0] - project.lid.gap    # under the sliding panel
    if has_threaded_lid(project):
        return thread_sizes(project).slope_bottom          # below the narrower neck
    if project.lid.enabled:
        return project.outer_height - project.lid.gap * 2   # just below the lid
    return project.outer_height


def wall_top_free(project: Project) -> float:
    """Highest point on the walls that holes may reach (below lips and grooves)."""
    if has_lip(project):
        return project.outer_height - project.lid.lip_height
    if has_sliding_lid(project):
        return slide_groove(project)[0]
    if has_threaded_lid(project):
        return thread_sizes(project).slope_bottom
    return project.outer_height


def has_screw_lid(project: Project) -> bool:
    return project.lid.enabled and project.lid.style == SCREWED


def lid_column_radius(project: Project) -> float:
    return SCREWS[project.lid.screw].post / 2


def lid_screw_positions(project: Project) -> list[tuple[float, float]]:
    """Where the screws of a screwed-down lid go: one column in each corner.

    Each column touches both walls of its corner (or, with rounded corners,
    the curve), so it fuses with the walls.
    """
    if not has_screw_lid(project):
        return []
    r = lid_column_radius(project)
    if project.shape == CYLINDER:
        reach = project.outer_diameter / 2 - project.wall - r
        return [(reach * math.cos(math.radians(a)), reach * math.sin(math.radians(a)))
                for a in (45.0, 135.0, 225.0, 315.0)]
    ri = project.inner_corner_radius
    hx, hy = project.inner_width / 2, project.inner_depth / 2
    if ri > r:
        inset = ri - (ri - r) / math.sqrt(2)      # tangent to the rounded corner
    else:
        inset = r                                 # tangent to both walls
    return [(sx * (hx - inset), sy * (hy - inset)) for sx in (-1, 1) for sy in (-1, 1)]


def lid_pilot_depth(project: Project) -> float:
    """How deep the screw holes in the columns go (never into the floor)."""
    return max(0.0, min(16.0, project.inner_height - 1.0))


def wall_corner_zone(project: Project, surface: str) -> float:
    """Distance from the end of a wall's inside face where holes can't go.

    That's the rounded corner, or the lid's screw column if it is bigger.
    """
    zone = project.inner_corner_radius
    positions = lid_screw_positions(project)
    if positions and project.shape != CYLINDER:
        r = lid_column_radius(project)
        if surface in (FRONT, BACK):
            zone = max(zone, project.inner_width / 2 - abs(positions[0][0]) + r)
        else:
            zone = max(zone, project.inner_depth / 2 - abs(positions[0][1]) + r)
    return zone


def lip_outer_offset(project: Project) -> float:
    """Inward offset from the box's inner wall to the outside of the lid lip."""
    return project.lid.gap


def lip_wall(project: Project) -> float:
    return max(1.2, project.wall)


def surface_frame(project: Project, surface: str):
    """Return (center, normal, right, up) vectors for a flat surface.

    `center` is on the outside face of the surface. For the round wall the
    frame depends on the angle, see side_frame().
    """
    w, d, h = project.outer_width, project.outer_depth, project.outer_height
    zc = h / 2
    frames = {
        FRONT: ((0, -d / 2, zc), (0, -1, 0), (1, 0, 0), (0, 0, 1)),
        BACK: ((0, d / 2, zc), (0, 1, 0), (-1, 0, 0), (0, 0, 1)),
        LEFT: ((-w / 2, 0, zc), (-1, 0, 0), (0, -1, 0), (0, 0, 1)),
        RIGHT: ((w / 2, 0, zc), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
        BOTTOM: ((0, 0, 0), (0, 0, -1), (1, 0, 0), (0, 1, 0)),
        LID: ((0, 0, lid_top_z(project)), (0, 0, 1), (1, 0, 0), (0, 1, 0)),
    }
    return frames[surface]


def side_frame(project: Project, angle_deg: float):
    r = project.outer_diameter / 2
    a = math.radians(angle_deg)
    n = (math.sin(a), -math.cos(a), 0.0)
    right = (math.cos(a), math.sin(a), 0.0)
    return ((n[0] * r, n[1] * r, project.outer_height / 2), n, right, (0, 0, 1))


def hole_center_3d(project: Project, hole: Hole) -> tuple:
    """Centre of the hole on the outside face, plus that face's normal."""
    if hole.surface == SIDE:
        c, n, right, up = side_frame(project, hole.u)
        return (c[0], c[1], c[2] + hole.v), n
    c, n, right, up = surface_frame(project, hole.surface)
    p = tuple(c[i] + right[i] * hole.u + up[i] * hole.v for i in range(3))
    return p, n


def wall_limits(project: Project, surface: str, diameter: float,
                margin: float = MIN_EDGE):
    """Allowed (u_min, u_max, v_min, v_max) for the centre of a round hole."""
    return extent_limits(project, surface, diameter / 2, diameter / 2, margin)


def hole_limits(project: Project, hole: Hole, margin: float = MIN_EDGE):
    """Allowed (u_min, u_max, v_min, v_max) for this hole's centre on its surface."""
    return extent_limits(project, hole.surface, *hole.half_extents, margin)


def extent_limits(project: Project, surface: str, half_u: float, half_v: float,
                  margin: float = MIN_EDGE):
    """Allowed (u_min, u_max, v_min, v_max) for the centre of an opening.

    `half_u`/`half_v` are half the opening's size along u and v. Returns None
    when it cannot fit on that surface at all. For bottom/lid surfaces this is
    the bounding rectangle; rounded corners are checked by flat_clearance().
    """
    if surface in (FRONT, BACK, LEFT, RIGHT, SIDE):
        z_lo = project.bottom + inside_fillet(project) + half_v + margin
        # Stay below the lid's lip or groove.
        z_hi = wall_top_free(project) - half_v - margin
        v_lo, v_hi = z_lo - project.outer_height / 2, z_hi - project.outer_height / 2
        if surface == SIDE:
            u_lo, u_hi = -180.0, 180.0
        else:
            span = project.inner_width if surface in (FRONT, BACK) else project.inner_depth
            half = span / 2 - wall_corner_zone(project, surface) - half_u - margin
            u_lo, u_hi = -half, half
    else:
        hw, hd = _flat_half_extents(project, surface)
        u_lo, u_hi = -(hw - half_u - margin), hw - half_u - margin
        v_lo, v_hi = -(hd - half_v - margin), hd - half_v - margin
    if u_lo > u_hi + 1e-9 or v_lo > v_hi + 1e-9:
        return None
    return u_lo, u_hi, v_lo, v_hi


def _flat_half_extents(project: Project, surface: str):
    """Half width/depth of the usable flat area of the bottom or lid."""
    hw, hd = project.inner_width / 2, project.inner_depth / 2
    if surface == BOTTOM:
        f = inside_fillet(project)                  # the curve up to the walls isn't flat
        hw, hd = hw - f, hd - f
    if surface == LID and has_lip(project):
        inset = lip_outer_offset(project) + lip_wall(project)
        hw, hd = hw - inset, hd - inset
    if surface == LID and has_threaded_lid(project):
        hw = hd = thread_sizes(project).opening        # holes go over the opening
    return hw, hd


def _flat_corner_radius(project: Project, surface: str) -> float:
    if project.shape == CYLINDER:
        hw, _ = _flat_half_extents(project, surface)
        return max(hw, 0.0)
    rad = project.inner_corner_radius
    if surface == BOTTOM:
        rad = max(0.0, rad - inside_fillet(project))
    if surface == LID and has_lip(project):
        rad = max(0.0, rad - lip_outer_offset(project) - lip_wall(project))
    return rad


def flat_clearance(project: Project, surface: str, u: float, v: float) -> float:
    """Distance from a point to the edge of the usable bottom/lid area.

    Positive = inside. Uses a rounded-rectangle distance so it is exact for
    both boxes with rounded corners and round containers.
    """
    hw, hd = _flat_half_extents(project, surface)
    rad = min(_flat_corner_radius(project, surface), hw, hd)
    qx = abs(u) - (hw - rad)
    qy = abs(v) - (hd - rad)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    inside = min(max(qx, qy), 0.0)
    return -(outside + inside - rad)


def _flat_hole_clearance(project: Project, hole: Hole, u: float, v: float) -> float:
    """Material between an opening at (u, v) and the edge of the bottom or lid."""
    hu, hv = hole.half_extents
    if hole.kind == ROUND:
        return flat_clearance(project, hole.surface, u, v) - hu
    # The usable area is convex, so the corners are the closest points.
    return min(flat_clearance(project, hole.surface, u + su * hu, v + sv * hv)
               for su in (-1, 1) for sv in (-1, 1))


def hole_edge_clearance(project: Project, hole: Hole) -> float:
    """Smallest amount of material between the hole and the end of its surface."""
    hu, hv = hole.half_extents
    if hole.surface in (BOTTOM, LID):
        return _flat_hole_clearance(project, hole, hole.u, hole.v)
    z = project.outer_height / 2 + hole.v
    z_lo = project.bottom + inside_fillet(project)
    z_hi = wall_top_free(project)
    clear = min(z - hv - z_lo, z_hi - (z + hv))
    if hole.surface != SIDE:
        span = project.inner_width if hole.surface in (FRONT, BACK) else project.inner_depth
        half = span / 2 - wall_corner_zone(project, hole.surface)
        clear = min(clear, half - abs(hole.u) - hu)
    return clear


def surface_offset_mm(project: Project, surface: str, du: float, dv: float) -> tuple[float, float]:
    """A (u, v) difference on a surface, in mm (turns angles on the round wall into arc length)."""
    if surface == SIDE:
        du = math.radians((du + 180.0) % 360.0 - 180.0) * project.outer_diameter / 2
    return du, dv


def _shape_gap(a: Hole, b: Hole, du: float, dv: float) -> float:
    """Gap in mm between two openings whose centres are (du, dv) mm apart.

    Negative means they overlap.
    """
    du, dv = abs(du), abs(dv)
    (au, av), (bu, bv) = a.half_extents, b.half_extents
    if a.kind == ROUND and b.kind == ROUND:
        return math.hypot(du, dv) - au - bu
    if a.kind != ROUND and b.kind != ROUND:
        gx, gy = du - au - bu, dv - av - bv
        return math.hypot(gx, gy) if gx > 0 and gy > 0 else max(gx, gy)
    rect, r = (a, bu) if a.kind != ROUND else (b, au)
    hu, hv = rect.half_extents
    dx, dy = max(du - hu, 0.0), max(dv - hv, 0.0)
    if dx == 0 and dy == 0:
        return -r
    return math.hypot(dx, dy) - r


def opening_gap(project: Project, a: Hole, b: Hole) -> float:
    """Material between two openings on the same surface, in mm (negative = overlap)."""
    du, dv = surface_offset_mm(project, a.surface, a.u - b.u, a.v - b.v)
    return _shape_gap(a, b, du, dv)


def point_near_opening(project: Project, hole: Hole, u: float, v: float, tolerance: float) -> bool:
    """Is the point (u, v) on the opening, or within `tolerance` mm of it?"""
    du, dv = surface_offset_mm(project, hole.surface, hole.u - u, hole.v - v)
    return _shape_gap(hole, Hole(kind=ROUND, diameter=0.0), du, dv) <= tolerance


def vent_openings(project: Project, hole: Hole) -> list[Hole]:
    """A vent's slots as separate rectangular openings on the same surface."""
    out = []
    for du, dv, w, h in hole.slot_rects():
        u = hole.u + (math.degrees(du / (project.outer_diameter / 2)) if hole.surface == SIDE else du)
        out.append(Hole(surface=hole.surface, kind=RECT, width=w, height=h, u=u, v=hole.v + dv,
                        rounding=hole.rounding))
    return out


def clamp_hole(project: Project, hole: Hole, margin: float | None = None) -> tuple[float, float] | None:
    """Nearest position to the hole's current one that keeps `margin` of material.

    Returns None if the hole cannot fit on its surface with that margin.
    """
    if margin is None:
        margin = comfortable_margin(project)
    limits = hole_limits(project, hole, margin)
    if limits is None:
        return None
    u_lo, u_hi, v_lo, v_hi = limits
    if hole.surface == SIDE:
        u = ((hole.u + 180.0) % 360.0) - 180.0
    else:
        u = min(max(hole.u, u_lo), u_hi)
    v = min(max(hole.v, v_lo), v_hi)
    if hole.surface in (BOTTOM, LID):
        # Pull the point towards the centre until it clears rounded corners.
        for _ in range(60):
            if _flat_hole_clearance(project, hole, u, v) >= margin - 1e-6:
                break
            u *= 0.97
            v *= 0.97
        else:
            return None
    return round(u, 2), round(v, 2)


DIVIDER_RANGE = (0.8, 10.0)
MAX_COMPARTMENTS = 12


def has_dividers(project: Project) -> bool:
    return project.shape == BOX and project.dividers.enabled


def has_set_sizes(sizes: list[float], count: int) -> bool:
    """Are the compartments in this direction set one by one (else all the same)?"""
    return count > 1 and len(sizes) == count - 1


def _sizes(span: float, count: int, thickness: float, chosen: list[float]) -> list[float]:
    room = span - (count - 1) * thickness
    if has_set_sizes(chosen, count):
        return list(chosen) + [room - sum(chosen)]          # the last one gets the rest
    return [room / count] * count


def compartment_widths(project: Project) -> list[float]:
    """Inside width of each compartment, from the left."""
    d = project.dividers
    return _sizes(project.inner_width, d.across, d.thickness, d.widths)


def compartment_depths(project: Project) -> list[float]:
    """Inside depth of each compartment, from the front."""
    d = project.dividers
    return _sizes(project.inner_depth, d.deep, d.thickness, d.depths)


def compartment_size(project: Project) -> tuple[float, float]:
    """Inside width and depth of the narrowest compartments."""
    return min(compartment_widths(project)), min(compartment_depths(project))


def resized_sizes(span: float, count: int, thickness: float, chosen: list[float]) -> list[float]:
    """Set sizes for a new number of compartments: keep the first ones, share the rest."""
    if count < 2:
        return []
    keep = list(chosen[:count - 1])
    room = span - (count - 1) * thickness - sum(keep)
    share = round(room / (count - len(keep)), 1)
    return keep + [share] * (count - 1 - len(keep))


def _positions(start: float, sizes: list[float], thickness: float) -> list[float]:
    out, edge = [], start
    for size in sizes[:-1]:
        edge += size
        out.append(edge + thickness / 2)
        edge += thickness
    return out


def divider_positions(project: Project) -> tuple[list[float], list[float]]:
    """Centre lines of the dividers: x positions (left-right split), y positions (front-back split)."""
    t = project.dividers.thickness
    return (_positions(-project.inner_width / 2, compartment_widths(project), t),
            _positions(-project.inner_depth / 2, compartment_depths(project), t))


def divider_top(project: Project) -> float:
    """Height (z) of the top of the dividers."""
    top = lid_ceiling(project)
    if project.dividers.height > 0:
        top = min(top, project.bottom + project.dividers.height)
    return top


TRAY_TEMPLATE = "tray"


def default_project(shape: str = BOX) -> Project:
    p = Project(shape=shape)
    if shape == TRAY_TEMPLATE:
        p.shape, p.name = BOX, "My tray"
        p.width, p.depth, p.height = 150.0, 100.0, 25.0
        p.wall = p.bottom = 1.6
        p.dividers = Dividers(across=3, deep=2)
    elif shape == CYLINDER:
        p.name = "My container"
        p.height = 80.0
    return p
