"""Translate a point clicked in the 3D view into "which surface, where on it".

Kept free of Qt so it can be unit-tested.
"""

from __future__ import annotations

import math

from .model import (BACK, BOTTOM, BOX, FRONT, LEFT, LID, RIGHT, SIDE, Hole,
                    Project, extent_limits, point_near_opening, surface_frame,
                    surface_offset_mm, wall_limits)

SNAP_MM = 3.0
SNAP_DEG = 5.0


def surface_at(project: Project, point, normal, part: str):
    """Return (surface, u, v) for a point on the body or lid, or None.

    `point` is in assembled coordinates (lid sitting on the body).
    """
    x, y, z = point
    h = project.outer_height
    if part == "lid":
        return LID, x, y
    if abs(normal[2]) > 0.7:
        if z <= project.bottom + 0.05:
            return BOTTOM, x, y
        return None           # top rim of the wall
    v = z - h / 2
    if project.shape != BOX:
        return SIDE, math.degrees(math.atan2(x, -y)), v
    w, d, t = project.outer_width, project.outer_depth, project.wall
    walls = {
        FRONT: (-d / 2 - 0.05 <= y <= -d / 2 + t + 0.05, (0, -1), x),
        BACK: (d / 2 - t - 0.05 <= y <= d / 2 + 0.05, (0, 1), -x),
        LEFT: (-w / 2 - 0.05 <= x <= -w / 2 + t + 0.05, (-1, 0), -y),
        RIGHT: (w / 2 - t - 0.05 <= x <= w / 2 + 0.05, (1, 0), y),
    }
    candidates = [(abs(n[0] * normal[0] + n[1] * normal[1]), name, u)
                  for name, (inside, n, u) in walls.items() if inside]
    if not candidates:
        return None
    _, name, u = max(candidates)
    return name, u, v


def find_hole(project: Project, surface: str, u: float, v: float) -> Hole | None:
    """The hole closest to a clicked spot, if the click was on or near it."""
    best, best_dist = None, None
    for hole in project.holes:
        if hole.surface != surface:
            continue
        dist = math.hypot(*surface_offset_mm(project, surface, hole.u - u, hole.v - v))
        if point_near_opening(project, hole, u, v, 2.0) and (best_dist is None or dist < best_dist):
            best, best_dist = hole, dist
    return best


def snap(surface: str, u: float, v: float) -> tuple[float, float]:
    """Snap a position to centre lines (and quarter turns on the round wall)."""
    if surface == SIDE:
        for target in (-180.0, -90.0, 0.0, 90.0, 180.0):
            if abs(u - target) <= SNAP_DEG:
                u = target
        u = (u + 180.0) % 360.0 - 180.0
    elif abs(u) <= SNAP_MM:
        u = 0.0
    if abs(v) <= SNAP_MM:
        v = 0.0
    return round(u, 1), round(v, 1)


def fitting_diameter(project: Project, surface: str, preferred: float = 8.0) -> float | None:
    """Largest of a few friendly sizes (up to `preferred`) that fits on a surface."""
    for d in (preferred, 6.0, 5.0, 4.0, 3.0):
        if d <= preferred and wall_limits(project, surface, d) is not None:
            return d
    return None


def fitting_rect(project: Project, surface: str) -> tuple[float, float] | None:
    """A friendly starting size for a rectangular hole that fits on a surface."""
    for w, h in ((12.0, 6.0), (10.0, 5.0), (8.0, 4.0), (6.0, 3.0)):
        if extent_limits(project, surface, w / 2, h / 2) is not None:
            return w, h
    return None


# ---------------------------------------------------------------------------
# Dragging holes: intersect the mouse ray with a hole's own surface.
# Rays are (origin, direction) in assembled coordinates, direction normalised.
# ---------------------------------------------------------------------------

