"""Geometry engine: turns a Project into watertight solids using Manifold.

Manifold guarantees closed ("watertight") results for every Boolean
operation, which is exactly what a slicer needs from an STL file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from manifold3d import CrossSection, Error, JoinType, Manifold, OpType

from .model import (RAISED, TAB_REACH, TAB_WIDTH, ANGLED, BACK, BOTTOM, BOX, CAP_TOP_GAP, CYLINDER, FRAME_RIM, FRONT, LEFT,
                    LID, RIGHT, ROUND, SCREWED, SCREWS, SIDE, SLIDING, SNAP_BUMP, SNAP_RIDGE, THREADED, THREAD_DEPTH,
                    THREAD_PITCH, VENT, Hole, Project, corner_rounding, divider_fillet,
                    divider_positions, divider_top, floor_inset, frame_thickness,
                    has_dividers, has_finger_notch, has_frame, has_lid_tab, has_lip, has_screw_lid, has_sliding_lid,
                    has_snap_lid, has_threaded_lid, inside_fillet, lid_ceiling, lid_pilot_depth,
                    notch_size, SIDE_ANGLES, side_span,
                    lid_screw_positions, lid_top_z, lip_outer_offset, lip_wall, slide_engage,
                    slide_groove, surface_frame, thread_sizes, vent_openings)


@dataclass
class Parts:
    body: Manifold
    lid: Manifold | None = None   # in assembled position (sitting on the body)

    def printable(self) -> dict[str, Manifold]:
        """Parts positioned for printing: flat side down, centred on the plate."""
        out = {"body": _on_plate(self.body)}
        if self.lid is not None:
            # Print the lid upside down: its flat top on the build plate.
            out["lid"] = _on_plate(self.lid.rotate([180.0, 0.0, 0.0]))
        return out


def _on_plate(m: Manifold) -> Manifold:
    lo, hi = _bounds(m)
    return m.translate([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])


def _bounds(m: Manifold):
    b = m.bounding_box()
    return b[:3], b[3:]


def _circle_segments(radius: float, edge: float = 0.8, lo: int = 32, hi: int = 360) -> int:
    n = int(round(2 * math.pi * radius / edge))
    return max(lo, min(hi, n - n % 4))


def footprint(project: Project, inset: float = 0.0) -> CrossSection | None:
    """Outline of the object seen from above, shrunk by `inset` mm."""
    if project.shape == CYLINDER:
        r = project.outer_diameter / 2 - inset
        if r <= 0:
            return None
        return CrossSection.circle(r, _circle_segments(r))
    w = project.outer_width - 2 * inset
    d = project.outer_depth - 2 * inset
    if w <= 0 or d <= 0:
        return None
    rad = project.outer_corner_radius - inset
    if inset >= project.wall:
        # Inside the walls, corners are at least as round as the inside corners.
        rad = max(rad, inside_fillet(project) - (inset - project.wall))
    rad = max(0.0, min(rad, w / 2, d / 2))
    core_w, core_d = w - 2 * rad, d - 2 * rad
    if rad < 0.05:
        return CrossSection.square([w, d], center=True)
    if core_w < 1e-3 or core_d < 1e-3:
        # Fully rounded: a stadium or circle.
        core = CrossSection.square([max(core_w, 1e-3), max(core_d, 1e-3)], center=True)
    else:
        core = CrossSection.square([core_w, core_d], center=True)
    return core.offset(rad, JoinType.Round, circular_segments=_circle_segments(rad, 0.5, 16, 128))


def _cavity(project: Project) -> Manifold | None:
    """The inside of the box, with the floor edge rounded or angled if asked for.

    The inside is convex, so with a rounded or angled floor edge it is built as
    one convex hull of outlines that shrink towards the floor.
    """
    h, z0 = project.outer_height, project.bottom
    f = min(inside_fillet(project), h - z0)
    inner = footprint(project, project.wall)
    if inner is None or f <= 0:
        return _prism(inner, h - z0 + 1.0, z0)
    steps = 1 if project.inside_corners == ANGLED else max(6, min(16, math.ceil(f * 3)))
    points = _outline_points(inner, h + 1.0)
    for i in range(steps + 1):
        height = f * i / steps
        outline = footprint(project, project.wall + floor_inset(project, height))
        if outline is not None:
            points += _outline_points(outline, z0 + height)
    return Manifold.hull_points(points)


FUSE = 0.02    # how far rounded dividers reach into the walls and the floor


def _divider_outline(project: Project, grow: float = 0.0) -> CrossSection | None:
    """The dividers seen from above, each made `grow` mm thicker on both sides."""
    xs, ys = divider_positions(project)
    t = project.dividers.thickness + 2 * grow
    w, d = project.outer_width, project.outer_depth
    strips = [CrossSection.square([t, d], center=True).translate([x, 0.0]) for x in xs]
    strips += [CrossSection.square([w, t], center=True).translate([0.0, y]) for y in ys]
    return CrossSection.batch_boolean(strips, OpType.Add) if strips else None


def _rounded_dividers(project: Project) -> Manifold | None:
    """Dividers whose joints with the floor, the walls and each other are rounded or
    angled like the inside corners.

    Every compartment is convex (rounded floor edge included), so the space in it
    near the floor is one convex hull of outlines shrinking towards the floor.
    The solid reaches a hair into the walls and the floor, so it fuses with them
    without any faces lying exactly on top of each other.
    """
    f, z0 = divider_fillet(project), project.bottom
    top = min(divider_top(project), project.outer_height - FUSE)   # not level with the rim
    base = footprint(project, project.wall - FUSE)
    dividers = _divider_outline(project)
    if base is None or dividers is None:
        return None
    seg = _circle_segments(f, 0.5, 16, 128)
    # Rounding every inside corner of a compartment is the same as rounding the
    # joints in the plan view: shrink, then grow back with round corners.
    rooms = (base - dividers).offset(-f, JoinType.Round, circular_segments=seg) \
        .offset(f, JoinType.Round, circular_segments=seg)
    upright = _prism(base - rooms, top - z0 - f, z0 + f)
    steps = 1 if project.inside_corners == ANGLED else max(6, min(16, math.ceil(f * 3)))
    hulls = []
    for room in rooms.decompose():
        points = _outline_points(room, z0 + f + 1.0)
        for i in range(steps + 1):
            height = f * i / steps
            inset = floor_inset(project, height)
            outline = room.offset(-inset, JoinType.Round, circular_segments=seg) if inset > 0 else room
            points += _outline_points(outline, z0 + height)
        hulls.append(Manifold.hull_points(points))
    low = _prism(base, f, z0) - Manifold.batch_boolean(hulls, OpType.Add)
    walls = low + upright if upright is not None else low
    # Only near the dividers: elsewhere this would just be a skin on the walls.
    return walls ^ _prism(_divider_outline(project, f + 1.0), top + 1.0, z0 - 1.0)


def _outline_points(section: CrossSection, z: float) -> list[list[float]]:
    return [[x, y, z] for polygon in section.to_polygons() for x, y in polygon]


def _lip_ring(project: Project, into_wall: float = 0.0) -> Manifold | None:
    """Room inside the walls that the lid's lip needs (nothing may stand there)."""
    if not has_lip(project):
        return None
    gap = project.lid.gap
    inner = footprint(project, project.wall - into_wall)
    clear = footprint(project, project.wall + lip_outer_offset(project) + lip_wall(project) + gap)
    z_notch = project.outer_height - project.lid.lip_height - gap
    ring = _prism(inner, project.outer_height - z_notch + 1.0, z_notch)
    if ring is not None and clear is not None:
        ring = ring - _prism(clear, project.outer_height - z_notch + 2.0, z_notch - 0.5)
    return ring


