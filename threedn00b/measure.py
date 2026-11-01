"""Measurements shown in the 3D view: the outside size, and where the selected hole is.

Kept free of Qt and OpenGL so it can be tested on its own. Every measurement is a
line with short end marks and a label in the middle, in assembled coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .model import BOTTOM, BOX, LID, SIDE, Hole, Project, lid_top_z, surface_frame

GAP = 0.6           # hole measurements float this far off the surface


@dataclass
class Measure:
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    text: str
    # Extra short lines: the end marks and the lines out to the object.
    marks: list[tuple[tuple, tuple]] = field(default_factory=list)

    @property
    def middle(self) -> tuple[float, float, float]:
        return tuple((a + b) / 2 for a, b in zip(self.start, self.end))

    @property
    def length(self) -> float:
        return float(np.linalg.norm(np.subtract(self.end, self.start)))


def mm(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".") + " mm"


def _offset(project: Project) -> float:
    """How far the size lines stand off the object."""
    return max(6.0, 0.1 * max(project.outer_width, project.outer_depth))


def facing_sides(azimuth: float) -> tuple[int, int]:
    """Which sides face a camera at this azimuth (degrees, as in the 3D view):
    (+1 right or -1 left, +1 back or -1 front)."""
    a = np.radians(azimuth)
    return (1 if np.cos(a) >= 0 else -1), (1 if np.sin(a) >= 0 else -1)


def size_measures(project: Project, facing: tuple[int, int] = (1, -1)) -> list[Measure]:
    """The outside size: width and depth (or diameter) along the bottom, and the height.

    `facing` says which sides you look at (see facing_sides()): the lines go along
    those sides, so they're in front of the object however it's turned. The height
    stands at the far end of the width line, beside the object rather than in front.
    """
    sx, sy = facing
    w, d, h = project.outer_width, project.outer_depth, project.outer_height
    off = _offset(project)
    out = []
    y = sy * (d / 2 + off)
    width_text = mm(w) if project.shape == BOX else "⌀ " + mm(w)
    near = d / 2 + 1.0 if project.shape == BOX else 1.0
    out.append(Measure((-w / 2, y, 0.0), (w / 2, y, 0.0), width_text,
                       [((ex * w / 2, sy * near, 0.0), (ex * w / 2, y + sy * 1.5, 0.0))
                        for ex in (-1, 1)]))
    if project.shape == BOX:
        x = sx * (w / 2 + off)
        out.append(Measure((x, -d / 2, 0.0), (x, d / 2, 0.0), mm(d),
                           [((sx * (w / 2 + 1.0), ey * d / 2, 0.0), (x + sx * 1.5, ey * d / 2, 0.0))
                            for ey in (-1, 1)]))
    # The height; with a lid, also the height with the lid on.
    text = mm(h)
    if project.lid.enabled and project.closed_height > h + 0.05:
        text += f" ({mm(project.closed_height)} with the lid)"
    if project.shape == BOX:
        x, y = -sx * (w / 2 + off), sy * d / 2
        marks = [((-sx * (w / 2 + 1.0), y, z), (x - sx * 1.5, y, z)) for z in (0.0, h)]
    else:
        r, k = w / 2, 0.5 ** 0.5                   # out from the middle at 45°
        x, y = -sx * (r + off) * k, sy * (r + off) * k
        marks = [((-sx * (r + 1.0) * k, sy * (r + 1.0) * k, z),
                  (-sx * (r + off + 1.5) * k, sy * (r + off + 1.5) * k, z)) for z in (0.0, h)]
    out.append(Measure((x, y, 0.0), (x, y, h), text, marks))
    return out


def hole_measures(project: Project, hole: Hole, lid_offset: float = 0.0) -> list[Measure]:
    """Where a hole's middle is: from the left edge of its surface and from the bottom
    (for the bottom and the lid: from the left and the front)."""
    w, d, h = project.outer_width, project.outer_depth, project.outer_height
    x_axis, y_axis = np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
    if hole.surface == SIDE:
        r = project.outer_diameter / 2 + GAP
        a = np.radians(hole.u)
        x, y = r * np.sin(a), -r * np.cos(a)
        z = h / 2 + hole.v
        tangent = np.array([np.cos(a), np.sin(a), 0.0])
        return [_measure((x, y, 0.0), (x, y, z), z, tangent)]
    if hole.surface in (BOTTOM, LID):
        z = project.bottom + GAP if hole.surface == BOTTOM else lid_top_z(project) + GAP + lid_offset
        out = []
        if hole.u + w / 2 > 0.5:
            out.append(_measure((-w / 2, hole.v, z), (hole.u, hole.v, z), hole.u + w / 2, y_axis))
        if hole.v + d / 2 > 0.5:
            out.append(_measure((hole.u, -d / 2, z), (hole.u, hole.v, z), hole.v + d / 2, x_axis))
        return out
    center, normal, right, up = (np.array(v, float) for v in surface_frame(project, hole.surface))
    span = w if abs(right[0]) > 0.5 else d
    lift = normal * GAP

    def point(u, v):
        return center + right * u + up * v + lift
    out = []
    if hole.u + span / 2 > 0.5:
        out.append(_measure(point(-span / 2, hole.v), point(hole.u, hole.v), hole.u + span / 2, up))
    out.append(_measure(point(hole.u, -h / 2), point(hole.u, hole.v), h / 2 + hole.v, right))
    return out


def _measure(start, end, value: float, across) -> Measure:
    """A measurement line with short marks across both ends (along `across`)."""
    start, end = np.array(start, float), np.array(end, float)
    mark = np.array(across, float) * 1.5
    marks = [(tuple(map(float, p - mark)), tuple(map(float, p + mark))) for p in (start, end)]
    return Measure(tuple(map(float, start)), tuple(map(float, end)), mm(value), marks)
