"""Geometry engine: turns a Project into watertight solids using Manifold.

Manifold guarantees closed ("watertight") results for every Boolean
operation, which is exactly what a slicer needs from an STL file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from manifold3d import CrossSection, Error, JoinType, Manifold, OpType

from .model import (BACK, BOTTOM, CYLINDER, FRONT, LEFT, LID, RECT, RIGHT, SIDE, VENT,
                    SCREWS, Hole, Project, divider_positions, divider_top, has_dividers, has_lip,
                    has_screw_lid, lid_pilot_depth, lid_screw_positions,
                    lip_outer_offset, lip_wall, vent_openings)


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
    rad = max(0.0, min(project.outer_corner_radius - inset, w / 2, d / 2))
    core_w, core_d = w - 2 * rad, d - 2 * rad
    if rad < 0.05:
        return CrossSection.square([w, d], center=True)
    if core_w < 1e-3 or core_d < 1e-3:
        # Fully rounded: a stadium or circle.
        core = CrossSection.square([max(core_w, 1e-3), max(core_d, 1e-3)], center=True)
    else:
        core = CrossSection.square([core_w, core_d], center=True)
    return core.offset(rad, JoinType.Round, circular_segments=_circle_segments(rad, 0.5, 16, 128))


def _prism(section: CrossSection | None, height: float, z0: float) -> Manifold | None:
    if section is None or height <= 0:
        return None
    return Manifold.extrude(section, height).translate([0.0, 0.0, z0])


def build_body(project: Project) -> Manifold:
    h = project.outer_height
    body = _prism(footprint(project), h, 0.0)
    cavity = _prism(footprint(project, project.wall), h - project.bottom + 1.0, project.bottom)
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
    w, dp = project.outer_width, project.outer_depth
    xs, ys = divider_positions(project)
    slabs = [Manifold.cube([d.thickness, dp, height]).translate([x - d.thickness / 2, -dp / 2, z0])
             for x in xs]
    slabs += [Manifold.cube([w, d.thickness, height]).translate([-w / 2, y - d.thickness / 2, z0])
              for y in ys]
    walls = Manifold.batch_boolean(slabs, OpType.Add)
    # Never poke out through rounded corners.
    walls = walls ^ _prism(footprint(project), project.outer_height, 0.0)
    if has_lip(project):
        # Notch the ends where the lid's lip goes, with the fit gap all round.
        gap = project.lid.gap
        inner = footprint(project, project.wall)
        clear = footprint(project, project.wall + lip_outer_offset(project) + lip_wall(project) + gap)
        z_notch = project.outer_height - project.lid.lip_height - gap
        ring = _prism(inner, project.outer_height - z_notch + 1.0, z_notch)
        if ring is not None and clear is not None:
            ring = ring - _prism(clear, project.outer_height - z_notch + 2.0, z_notch - 0.5)
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
        column = Manifold.cylinder(h - z0, r, -1.0, _circle_segments(r, 0.5, 24, 96)).translate([x, y, z0])
        hole = Manifold.cylinder(depth + 1.0, pilot, -1.0, _circle_segments(pilot, 0.4, 16, 48))
        columns.append(column - hole.translate([x, y, h - depth]))
    # Clip to the outside of the box so nothing pokes out through the walls.
    return Manifold.batch_boolean(columns, OpType.Add) ^ _prism(footprint(project), h, 0.0)


def build_lid(project: Project) -> Manifold | None:
    lid_opts = project.lid
    if not lid_opts.enabled:
        return None
    h = project.outer_height
    lid = _prism(footprint(project), lid_opts.thickness, h)
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
    return _cut_lid_holes(project, lid)


def _cut_lid_holes(project: Project, lid: Manifold) -> Manifold:
    cutters = [_hole_cutter(project, hole) for hole in project.holes if hole.surface == LID]
    cutters = [c for c in cutters if c is not None]
    if cutters:
        lid = lid - Manifold.batch_boolean(cutters, OpType.Add)
    return lid


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
    w, d = project.outer_width, project.outer_depth

    def plug(length: float) -> Manifold:
        """The opening's shape, extruded along Z: u along X, v along Y."""
        if hole.kind == RECT:
            return Manifold.cube([hole.width, hole.height, length], True)
        return Manifold.cylinder(length, hu, -1.0, _circle_segments(hu, 0.6, 24, 128), True)

    def upright(length: float) -> Manifold:
        """Plug pointing along Y, with u along X and v up (Z)."""
        return plug(length).rotate([90.0, 0.0, 0.0])

    if hole.surface in (FRONT, BACK):
        y = -d / 2 + wall / 2 if hole.surface == FRONT else d / 2 - wall / 2
        x = hole.u if hole.surface == FRONT else -hole.u
        return upright(wall + 2.0).translate([x, y, zc])
    if hole.surface in (LEFT, RIGHT):
        x = -w / 2 + wall / 2 if hole.surface == LEFT else w / 2 - wall / 2
        y = -hole.u if hole.surface == LEFT else hole.u
        return upright(wall + 2.0).rotate([0.0, 0.0, 90.0]).translate([x, y, zc])
    if hole.surface == SIDE:
        big_r = project.outer_diameter / 2
        inner_r = big_r - wall
        # The inside of a round wall curves away; cut deep enough at the opening's edges.
        sag = inner_r - math.sqrt(max(inner_r ** 2 - hu ** 2, 0.0)) if hu < inner_r else inner_r
        length = wall + sag + 2.0
        mid = big_r + 1.0 - length / 2
        a = math.radians(hole.u)
        return (upright(length).rotate([0.0, 0.0, hole.u])
                .translate([math.sin(a) * mid, -math.cos(a) * mid, zc]))
    if hole.surface == BOTTOM:
        return plug(project.bottom + 2.0).translate([hole.u, hole.v, project.bottom / 2])
    if hole.surface == LID:
        t = project.lid.thickness
        return plug(t + 2.0).translate([hole.u, hole.v, project.outer_height + t / 2])
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
