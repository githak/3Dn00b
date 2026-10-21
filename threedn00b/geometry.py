"""Geometry engine: turns a Project into watertight solids using Manifold.

Manifold guarantees closed ("watertight") results for every Boolean
operation, which is exactly what a slicer needs from an STL file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from manifold3d import CrossSection, Error, JoinType, Manifold, OpType

from .model import (BACK, BOTTOM, CYLINDER, FRONT, LEFT, LID, RECT, RIGHT, SIDE,
                    Hole, Project, lip_outer_offset, lip_wall)


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
    cutters = [_hole_cutter(project, hole) for hole in project.holes if hole.surface != LID]
    cutters = [c for c in cutters if c is not None]
    if cutters:
        body = body - Manifold.batch_boolean(cutters, OpType.Add)
    return body


def build_lid(project: Project) -> Manifold | None:
    lid_opts = project.lid
    if not lid_opts.enabled:
        return None
    h = project.outer_height
    lid = _prism(footprint(project), lid_opts.thickness, h)
    lip_out_inset = project.wall + lip_outer_offset(project)
    # The lip reaches 0.01 mm into the plate so the union is a single solid.
    lip_outer = _prism(footprint(project, lip_out_inset), lid_opts.lip_height + 0.01,
                       h - lid_opts.lip_height)
    if lip_outer is not None:
        lip_inner = _prism(footprint(project, lip_out_inset + lip_wall(project)),
                           lid_opts.lip_height + 1.0, h - lid_opts.lip_height - 0.5)
        lip = lip_outer - lip_inner if lip_inner is not None else lip_outer
        lid = lid + lip
    cutters = [_hole_cutter(project, hole) for hole in project.holes if hole.surface == LID]
    cutters = [c for c in cutters if c is not None]
    if cutters:
        lid = lid - Manifold.batch_boolean(cutters, OpType.Add)
    return lid


def build_parts(project: Project) -> Parts:
    return Parts(body=build_body(project), lid=build_lid(project))


def _hole_cutter(project: Project, hole: Hole) -> Manifold | None:
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
