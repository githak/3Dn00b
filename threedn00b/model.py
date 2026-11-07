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

ROUND, RECT, VENT, NOTCH = "round", "rect", "vent", "notch"
HOLE_KIND_LABELS = {ROUND: "Round", RECT: "Rectangle", VENT: "Air vent", NOTCH: "Cable notch"}
# A cable notch is a slot down from the top of a wall, open at the top and round at the
# bottom, so a cable can come out with the lid on. Its width and height (depth from the
# top) are the hole's width and height; it always reaches the top of the wall.
WALL_SURFACES = (FRONT, BACK, LEFT, RIGHT, SIDE)
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
        if self.kind == NOTCH:
            return f"notch {self.width:g} mm wide, {self.height:g} mm deep"
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
    "M1.6": Screw(pilot=1.3, post=4.0, nominal=1.6),      # Arduino Nano holes are 1.65 to 1.8 mm
    "M2": Screw(pilot=1.7, post=5.0, nominal=2.0),
    "M2.5": Screw(pilot=2.2, post=6.0, nominal=2.5),
    "M3": Screw(pilot=2.6, post=7.0, nominal=3.0),
    "M4": Screw(pilot=3.5, post=9.0, nominal=4.0),
}

# Heat-set inserts: brass threads pressed into a hole with a hot soldering iron. Sizes for
# the common short inserts (hole diameter, hole depth), as their makers recommend.
@dataclass(frozen=True)
class Insert:
    hole: float
    depth: float


INSERTS = {
    "M2": Insert(hole=3.2, depth=4.0),
    "M2.5": Insert(hole=3.6, depth=5.0),
    "M3": Insert(hole=4.0, depth=6.0),
    "M4": Insert(hole=5.6, depth=8.5),
}
INSERT_WALL = 1.6        # plastic around an insert


def post_diameter(screw: str, inserts: bool = False) -> float:
    """Outside of a post or column for this screw: wider with a heat-set insert in it."""
    post = SCREWS[screw].post
    if inserts and screw in INSERTS:
        post = max(post, INSERTS[screw].hole + 2 * INSERT_WALL)
    return post


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
MAGNETS = "magnets"
LID_STYLE_LABELS = {
    PUSH_ON: "Push-on (friction fit)",
    SNAP: "Snap-on (clicks into place)",
    SLIDING: "Sliding (boxes only)",
    SCREWED: "Screwed down",
    MAGNETS: "Held by magnets",
    THREADED: "Threaded (round containers only)",
}


@dataclass(frozen=True)
class Magnet:
    diameter: float
    thickness: float


# Round neodymium magnets in their common sizes: diameter x thickness.
MAGNET_SIZES = {"5x2": Magnet(5.0, 2.0), "6x2": Magnet(6.0, 2.0), "6x3": Magnet(6.0, 3.0),
                "8x2": Magnet(8.0, 2.0), "8x3": Magnet(8.0, 3.0), "10x2": Magnet(10.0, 2.0),
                "10x3": Magnet(10.0, 3.0), "12x3": Magnet(12.0, 3.0)}
MAGNET_ROOM = 0.3     # a pocket is this much wider than its magnet (printed holes come out smaller)
MAGNET_GLUE = 0.2     # and this much deeper, for a drop of glue
MAGNET_WALL = 1.2     # plastic around a pocket in a corner column
MAGNET_SKIN = 0.8     # plastic left over a pocket in the lid
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
    inserts: bool = False          # screwed lids: heat-set inserts in the corner columns
    magnet: str = "6x3"            # lids held by magnets: key of MAGNET_SIZES

    @property
    def gap(self) -> float:
        if self.fit in FIT_PRESETS:
            return FIT_PRESETS[self.fit]
        return self.custom_gap


@dataclass
class Fixing:
    """Ways to fix the box in place: screw tabs at the bottom, and keyhole slots in the
    back to hang it on two screws in a wall."""
    tabs: bool = False
    keyholes: bool = False
    screw: float = 4.0             # size of the screws (mm across the thread)
    keyhole_spacing: float = 0.0   # between the two keyholes; 0 = as far apart as fits


FIXING_SCREWS = (3.0, 3.5, 4.0, 5.0)


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
    length: float = 6.0            # how far the posts reach out from the floor (or the lid)
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
    inserts: bool = False          # heat-set inserts in the posts instead of plain holes
    surface: str = BOTTOM          # BOTTOM: posts stand on the floor; LID: they hang under the lid