def _prism(section: CrossSection | None, height: float, z0: float) -> Manifold | None:
    if section is None or height <= 0:
        return None
    return Manifold.extrude(section, height).translate([0.0, 0.0, z0])


def build_body(project: Project) -> Manifold:
    h = project.outer_height
    if has_threaded_lid(project):
        body = _threaded_container(project)
    else:
        body = _prism(footprint(project), h, 0.0)
        cavity = _cavity(project)
        if cavity is not None:
            body = body - cavity
    dividers = build_dividers(project)
    if dividers is not None:
        body = body + dividers
    posts = build_posts(project)
    if posts is not None:
        body = body + posts
    columns = build_lid_columns(project)
    if columns is not None:
        body = body + columns
    frames = build_frames(project)
    if frames is not None:
        body = body + frames
    lid_cut = _lid_cut_in_body(project)
    if lid_cut is not None:
        body = body - lid_cut
    notch = _finger_notch(project)
    if notch is not None:
        body = body - notch
    body = _apply_labels(project, body, lid=False)
    cutters = [_hole_cutter(project, hole) for hole in project.holes if hole.surface != LID]
    cutters = [c for c in cutters if c is not None]
    if cutters:
        body = body - Manifold.batch_boolean(cutters, OpType.Add)
    return body


def build_dividers(project: Project) -> Manifold | None:
    """The divider walls, reaching into the outer walls so they fuse with them."""
    if not has_dividers(project):
        return None
    d = project.dividers
    top = divider_top(project)
    z0 = project.bottom - 0.01                     # overlap the floor slightly
    height = top - z0
    if height <= 0 or d.thickness <= 0:
        return None
    if divider_fillet(project) > 0:
        walls = _rounded_dividers(project)
        ring = _lip_ring(project, 2 * FUSE)        # notches for the lip, as below
        return walls - ring if ring is not None and walls is not None else walls
    w, dp = project.outer_width, project.outer_depth
    xs, ys = divider_positions(project)
    slabs = [Manifold.cube([d.thickness, dp, height]).translate([x - d.thickness / 2, -dp / 2, z0])
             for x in xs]
    slabs += [Manifold.cube([w, d.thickness, height]).translate([-w / 2, y - d.thickness / 2, z0])
              for y in ys]
    walls = Manifold.batch_boolean(slabs, OpType.Add)
    # Never poke out through rounded corners.
    walls = walls ^ _prism(footprint(project), project.outer_height, 0.0)
    # Notch the ends where the lid's lip goes, with the fit gap all round.
    ring = _lip_ring(project)
    if ring is not None:
        walls = walls - ring
    return walls


