"""Translate a point clicked in the 3D view into "which surface, where on it".

Kept free of Qt so it can be unit-tested.
"""

from __future__ import annotations

import math

from .model import (BACK, BOTTOM, BOX, FRONT, LEFT, LID, RIGHT, SIDE, Hole,
                    Project, wall_limits)

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
        du = hole.u - u
        if surface == SIDE:
            du = math.radians((du + 180.0) % 360.0 - 180.0) * project.outer_diameter / 2
        dist = math.hypot(du, hole.v - v)
        if dist <= hole.diameter / 2 + 2.0 and (best_dist is None or dist < best_dist):
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