def surface_hit(project: Project, surface: str, origin, direction, lid_offset: float = 0.0):
    """Where a ray meets a surface: (distance, u, v, exact) or None.

    For the round wall a ray that misses the cylinder returns the closest
    point instead, with exact=False, so dragging past the edge still works.
    """
    ox, oy, oz = origin
    dx, dy, dz = direction
    if surface == LID:
        oz -= lid_offset
    h = project.outer_height
    if surface == SIDE:
        radius = project.outer_diameter / 2
        a = dx * dx + dy * dy
        if a < 1e-12:
            return None
        b = 2 * (ox * dx + oy * dy)
        c = ox * ox + oy * oy - radius * radius
        disc = b * b - 4 * a * c
        exact = disc >= 0
        if exact:
            root = math.sqrt(disc)
            t = (-b - root) / (2 * a)
            if t < 0:
                t = (-b + root) / (2 * a)
        else:
            t = -b / (2 * a)
        if t < 0:
            return None
        px, py, pz = ox + t * dx, oy + t * dy, oz + t * dz
        return t, math.degrees(math.atan2(px, -py)), pz - h / 2, exact
    c, n, right, up = surface_frame(project, surface)
    if surface == BOTTOM and oz > project.bottom:
        c = (0.0, 0.0, project.bottom)        # from above you see the inside floor
    denom = dx * n[0] + dy * n[1] + dz * n[2]
    if abs(denom) < 1e-9:
        return None
    t = ((c[0] - ox) * n[0] + (c[1] - oy) * n[1] + (c[2] - oz) * n[2]) / denom
    if t < 0:
        return None
    p = (ox + t * dx - c[0], oy + t * dy - c[1], oz + t * dz - c[2])
    u = p[0] * right[0] + p[1] * right[1] + p[2] * right[2]
    v = p[0] * up[0] + p[1] * up[1] + p[2] * up[2]
    return t, u, v, True


def hole_under_ray(project: Project, origin, direction, mesh_distance: float | None,
                   lid_offset: float = 0.0, lid_visible: bool = True) -> Hole | None:
    """The hole the mouse is pointing at, if any.

    `mesh_distance` is how far away the ray first hits the visible model; holes
    on surfaces further back than that are hidden and can't be grabbed.
    """
    best, best_t = None, None
    for hole in project.holes:
        if hole.surface not in project.surfaces() or (hole.surface == LID and not lid_visible):
            continue
        hit = surface_hit(project, hole.surface, origin, direction, lid_offset)
        if hit is None or not hit[3]:
            continue
        t, u, v, _ = hit
        depth = project.bottom if hole.surface == BOTTOM else project.wall
        if mesh_distance is not None and t > mesh_distance + depth + 1.5:
            continue
        if not point_near_opening(project, hole, u, v, 1.5):
            continue
        if best_t is None or t < best_t:
            best, best_t = hole, t
    return best


def snap_drag(project: Project, hole: Hole, u: float, v: float):
    """Snap a dragged position to centre lines and other holes on the same surface.

    Returns (u, v, description) where description says what it snapped to.
    """
    others = [(i, h) for i, h in enumerate(project.holes, 1)
              if h.surface == hole.surface and h.id != hole.id]
    notes = []
    if hole.surface == SIDE:
        tol_u = math.degrees(SNAP_MM / (project.outer_diameter / 2))
        u_targets = [(0.0, "the front"), (90.0, "the right"), (180.0, "the back"),
                     (-90.0, "the left")]
    else:
        tol_u = SNAP_MM
        u_targets = [(0.0, "the centre")]
    u_targets += [(h.u, f"Hole {i}") for i, h in others]
    v_targets = [(0.0, "the middle")] + [(h.v, f"Hole {i}") for i, h in others]

    def nearest(value, targets, tol, wrap=False):
        best = None
        for target, name in targets:
            diff = value - target
            if wrap:
                diff = (diff + 180.0) % 360.0 - 180.0
            if abs(diff) <= tol and (best is None or abs(diff) < best[0]):
                best = (abs(diff), target, name)
        return best

    hit = nearest(u, u_targets, tol_u, wrap=hole.surface == SIDE)
    if hit:
        u = hit[1]
        notes.append(f"lined up with {hit[2]}" if hit[2].startswith("Hole") else f"at {hit[2]}")
    hit = nearest(v, v_targets, SNAP_MM)
    if hit:
        v = hit[1]
        notes.append(f"level with {hit[2]}" if hit[2].startswith("Hole") else f"in {hit[2]}")
    if hole.surface == SIDE:
        u = (u + 180.0) % 360.0 - 180.0
    return round(u, 1), round(v, 1), ", ".join(notes)