# Text on the outside of a surface: standing out (raised), cut in (engraved), or cut
# right through, like a stencil.
RAISED, ENGRAVED, CUT_THROUGH = "raised", "engraved", "cut"
LABEL_STYLE_LABELS = {RAISED: "Raised", ENGRAVED: "Engraved", CUT_THROUGH: "Cut through"}
LABEL_SIZE_RANGE = (2.0, 80.0)     # height of the capital letters (mm)
LABEL_DEPTH_RANGE = (0.2, 3.0)
LABEL_MARGIN = 1.0                 # keep this far from the edges of the surface
LABEL_MIN_SIZE = 5.0               # smaller letters are hard to print clearly


@dataclass
class Label:
    """A line of text on the outside of a wall, the bottom or the lid."""
    text: str = "Text"
    surface: str = FRONT
    style: str = RAISED
    size: float = 8.0              # height of the capital letters (mm)
    depth: float = 0.6             # how far it stands out, or is cut in (mm); not used
                                   # for text cut right through
    u: float = 0.0                 # where its middle is, measured like a hole's position
    v: float = 0.0
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


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
    fixing: Fixing = field(default_factory=Fixing)
    mounts: list[Mount] = field(default_factory=list)
    # The template this design was started from ("" = none). Choosing Box or Round
    # container then starts over with a plain one rather than reshaping the template.
    # Older versions ignore it, so files stay readable there.
    template: str = ""
    labels: list[Label] = field(default_factory=list)

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

    def label(self, label_id: str) -> Label | None:
        return next((t for t in self.labels if t.id == label_id), None)

    def set_shape(self, shape: str) -> None:
        """Change the base shape, moving wall holes and text to the matching wall."""
        if shape == self.shape:
            return
        angles = {FRONT: 0.0, RIGHT: 90.0, BACK: 180.0, LEFT: -90.0}
        if shape == CYLINDER:
            # Keep the overall footprint similar.
            self.diameter = round(min(self.width, self.depth), 2)
            self.shape = shape
            radius = self.outer_diameter / 2
            for hole in self.holes + self.labels:
                if hole.surface in angles:
                    # Turn a sideways offset (mm) into the matching angle.
                    a = angles[hole.surface] + math.degrees(hole.u / radius)
                    hole.surface, hole.u = SIDE, round((a + 180.0) % 360.0 - 180.0, 1)
        else:
            radius = self.outer_diameter / 2
            self.width = self.depth = self.diameter
            self.shape = shape
            for hole in self.holes + self.labels:
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
    if hole.kind == NOTCH:
        return min(hole.half_extents)                   # a round bottom, for the cable
    return max(0.0, min(hole.rounding, *hole.half_extents))


FRAME_RIM = 2.0        # flat band of the strengthening frame around an opening


def frame_thickness(project: Project) -> float:
    """How far a strengthening frame stands out from the inside of the wall."""
    return max(1.2, min(project.wall, 3.0))


def has_frame(project: Project, hole: Hole) -> bool:
    return hole.strengthen and hole.kind != NOTCH and hole.surface in WALL_SURFACES


def notch_v(project: Project, hole: Hole) -> float:
    """Where a cable notch's middle is (v): it reaches down from the top of the wall, or
    of the divider it is in."""
    if is_divider_surface(hole.surface):
        return divider_top(project) - project.outer_height / 2 - hole.height / 2
    return project.outer_height / 2 - hole.height / 2


def fix_notches(project: Project) -> None:
    """Keep cable notches at the top of their wall (after the height or depth changes)."""
    for hole in project.holes:
        if hole.kind == NOTCH:
            hole.v = round(notch_v(project, hole), 3)


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


def has_easy_opening(project: Project) -> bool:
    """Lids that can have a tab and a finger notch: those that sit on the walls and lift off."""
    return has_lip(project) or has_magnet_lid(project)


def has_lid_tab(project: Project) -> bool:
    return has_easy_opening(project) and project.lid.opening in ("tab", "both")


def has_finger_notch(project: Project) -> bool:
    return has_easy_opening(project) and project.lid.opening in ("notch", "both")


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


def has_magnet_lid(project: Project) -> bool:
    return project.lid.enabled and project.lid.style == MAGNETS


def has_corner_columns(project: Project) -> bool:
    """Screwed-down lids and lids held by magnets need a column in each corner."""
    return has_screw_lid(project) or has_magnet_lid(project)


def magnet_pocket(project: Project) -> tuple[float, float]:
    """(Diameter, depth) of the pockets the lid's magnets go in."""
    m = MAGNET_SIZES[project.lid.magnet]
    return m.diameter + MAGNET_ROOM, m.thickness + MAGNET_GLUE