def build_posts(project: Project) -> Manifold | None:
    """Screw posts on the floor, each with a pilot hole down to the floor."""
    from . import mounts
    posts = []
    for m in project.mounts:
        screw = mounts.SCREWS[m.screw]
        r, pilot = screw.post / 2, screw.pilot / 2
        if m.length <= 0:
            continue
        for x, y in mounts.post_positions(m):
            post = Manifold.cylinder(m.length + 0.01, r, -1.0, _circle_segments(r, 0.5, 24, 96))
            hole = Manifold.cylinder(m.length + 1.0, pilot, -1.0, _circle_segments(pilot, 0.4, 16, 48))
            posts.append((post - hole.translate([0.0, 0.0, 0.01]))
                         .translate([x, y, project.bottom - 0.01]))
    if not posts:
        return None
    # Never poke out through the walls.
    return Manifold.batch_boolean(posts, OpType.Add) ^ _prism(footprint(project), project.outer_height, 0.0)


def build_frames(project: Project) -> Manifold | None:
    """Thicker frames on the inside of the walls around openings that ask for one.

    Each frame has a flat band around the opening and 45° sides, so it prints
    without support. It is kept out of the lid's way and never pokes outside.
    """
    frames = [f for f in (frame_solid(project, h) for h in project.holes) if f is not None]
    if not frames:
        return None
    frames = Manifold.batch_boolean(frames, OpType.Add)
    keep = _prism(footprint(project), lid_ceiling(project), 0.0)
    frames = frames ^ keep
    ring = _lip_ring(project)
    return frames - ring if ring is not None else frames


def frame_solid(project: Project, hole: Hole) -> Manifold | None:
    """The strengthening frame of one wall opening, before it is trimmed."""
    if not has_frame(project, hole):
        return None
    outline = _opening_outline(hole)
    if outline is None:
        return None
    t = frame_thickness(project)
    seg = _circle_segments(FRAME_RIM + t, 0.5, 16, 64)
    base = outline.offset(FRAME_RIM + t, JoinType.Round, circular_segments=seg)
    face = outline.offset(FRAME_RIM, JoinType.Round, circular_segments=seg)
    frame = Manifold.hull_points(_outline_points(base, -0.01) + _outline_points(face, t))
    return _on_wall_inside(project, hole, frame)


def _on_wall_inside(project: Project, hole: Hole, m: Manifold) -> Manifold:
    """Place a shape made around the origin (u along X, v along Y, Z pointing into
    the box) on the inside face of the hole's wall."""
    m = m.rotate([-90.0, 0.0, 0.0])        # Z (into the box) -> +Y, v -> up/down
    zc = project.outer_height / 2 + hole.v
    w, d, wall = project.outer_width, project.outer_depth, project.wall
    if hole.surface == FRONT:
        return m.translate([hole.u, -d / 2 + wall, zc])
    if hole.surface == BACK:
        return m.rotate([0.0, 0.0, 180.0]).translate([-hole.u, d / 2 - wall, zc])
    if hole.surface == LEFT:
        return m.rotate([0.0, 0.0, -90.0]).translate([-w / 2 + wall, -hole.u, zc])
    if hole.surface == RIGHT:
        return m.rotate([0.0, 0.0, 90.0]).translate([w / 2 - wall, hole.u, zc])
    inner_r = project.outer_diameter / 2 - wall          # SIDE
    a = math.radians(hole.u)
    return m.rotate([0.0, 0.0, hole.u]).translate([math.sin(a) * inner_r, -math.cos(a) * inner_r, zc])


def _opening_outline(hole: Hole) -> CrossSection | None:
    """The opening's shape seen straight on: u along X, v along Y."""
    hu, hv = hole.half_extents
    if hu <= 0 or hv <= 0:
        return None
    if hole.kind == ROUND:
        return CrossSection.circle(hu, _circle_segments(hu, 0.6, 24, 128))
    r = corner_rounding(hole)
    if r < 0.05:
        return CrossSection.square([2 * hu, 2 * hv], center=True)
    core = CrossSection.square([max(2 * (hu - r), 1e-3), max(2 * (hv - r), 1e-3)], center=True)
    return core.offset(r, JoinType.Round, circular_segments=_circle_segments(r, 0.4, 8, 64))