def magnet_lid_thickness(project: Project) -> float:
    """The thinnest lid that holds its magnets with plastic over them."""
    return magnet_pocket(project)[1] + MAGNET_SKIN


def lid_column_radius(project: Project) -> float:
    if has_magnet_lid(project):
        return magnet_pocket(project)[0] / 2 + MAGNET_WALL
    return post_diameter(project.lid.screw, project.lid.inserts) / 2


def lid_column_positions(project: Project) -> list[tuple[float, float]]:
    """Where the columns of a screwed-down lid, or of a lid held by magnets, go: one in
    each corner.

    Each column touches both walls of its corner (or, with rounded corners,
    the curve), so it fuses with the walls.
    """
    if not has_corner_columns(project):
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

    That's the rounded corner, or the lid's corner column if it is bigger.
    """
    zone = project.inner_corner_radius
    positions = lid_column_positions(project)
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


# A divider can hold cable notches too. Its "surface" is named after the dividers'
# direction and number: "divider-x1" is the first divider from the left (it runs from
# front to back, at an x position), "divider-y1" the first from the front.
DIVIDER_PREFIX = "divider-"


def divider_surfaces(project: Project) -> list[str]:
    """The dividers that are there now, as surfaces for cable notches."""
    if not has_dividers(project):
        return []
    xs, ys = divider_positions(project)
    return ([f"{DIVIDER_PREFIX}x{i + 1}" for i in range(len(xs))]
            + [f"{DIVIDER_PREFIX}y{i + 1}" for i in range(len(ys))])


def is_divider_surface(surface: str) -> bool:
    return surface.startswith(DIVIDER_PREFIX)


def divider_place(project: Project, surface: str) -> tuple[str, float] | None:
    """For a divider surface: ("x", its x position) or ("y", its y position); None when
    that divider isn't there (any more)."""
    if not is_divider_surface(surface) or surface not in divider_surfaces(project):
        return None
    axis, number = surface[len(DIVIDER_PREFIX)], int(surface[len(DIVIDER_PREFIX) + 1:])
    xs, ys = divider_positions(project)
    return axis, (xs if axis == "x" else ys)[number - 1]


def hole_surfaces(project: Project) -> tuple[str, ...]:
    """Everywhere a hole can be now: the surfaces, and the dividers (for cable notches)."""
    return tuple(project.surfaces()) + tuple(divider_surfaces(project))


def surface_label(project: Project, surface: str) -> str:
    """The name of a surface for people: "Front wall", "Divider 2 (between compartments 2
    and 3)" ..."""
    if not is_divider_surface(surface):
        return SURFACE_LABELS.get(surface, surface)
    axis, number = surface[len(DIVIDER_PREFIX)], surface[len(DIVIDER_PREFIX) + 1:]
    xs, ys = divider_positions(project) if has_dividers(project) else ([], [])
    if xs and ys:
        return f"{'Front-to-back' if axis == 'x' else 'Side-to-side'} divider {number}"
    if number.isdigit():
        return f"Divider {number} (between compartments {number} and {int(number) + 1})"
    return f"Divider {number}"


def surface_frame(project: Project, surface: str):
    """Return (center, normal, right, up) vectors for a flat surface.

    `center` is on the outside face of the surface. For the round wall the
    frame depends on the angle, see side_frame(). A divider's frame is like the
    right wall's (u from front to back) or the front wall's (u from left to right),
    on the divider's right or front face.
    """
    w, d, h = project.outer_width, project.outer_depth, project.outer_height
    zc = h / 2
    place = divider_place(project, surface) if is_divider_surface(surface) else None
    if place is not None:
        t = project.dividers.thickness
        axis, at = place
        if axis == "x":
            return (at + t / 2, 0, zc), (1, 0, 0), (0, 1, 0), (0, 0, 1)
        return (0, at - t / 2, zc), (0, -1, 0), (1, 0, 0), (0, 0, 1)
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
    return extent_limits(project, hole.surface, *hole.half_extents, margin,
                         notch=hole.kind == NOTCH)