def build_lid_columns(project: Project) -> Manifold | None:
    """Corner columns for a screwed-down lid, with a pilot hole from the top."""
    positions = lid_screw_positions(project)
    if not positions:
        return None
    screw = SCREWS[project.lid.screw]
    r, pilot = screw.post / 2, screw.pilot / 2
    h, z0 = project.outer_height, project.bottom - 0.01
    depth = lid_pilot_depth(project)
    columns = []
    for x, y in positions:
        # The column, filled out towards the corner so it is joined to the walls along
        # its whole height (not only through the floor).
        reach = r + project.wall
        if project.shape == CYLINDER:
            fill = CrossSection.square([reach, 1.4 * r]).translate([0.0, -0.7 * r]) \
                .rotate(math.degrees(math.atan2(y, x)))
        else:
            fill = CrossSection.square([reach, reach]).translate(
                [-reach if x < 0 else 0.0, -reach if y < 0 else 0.0])
        section = (CrossSection.circle(r, _circle_segments(r, 0.5, 24, 96)) + fill).translate([x, y])
        column = Manifold.extrude(section, h - z0).translate([0.0, 0.0, z0])
        hole = Manifold.cylinder(depth + 1.0, pilot, -1.0, _circle_segments(pilot, 0.4, 16, 48))
        columns.append(column - hole.translate([x, y, h - depth]))
    # Clip to the outside of the box so nothing pokes out through the walls.
    return Manifold.batch_boolean(columns, OpType.Add) ^ _prism(footprint(project), h, 0.0)


def _snap_selector(project: Project, z0: float, z1: float, extra: float) -> Manifold:
    """The middle third of every side (plus `extra` mm each way), where snap ridges go."""
    big = project.outer_width + project.outer_depth
    sx = project.inner_width / 6 + extra
    sy = project.inner_depth / 6 + extra
    a = Manifold.cube([2 * sx, big, z1 - z0]).translate([-sx, -big / 2, z0])
    b = Manifold.cube([big, 2 * sy, z1 - z0]).translate([-big / 2, -sy, z0])
    return a + b


def _snap_ridge_z(project: Project) -> float:
    """Height of the bottom of the snap ridges (lid on)."""
    return project.outer_height - project.lid.lip_height + 1.0


def _lid_cut_in_body(project: Project) -> Manifold | None:
    """What the lid needs cut out of the box: snap grooves, or a sliding lid's slot."""
    lid = project.lid
    if has_snap_lid(project):
        z0 = _snap_ridge_z(project) - 0.2
        z1 = z0 + SNAP_RIDGE + 0.4
        outer = footprint(project, project.wall + lid.gap - SNAP_BUMP - 0.15)
        inner = footprint(project, project.wall + 0.5)
        if outer is None or inner is None:
            return None
        ring = _prism(outer, z1 - z0, z0) - _prism(inner, z1 - z0 + 2, z0 - 1)
        return ring ^ _snap_selector(project, z0 - 1, z1 + 1, 1.0)
    if has_sliding_lid(project) and project.shape == BOX:
        # Made as if the lid slid in from the front, then turned to its side.
        g0, g1 = slide_groove(project)
        reach_x = _slide_across(project) / 2 + slide_engage(project) + lid.gap
        front = -side_span(project, lid.slide_from)[1] - 1.0
        groove = _prism(_slide_outline(project, slide_engage(project) + lid.gap, front),
                        g1 - g0, g0)
        # Lower that wall so the lid can slide in.
        opening_h = project.outer_height - g0 + 1.0
        opening = Manifold.cube([2 * reach_x, project.wall + 1.0 + 0.01, opening_h]).translate(
            [-reach_x, front, g0])
        return (groove + opening).rotate([0.0, 0.0, SIDE_ANGLES[lid.slide_from]])
    return None


def _slide_across(project: Project) -> float:
    """Inside width of the box across the way a sliding lid moves."""
    return project.inner_width if project.lid.slide_from in (FRONT, BACK) else project.inner_depth


def _slide_outline(project: Project, reach: float, front_y: float) -> CrossSection:
    """Outline of a sliding lid reaching `reach` mm into the walls, as if it slid
    in from the front (turn it by SIDE_ANGLES to its real side).

    The back follows the box's corners; the front half is straight so the
    lid can slide in and out.
    """
    back = footprint(project, project.wall - reach).rotate(-SIDE_ANGLES[project.lid.slide_from])
    half_x = _slide_across(project) / 2 + reach
    straight = CrossSection.square([2 * half_x, -front_y]).translate([-half_x, front_y])
    return back + straight


def _helix(radius: float, z_from: float, z_to: float) -> Manifold:
    """A right-hand thread: an off-centre disc twisted as it rises.

    Its surface swings between radius - THREAD_DEPTH and radius (outermost
    point). Every helix uses the same phase at the same height, so a neck's
    thread and its lid's thread always line up.
    """
    e = THREAD_DEPTH / 2
    disc = CrossSection.circle(radius - e, _circle_segments(radius, 0.8, 64, 240)).translate([e, 0])
    turn = 360.0 / THREAD_PITCH
    disc = disc.rotate(turn * z_from)
    height = z_to - z_from
    # Between slices the surface is straight; keep the slices close enough that it
    # stays within 0.05 mm of the true curve, however wide the container (well
    # inside the thread clearance, which is 0.35 mm or more).
    step = math.degrees(2 * math.acos(1 - 0.05 / radius))
    slices = max(8, math.ceil(turn * height / step))
    return Manifold.extrude(disc, height, slices, turn * height).translate([0.0, 0.0, z_from])