def extent_limits(project: Project, surface: str, half_u: float, half_v: float,
                  margin: float = MIN_EDGE, notch: bool = False):
    """Allowed (u_min, u_max, v_min, v_max) for the centre of an opening.

    `half_u`/`half_v` are half the opening's size along u and v. Returns None
    when it cannot fit on that surface at all. For bottom/lid surfaces this is
    the bounding rectangle; rounded corners are checked by flat_clearance().
    A cable notch (`notch`) only moves sideways: it always reaches the top.
    """
    if is_divider_surface(surface):
        return _divider_notch_limits(project, surface, half_u, half_v, margin) if notch else None
    if surface not in WALL_SURFACES and notch:
        return None
    if surface in WALL_SURFACES:
        z_lo = project.bottom + inside_fillet(project) + half_v + margin
        # Stay below the lid's lip or groove.
        z_hi = wall_top_free(project) - half_v - margin
        if notch:
            bottom = project.outer_height - 2 * half_v
            if bottom < project.bottom + inside_fillet(project) + margin - 1e-9:
                return None                           # so deep it would reach the floor
            z_lo = z_hi = project.outer_height - half_v
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


def divider_end_zone(project: Project) -> float:
    """How far from the outer walls a notch in a divider must stay: clear of the rounded
    joint, and of the gap the divider has for a lid's lip."""
    zone = divider_fillet(project)
    if has_lip(project):
        zone += lip_outer_offset(project) + lip_wall(project)
    return zone


def _divider_notch_limits(project: Project, surface: str, half_u: float, half_v: float,
                          margin: float):
    place = divider_place(project, surface)
    if place is None:
        return None
    top = divider_top(project)
    if top - 2 * half_v < project.bottom + divider_fillet(project) + margin - 1e-9:
        return None                                   # so deep it would reach the floor
    v = top - half_v - project.outer_height / 2
    span = project.inner_depth if place[0] == "x" else project.inner_width
    half = span / 2 - divider_end_zone(project) - half_u - margin
    if half < -1e-9:
        return None
    return -half, half, v, v


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
    if is_divider_surface(hole.surface):
        place = divider_place(project, hole.surface)
        if place is None:
            return -1.0
        z = project.outer_height / 2 + hole.v
        span = project.inner_depth if place[0] == "x" else project.inner_width
        half = span / 2 - divider_end_zone(project)
        return min(z - hv - (project.bottom + divider_fillet(project)), half - abs(hole.u) - hu)
    z = project.outer_height / 2 + hole.v
    z_lo = project.bottom + inside_fillet(project)
    z_hi = wall_top_free(project)
    clear = min(z - hv - z_lo, z_hi - (z + hv))
    if hole.kind == NOTCH:                      # open at the top on purpose
        clear = z - hv - z_lo
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


# ---- text labels ---------------------------------------------------------

def label_half_extents(label: Label) -> tuple[float, float]:
    """Half the size of the text (mm) to each side of its middle: across, and up/down."""
    from .text import text_size
    x0, y0, x1, y1 = text_size(label.text, label.size)
    return max(-x0, x1), max(-y0, y1)


def label_thickness(project: Project, surface: str) -> float:
    """How thick the plastic under text on this surface is (for engraving)."""
    if surface == BOTTOM:
        return project.bottom
    if surface == LID:
        return project.lid.thickness
    return project.wall


def label_limits(project: Project, label: Label, margin: float = LABEL_MARGIN):
    """Allowed (u_min, u_max, v_min, v_max) for the middle of the text, or None."""
    hu, hv = label_half_extents(label)
    if label.surface == SIDE:
        radius = project.outer_diameter / 2
        if hu <= 0 or 2 * hu / radius > math.pi:       # more than halfway round
            return None
    return extent_limits(project, label.surface, hu, hv, margin)


def label_clear_of_corners(project: Project, label: Label, u: float, v: float,
                           margin: float = LABEL_MARGIN) -> bool:
    """On the bottom or the lid: do the text's corners stay off the rounded edge?"""
    if label.surface not in (BOTTOM, LID):
        return True
    hu, hv = label_half_extents(label)
    return all(flat_clearance(project, label.surface, u + su * hu, v + sv * hv) >= margin - 1e-6
               for su in (-1, 1) for sv in (-1, 1))


def clamp_label(project: Project, label: Label, margin: float = LABEL_MARGIN) -> tuple[float, float] | None:
    """Nearest position that keeps the whole text on its surface, or None if it can't fit."""
    limits = label_limits(project, label, margin)
    if limits is None:
        return None
    u_lo, u_hi, v_lo, v_hi = limits
    u = ((label.u + 180.0) % 360.0) - 180.0 if label.surface == SIDE else min(max(label.u, u_lo), u_hi)
    v = min(max(label.v, v_lo), v_hi)
    for _ in range(80):
        if label_clear_of_corners(project, label, u, v, margin):
            return round(u, 2), round(v, 2)
        u *= 0.97
        v *= 0.97
    return None