def _threaded_container(project: Project) -> Manifold:
    """A round container whose top narrows into a neck with a thread on the outside."""
    t = thread_sizes(project)
    h, inside = project.outer_height, project.outer_diameter / 2 - project.wall
    profile = CrossSection([[
        (0.0, 0.0), (t.outer, 0.0), (t.outer, t.shoulder), (t.root, t.shoulder), (t.root, h),
        (t.opening, h), (t.opening, t.shoulder), (inside, t.slope_bottom),
        *_floor_corner_profile(project, inside), (0.0, project.bottom)]])
    body = Manifold.revolve(profile, _circle_segments(t.outer))
    thread = _helix(t.crest, t.thread_from, t.thread_to)
    opening = Manifold.cylinder(h - t.shoulder + 2, t.opening, -1.0, _circle_segments(t.opening))
    return (body + thread) - opening.translate([0.0, 0.0, t.shoulder - 0.01])


def _floor_corner_profile(project: Project, inside: float) -> list[tuple[float, float]]:
    """Points (radius, height) from the inside wall down to the floor, round or angled."""
    f = inside_fillet(project)
    if f <= 0:
        return [(inside, project.bottom)]
    steps = 1 if project.inside_corners == ANGLED else 12
    return [(inside - floor_inset(project, f * (1 - i / steps)), project.bottom + f * (1 - i / steps))
            for i in range(steps + 1)]


def _threaded_lid(project: Project) -> Manifold:
    """A cap whose skirt has the matching thread on the inside."""
    t = thread_sizes(project)
    top_inside = project.outer_height + CAP_TOP_GAP
    skirt_from = t.shoulder + 0.5
    cap = Manifold.cylinder(top_inside + project.lid.thickness - skirt_from, t.outer, -1.0,
                            _circle_segments(t.outer)).translate([0.0, 0.0, skirt_from])
    # The inside is the neck's outside grown by the clearance, thread included.
    room = Manifold.cylinder(top_inside - skirt_from + 1.0, t.root + t.clearance, -1.0,
                             _circle_segments(t.root)).translate([0.0, 0.0, skirt_from - 1.0])
    room = room + _helix(t.crest + t.clearance, skirt_from - 1.0, top_inside)
    return cap - room


def build_lid(project: Project) -> Manifold | None:
    lid_opts = project.lid
    if not lid_opts.enabled:
        return None
    if lid_opts.style == THREADED:
        return _cut_lid_holes(project, _threaded_lid(project)) if has_threaded_lid(project) else None
    if has_sliding_lid(project):
        if project.shape != BOX:
            return None
        g0, _ = slide_groove(project)
        side = lid_opts.slide_from
        outline = _slide_outline(project, slide_engage(project), -side_span(project, side)[1])
        panel = _prism(outline.rotate(SIDE_ANGLES[side]), lid_opts.thickness, g0 + lid_opts.gap)
        return _cut_lid_holes(project, panel)
    h = project.outer_height
    lid = _prism(_lid_outline(project), lid_opts.thickness, h)
    if has_screw_lid(project):
        d = SCREWS[lid_opts.screw].clearance
        holes = [Manifold.cylinder(lid_opts.thickness + 2.0, d / 2, -1.0, _circle_segments(d / 2, 0.4, 16, 48))
                 .translate([x, y, h - 1.0]) for x, y in lid_screw_positions(project)]
        lid = lid - Manifold.batch_boolean(holes, OpType.Add)
        return _cut_lid_holes(project, lid)
    lip_out_inset = project.wall + lip_outer_offset(project)
    # The lip reaches 0.01 mm into the plate so the union is a single solid.
    lip_outer = _prism(footprint(project, lip_out_inset), lid_opts.lip_height + 0.01,
                       h - lid_opts.lip_height)
    if lip_outer is not None:
        lip_inner = _prism(footprint(project, lip_out_inset + lip_wall(project)),
                           lid_opts.lip_height + 1.0, h - lid_opts.lip_height - 0.5)
        lip = lip_outer - lip_inner if lip_inner is not None else lip_outer
        lid = lid + lip
    if has_snap_lid(project):
        z0 = _snap_ridge_z(project)
        outer = footprint(project, project.wall + lid_opts.gap - SNAP_BUMP)
        inner = footprint(project, lip_out_inset + 0.5)      # reaches into the lip
        if outer is not None and inner is not None:
            ridge = _prism(outer, SNAP_RIDGE, z0) - _prism(inner, SNAP_RIDGE + 2, z0 - 1)
            lid = lid + (ridge ^ _snap_selector(project, z0 - 1, z0 + SNAP_RIDGE + 1, 0.0))
    return _cut_lid_holes(project, lid)


def _lid_outline(project: Project) -> CrossSection:
    """The lid seen from above: the box's outline, plus the opening tab if asked for."""
    outline = footprint(project)
    if not has_lid_tab(project):
        return outline
    side = project.lid.opening_side
    length, front = side_span(project, side)
    width = min(TAB_WIDTH, 0.5 * length)
    r = min(2.5, width / 2)
    tab = CrossSection.square([width - 2 * r, TAB_REACH + 2.0 - 2 * r], center=True) \
        .offset(r, JoinType.Round, circular_segments=16) \
        .translate([0.0, -front - TAB_REACH / 2 + 1.0]).rotate(SIDE_ANGLES[side])
    # Round the corners where the tab meets the lid, so they don't crack.
    seg = _circle_segments(2.0, 0.4, 8, 32)
    return (outline + tab).offset(2.0, JoinType.Round, circular_segments=seg) \
        .offset(-2.0, JoinType.Round, circular_segments=seg)


def _finger_notch(project: Project) -> Manifold | None:
    """A rounded notch in the top of a wall, to get a finger under the lid."""
    if not has_finger_notch(project):
        return None
    width, depth = notch_size(project)
    if depth <= 0:
        return None
    h, wall = project.outer_height, project.wall
    r = min(depth, width / 2)
    shape = CrossSection.square([width - 2 * r, 2 * depth + 2.0 - 2 * r], center=True) \
        .offset(r, JoinType.Round, circular_segments=_circle_segments(r, 0.4, 16, 48)) \
        .translate([0.0, h + 1.0])                      # bottom at h - depth
    side = project.lid.opening_side
    _, front = side_span(project, side)
    if project.shape == BOX:
        reach = wall + 0.5
    else:
        inner = front - wall
        reach = wall + inner - math.sqrt(inner ** 2 - (width / 2) ** 2) + 0.5
    # The shape is drawn in x/z; extruding along z and turning it makes it run along y.
    # Made at the front, then turned to its side.
    return (Manifold.extrude(shape, reach + 1.0).rotate([90.0, 0.0, 0.0])
            .translate([0.0, -front + reach, 0.0]).rotate([0.0, 0.0, SIDE_ANGLES[side]]))


def _cut_lid_holes(project: Project, lid: Manifold) -> Manifold:
    lid = _apply_labels(project, lid, lid=True)
    cutters = [_hole_cutter(project, hole) for hole in project.holes if hole.surface == LID]
    cutters = [c for c in cutters if c is not None]
    if cutters:
        lid = lid - Manifold.batch_boolean(cutters, OpType.Add)
    return lid


LABEL_EMBED = 0.3       # raised text reaches this far into the surface, so they join


def label_solid(project: Project, label) -> Manifold | None:
    """The text as a solid on the outside of its surface: what is added (raised
    text) or cut away (engraved text)."""
    from .text import outline
    if label.surface not in project.surfaces():
        return None
    shape = outline(label.text, label.size)
    if shape is None:
        return None
    if label.style == RAISED:
        z0, z1 = -LABEL_EMBED, label.depth
    else:
        z0, z1 = -label.depth, 1.0
    slab = Manifold.extrude(shape, z1 - z0).translate([0.0, 0.0, z0])
    if label.surface == SIDE:
        # Wrap it around the round wall: across becomes the angle, out becomes the radius.
        radius = project.outer_diameter / 2
        start = math.radians(label.u)
        z_mid = project.outer_height / 2 + label.v
        slab = slab.refine_to_length(1.0)

        def wrap(points):
            angle = start + points[:, 0] / radius
            r = radius + points[:, 2]
            return np.column_stack([r * np.sin(angle), -r * np.cos(angle), z_mid + points[:, 1]])
        return slab.warp_batch(wrap)
    center, normal, right, up = surface_frame(project, label.surface)
    origin = np.array(center) + np.array(right) * label.u + np.array(up) * label.v
    text_up = np.array(up)
    if label.surface == BOTTOM:
        text_up = -text_up          # reads the right way when the box is tipped towards you
    matrix = np.column_stack([np.array(right, float), text_up.astype(float),
                              np.array(normal, float), origin])
    return slab.transform(matrix)


def _apply_labels(project: Project, solid: Manifold, lid: bool) -> Manifold:
    raised, engraved = [], []
    for label in project.labels:
        if (label.surface == LID) != lid:
            continue
        piece = label_solid(project, label)
        if piece is not None:
            (raised if label.style == RAISED else engraved).append(piece)
    if raised:
        solid = solid + Manifold.batch_boolean(raised, OpType.Add)
    if engraved:
        solid = solid - Manifold.batch_boolean(engraved, OpType.Add)
    return solid


def build_parts(project: Project) -> Parts:
    return Parts(body=build_body(project), lid=build_lid(project))