# ---- fixing the box in place -----------------------------------------------

def screw_head(screw: float) -> float:
    """Room for the head of a common wood or machine screw of this size."""
    return 2.0 * screw + 0.5


def screw_clearance(screw: float) -> float:
    """A hole the screw slides through."""
    return screw + 0.5


@dataclass(frozen=True)
class TabSizes:
    width: float            # along the wall
    reach: float            # how far it sticks out from the wall
    thickness: float
    hole: float             # screw hole
    hole_from_wall: float   # middle of the hole, from the outside of the wall


def tab_sizes(project: Project) -> TabSizes:
    screw = project.fixing.screw
    width = 4.0 * screw + 2.0
    reach = 3.0 * screw + 3.0
    return TabSizes(width, reach, max(project.bottom, 3.0), screw_clearance(screw),
                    reach - width / 2)


def tab_positions(project: Project) -> list[tuple[float, float, float]]:
    """Where the screw tabs go: (x, y, outward angle in degrees), at the left and right."""
    if not project.fixing.tabs:
        return []
    if project.shape == BOX:
        return [(-project.outer_width / 2, 0.0, 180.0), (project.outer_width / 2, 0.0, 0.0)]
    r = project.outer_diameter / 2
    return [(-r, 0.0, 180.0), (r, 0.0, 0.0)]


@dataclass(frozen=True)
class KeyholeSizes:
    head: float             # the big round hole the screw head goes through
    slot: float             # the slot the screw slides up into
    length: float           # from the middle of the big hole to the top end of the slot
    v: float                # where the middle of the big hole is (v on the back wall)


KEYHOLE_SURFACE = {BOX: BACK, CYLINDER: SIDE}
KEYHOLE_MAX_ANGLE = 20.0     # round containers: how far round from the back a keyhole may be


def keyhole_sizes(project: Project) -> KeyholeSizes | None:
    """Sizes and height of the keyholes, or None when the back wall is too low for them."""
    screw = project.fixing.screw
    head, slot = screw_head(screw), screw_clearance(screw)
    length = head
    top = wall_top_free(project) - 2.5                       # top of the slot
    v_mid = top - slot / 2 - length
    if v_mid - head / 2 < project.bottom + inside_fillet(project) + 2.0:
        return None
    return KeyholeSizes(head, slot, length, v_mid - project.outer_height / 2)


def keyhole_max_spacing(project: Project) -> float:
    """The furthest apart two keyholes can be (mm), keeping clear of the corners."""
    sizes = keyhole_sizes(project)
    if sizes is None:
        return 0.0
    if project.shape == BOX:
        half = project.inner_width / 2 - wall_corner_zone(project, BACK) - sizes.head / 2 - 2.0
    else:
        # Within 20° of the back, so the screws in the wall go straight into the keyholes.
        half = project.outer_diameter / 2 * math.sin(math.radians(KEYHOLE_MAX_ANGLE))
    return max(0.0, 2 * half)


def keyhole_spacing(project: Project) -> float:
    """The spacing used: the one asked for, or as far apart as fits (0 = just one)."""
    asked = project.fixing.keyhole_spacing
    if asked > 0:
        return asked
    best = keyhole_max_spacing(project)
    sizes = keyhole_sizes(project)
    return best if sizes is not None and best >= 2 * sizes.head else 0.0


def keyhole_openings(project: Project) -> list[Hole]:
    """The keyholes as openings in the back: a round hole and a slot above it, each."""
    if not project.fixing.keyholes:
        return []
    sizes = keyhole_sizes(project)
    if sizes is None:
        return []
    spacing = keyhole_spacing(project)
    offsets = [0.0] if spacing <= 0 else [-spacing / 2, spacing / 2]
    surface = KEYHOLE_SURFACE[project.shape]
    out = []
    for du in offsets:
        # The spacing is straight across (as the screws in the wall are), also on a round wall.
        u = du if project.shape == BOX else \
            180.0 + math.degrees(math.asin(max(-1.0, min(1.0, du / (project.outer_diameter / 2)))))
        out.append(Hole(surface=surface, diameter=sizes.head, u=u, v=sizes.v))
        out.append(Hole(surface=surface, kind=RECT, width=sizes.slot,
                        height=sizes.length + sizes.slot, u=u,
                        v=sizes.v + (sizes.length + sizes.slot) / 2 - sizes.slot / 2,
                        rounding=sizes.slot / 2))
    return out