def _hole_cutter(project: Project, hole: Hole) -> Manifold | None:
    if hole.kind == VENT:
        slots = [c for c in (_hole_cutter(project, s) for s in vent_openings(project, hole))
                 if c is not None]
        return Manifold.batch_boolean(slots, OpType.Add) if slots else None
    hu, hv = hole.half_extents
    if hu <= 0 or hv <= 0:
        return None
    wall = project.wall
    zc = project.outer_height / 2 + hole.v

    def plug(length: float) -> Manifold:
        """The opening's shape, extruded along Z: u along X, v along Y."""
        return Manifold.extrude(_opening_outline(hole), length).translate([0.0, 0.0, -length / 2])

    def upright(length: float) -> Manifold:
        """Plug pointing along Y, with u along X and v up (Z)."""
        return plug(length).rotate([90.0, 0.0, 0.0])

    # Through a frame on the inside too (this hole's own, or a neighbour's).
    deep = frame_thickness(project) if any(has_frame(project, h) for h in project.holes) else 0.0
    if hole.surface in (FRONT, BACK, LEFT, RIGHT):
        return _on_wall_inside(project, hole, plug(wall + deep + 2.0).translate(
            [0.0, 0.0, (deep - wall) / 2]))
    if hole.surface == SIDE:
        big_r = project.outer_diameter / 2
        inner_r = big_r - wall
        # The inside of a round wall curves away; cut deep enough at the opening's edges.
        sag = inner_r - math.sqrt(max(inner_r ** 2 - hu ** 2, 0.0)) if hu < inner_r else inner_r
        length = wall + max(sag, deep) + 2.0
        mid = big_r + 1.0 - length / 2
        a = math.radians(hole.u)
        return (upright(length).rotate([0.0, 0.0, hole.u])
                .translate([math.sin(a) * mid, -math.cos(a) * mid, zc]))
    if hole.surface == BOTTOM:
        return plug(project.bottom + 2.0).translate([hole.u, hole.v, project.bottom / 2])
    if hole.surface == LID:
        t = project.lid.thickness
        return plug(t + 2.0).translate([hole.u, hole.v, lid_top_z(project) - t / 2])
    return None


# ---------------------------------------------------------------------------
# Mesh helpers
# ---------------------------------------------------------------------------

def mesh_arrays(m: Manifold) -> tuple[np.ndarray, np.ndarray]:
    """Vertices (N x 3 float) and triangles (M x 3 int) of a solid."""
    mesh = m.to_mesh()
    verts = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    tris = np.asarray(mesh.tri_verts, dtype=np.int64)
    return verts, tris


def piece_count(m: Manifold) -> int:
    return len(m.decompose())


def is_valid_solid(m: Manifold) -> bool:
    return m.status() == Error.NoError and not m.is_empty() and m.volume() > 0


def overlap_volume(a: Manifold, b: Manifold) -> float:
    return (a ^ b).volume()


# ---------------------------------------------------------------------------
# Fit test print: only the parts that must fit, to check them with little plastic.
# ---------------------------------------------------------------------------

FIT_MARGIN = 2.0       # extra wall above and below what is being tested
FIT_RIM = 3.0          # how far the lid's test ring reaches in past what must fit
FIT_JOIN = 3.0         # test bands closer than this become one piece
WALL_SURFACES = (FRONT, BACK, LEFT, RIGHT, SIDE)


def fit_test_lid_band(project: Project) -> tuple[float, float] | None:
    """Heights (from, to) of the top of the box that the lid needs to fit."""
    if _lid_style(project) is None:
        return None
    h, lid = project.outer_height, project.lid
    if has_threaded_lid(project):
        z0 = thread_sizes(project).shoulder - FIT_MARGIN
    elif has_sliding_lid(project):
        z0 = slide_groove(project)[0] - FIT_MARGIN - 1.0
    elif has_screw_lid(project):
        z0 = h - max(lid_pilot_depth(project), 3.0) - FIT_MARGIN
    else:
        z0 = h - lid.lip_height - FIT_MARGIN - 1.0
    return max(0.0, z0), h


def _lid_style(project: Project) -> str | None:
    """The kind of lid that will be built, or None when there is no lid."""
    if not project.lid.enabled:
        return None
    if project.lid.style == THREADED and not has_threaded_lid(project):
        return None
    if has_sliding_lid(project) and project.shape != BOX:
        return None
    return project.lid.style


def fit_test_openings_band(project: Project) -> tuple[float, float] | None:
    """Heights (from, to) of the walls with openings and the screw posts. With screw
    posts it starts at the bottom, so you can screw the board on and try the plugs."""
    from . import mounts
    zs = []
    for hole in project.holes:
        if hole.surface in WALL_SURFACES and hole.kind != VENT:
            z = project.outer_height / 2 + hole.v
            reach = hole.half_extents[1] + (FRAME_RIM if has_frame(project, hole) else 0.0)
            zs += [z - reach, z + reach]
    tops = [mounts.board_bottom(project, m) for m in project.mounts if m.length > 0]
    if not zs and not tops:
        return None
    z0 = 0.0 if tops else max(project.bottom, min(zs) - FIT_MARGIN)
    z1 = min(project.outer_height, max(zs + tops) + FIT_MARGIN)
    return z0, z1


FIT_FLOOR_RIM = 4.0    # the test piece keeps this much of the floor along the walls


def _band(body: Manifold, z0: float, z1: float, project: Project) -> Manifold:
    big = project.outer_width + project.outer_depth + 20.0
    cut = Manifold.cube([big, big, z1 - z0]).translate([-big / 2, -big / 2, z0])
    band = body ^ cut
    if z0 <= 0.0:
        band = band - _floor_middle(project)
    return _on_plate(band)


def _floor_middle(project: Project) -> Manifold:
    """The part of the floor a test piece doesn't need: it keeps a rim along the
    walls, the floor under the screw posts and dividers, and a bar from each post
    to the nearest wall, so the posts stay exactly where they belong."""
    from . import mounts
    middle = footprint(project, project.wall + FIT_FLOOR_RIM)
    if middle is None:
        return Manifold()
    keep = []
    for m in project.mounts:
        if m.length <= 0:
            continue
        r = mounts.post_radius(m)
        for x, y in mounts.post_positions(m):
            keep.append(CrossSection.circle(r + 2.0, _circle_segments(r + 2.0, 0.5, 16, 64))
                        .translate([x, y]))
            if project.shape == CYLINDER:
                reach = project.outer_diameter / 2
                bar = CrossSection.square([reach, 2 * r]).translate([0.0, -r]) \
                    .rotate(math.degrees(math.atan2(y, x))) if (x or y) else None
            else:
                to_x = project.inner_width / 2 - abs(x)
                to_y = project.inner_depth / 2 - abs(y)
                if to_x < to_y:
                    bar = CrossSection.square([to_x + 1.0, 2 * r]).translate(
                        [0.0 if x >= 0 else -(to_x + 1.0), -r])
                else:
                    bar = CrossSection.square([2 * r, to_y + 1.0]).translate(
                        [-r, 0.0 if y >= 0 else -(to_y + 1.0)])
            if bar is not None:
                keep.append(bar.translate([x, y]))
    for x, y in lid_screw_positions(project):
        r = SCREWS[project.lid.screw].post / 2 + 1.0
        keep.append(CrossSection.circle(r, _circle_segments(r, 0.5, 16, 64)).translate([x, y]))
    dividers = _divider_outline(project, 2.0)
    if dividers is not None:
        keep.append(dividers)
    if keep:
        middle = middle - CrossSection.batch_boolean(keep, OpType.Add)
    if middle.area() < 25.0:
        return Manifold()
    return _prism(middle, project.bottom + 0.51, -0.5)


def _lid_ring(project: Project, lid: Manifold) -> Manifold:
    """The lid without its middle: just what has to fit on the box."""
    style = _lid_style(project)
    wall = project.wall
    if style == THREADED:
        r = thread_sizes(project).root - FIT_RIM
        middle = CrossSection.circle(r, _circle_segments(r)) if r > FIT_RIM else None
    elif style == SCREWED:
        middle = footprint(project, wall + FIT_RIM)
        if middle is not None:
            d = SCREWS[project.lid.screw].clearance / 2 + FIT_RIM
            for x, y in lid_screw_positions(project):
                middle = middle - CrossSection.circle(d, _circle_segments(d, 0.5, 16, 64)).translate([x, y])
    elif style == SLIDING:
        middle = footprint(project, wall + slide_engage(project) + FIT_RIM)
    else:
        middle = footprint(project, wall + lip_outer_offset(project) + lip_wall(project) + FIT_RIM)
    if middle is None or middle.area() < 25.0:
        return lid
    lo, hi = _bounds(lid)
    return lid - _prism(middle, hi[2] - lo[2] + 2.0, lo[2] - 1.0)


def fit_test_parts(project: Project, lid: bool = True, openings: bool = True,
                   parts: Parts | None = None) -> dict[str, Manifold]:
    """Pieces of the box and lid to print first, laid flat for printing.

    "box-top" is the top of the box that the lid fits on, "box-openings" the walls
    with the openings (and the floor with the screw posts). When they are close
    together they are one piece, "box".
    """
    if parts is None:
        parts = build_parts(project)
    lid_band = fit_test_lid_band(project) if lid and parts.lid is not None else None
    open_band = fit_test_openings_band(project) if openings else None
    out = {}
    if lid_band and open_band and open_band[1] >= lid_band[0] - FIT_JOIN:
        out["box"] = _band(parts.body, min(open_band[0], lid_band[0]), lid_band[1], project)
    else:
        if open_band:
            out["box-openings"] = _band(parts.body, *open_band, project)
        if lid_band:
            out["box-top"] = _band(parts.body, *lid_band, project)
    if lid_band:
        ring = _lid_ring(project, parts.lid)
        out["lid"] = _on_plate(ring.rotate([180.0, 0.0, 0.0]))
    return out
