"""Rule-based checks that explain problems in everyday language.

Each rule returns Issue objects. "error" blocks export (the result would be
broken or unprintable), "warning" is probably a mistake, "info" is advice.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from . import geometry
from .model import (BOTTOM, LID, MIN_EDGE, SIDE, SURFACE_LABELS, Hole, Project,
                    clamp_hole, comfortable_margin, hole_edge_clearance,
                    lip_outer_offset, lip_wall, wall_limits)

ERROR, WARNING, INFO = "error", "warning", "info"
_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}


@dataclass
class Issue:
    level: str
    message: str
    hint: str = ""
    hole_id: str | None = None
    # Optional one-click fix: move hole `hole_id` to (u, v).
    fix: tuple[float, float] | None = None
    fix_label: str = ""


def _mm(value: float) -> str:
    return f"{value:.1f} mm".replace(".0 mm", " mm")


def hole_name(project: Project, hole: Hole) -> str:
    index = next((i for i, h in enumerate(project.holes) if h.id == hole.id), 0) + 1
    return f"Hole {index}"


def check_size(project: Project) -> list[Issue]:
    """Only the basic size rules; cheap, and needed before geometry can be built."""
    return sorted(_check_size(project), key=lambda i: _ORDER[i.level])


def check(project: Project, parts: geometry.Parts | None = None) -> list[Issue]:
    issues: list[Issue] = []
    issues += _check_size(project)
    if not has_errors(issues):
        issues += _check_lid(project)
        issues += _check_holes(project)
        if parts is None:
            parts = geometry.build_parts(project)
        issues += _check_geometry(project, parts)
    issues.sort(key=lambda i: _ORDER[i.level])
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(i.level == ERROR for i in issues)


# ---------------------------------------------------------------------------

def _check_size(p: Project) -> list[Issue]:
    out = []
    if p.inner_width < 2 or p.inner_depth < 2:
        out.append(Issue(ERROR, "The walls are too thick for this size, so there's no room left inside.",
                         "Make the walls thinner or the object bigger."))
    if p.inner_height < 1:
        out.append(Issue(ERROR, "The bottom is as thick as the whole object.",
                         "Make the bottom thinner or the object taller."))
    largest = max(p.outer_width, p.outer_depth, p.outer_height)
    if largest > 300:
        out.append(Issue(WARNING, f"The object is {_mm(largest)} across. That's larger than most printers.",
                         "Check your printer's build size."))
    if p.wall < 1.2:
        out.append(Issue(WARNING, f"Walls of {_mm(p.wall)} are thin and can break easily.",
                         "1.6 to 2.4 mm is a good everyday wall thickness."))
    if p.bottom < 1.0:
        out.append(Issue(WARNING, f"A bottom of {_mm(p.bottom)} is thin and may be see-through or weak.",
                         "1.2 mm or more is recommended."))
    return out


def _check_lid(p: Project) -> list[Issue]:
    if not p.lid.enabled:
        return []
    lid = p.lid
    out = []
    lip_inside = min(p.inner_width, p.inner_depth) - 2 * (lip_outer_offset(p) + lip_wall(p))
    if lip_inside <= 1:
        out.append(Issue(ERROR, "The box is too small inside to hold a lid.",
                         "Make the box bigger or the walls thinner."))
    if lid.lip_height > p.inner_height - 1:
        out.append(Issue(ERROR, "The lid's lip is deeper than the box.",
                         "Make the lip shorter or the box taller."))
    if lid.gap < 0.1:
        out.append(Issue(WARNING, f"A fit gap of {lid.gap:.2f} mm is very tight. The lid may not go on at all.",
                         "Try the Normal fit first."))
    elif lid.gap > 0.6:
        out.append(Issue(WARNING, f"A fit gap of {lid.gap:.2f} mm is loose. The lid may fall off.",
                         "Try the Normal or Loose fit."))
    if lid.thickness < 1.2:
        out.append(Issue(WARNING, f"A lid top of {_mm(lid.thickness)} is thin and may bend.",
                         "1.6 mm or more is recommended."))
    if lid.lip_height < 2:
        out.append(Issue(WARNING, "A very short lip won't hold the lid in place well.",
                         "3 to 6 mm works well for most boxes."))
    out.append(Issue(INFO, "How well the lid fits depends on your printer and material.",
                     "If it's too tight or too loose, change the Fit and reprint just the lid."))
    return out


def _check_holes(p: Project) -> list[Issue]:
    out = []
    margin = comfortable_margin(p)
    valid_surfaces = p.surfaces()
    placed: list[Hole] = []
    for hole in p.holes:
        name = hole_name(p, hole)
        where = SURFACE_LABELS.get(hole.surface, hole.surface).lower()
        if hole.surface not in valid_surfaces:
            if hole.surface == LID:
                out.append(Issue(ERROR, f"{name} is on the lid, but the lid is turned off.",
                                 "Turn the lid back on, or remove this hole.", hole.id))
            else:
                out.append(Issue(ERROR, f"{name} is on a surface this shape doesn't have.",
                                 "Move it to another surface or remove it.", hole.id))
            continue
        if wall_limits(p, hole.surface, hole.diameter, MIN_EDGE) is None:
            out.append(Issue(ERROR, f"{name} ({_mm(hole.diameter)}) is too big for the {where}.",
                             "Make the hole smaller or the object bigger.", hole.id))
            continue
        placed.append(hole)
        clearance = hole_edge_clearance(p, hole)
        fix = clamp_hole(p, hole, margin)
        fix_label = "Move to the nearest safe spot"
        if _behind_lip(p, hole):
            out.append(Issue(ERROR, f"{name} is behind the lid's lip, so the lid would cover it from inside.",
                             "Move the hole lower, or make the lid's lip shorter.", hole.id, fix, fix_label))
        elif clearance < MIN_EDGE:
            out.append(Issue(ERROR, f"{name} runs off the edge of the {where}.",
                             "Move it further in or make it smaller.", hole.id, fix, fix_label))
        elif clearance < margin - 1e-6:
            out.append(Issue(WARNING, f"Only {_mm(clearance)} of material is left next to {name}.",
                             f"Keep at least {_mm(margin)} so the edge doesn't break.",
                             hole.id, fix, fix_label))
        if hole.surface not in (BOTTOM, LID) and hole.diameter > 15:
            out.append(Issue(INFO, f"{name} is large. Its top edge may print a bit rough.",
                             "That's normal for big holes in walls and usually fine.", hole.id))

    for a, b in itertools.combinations(placed, 2):
        if a.surface != b.surface:
            continue
        gap = _center_distance(p, a, b) - (a.diameter + b.diameter) / 2
        if gap < 0:
            out.append(Issue(WARNING, f"{hole_name(p, a)} and {hole_name(p, b)} overlap and will become one opening.",
                             "Move them apart if you wanted two holes.", b.id))
        elif gap < min(1.5, margin):
            out.append(Issue(WARNING, f"{hole_name(p, a)} and {hole_name(p, b)} are only {_mm(gap)} apart.",
                             "The thin strip between them may break. Move them further apart.", b.id))
    if p.holes:
        out.append(Issue(INFO, "Printed holes often come out 0.2 to 0.4 mm smaller than designed.",
                         "For screws or cables, make the hole a little bigger than needed."))
    return out


def _behind_lip(p: Project, hole: Hole) -> bool:
    if not p.lid.enabled or hole.surface in (BOTTOM, LID):
        return False
    z = p.outer_height / 2 + hole.v
    return z + hole.diameter / 2 > p.outer_height - p.lid.lip_height


def _center_distance(p: Project, a: Hole, b: Hole) -> float:
    if a.surface == SIDE:
        angle = abs((a.u - b.u + 180.0) % 360.0 - 180.0)
        arc = math.radians(angle) * p.outer_diameter / 2
        return math.hypot(arc, a.v - b.v)
    return math.hypot(a.u - b.u, a.v - b.v)


def _check_geometry(p: Project, parts: geometry.Parts) -> list[Issue]:
    out = []
    for label, solid in (("box", parts.body), ("lid", parts.lid)):
        if solid is None:
            continue
        if not geometry.is_valid_solid(solid):
            out.append(Issue(ERROR, f"The {label} could not be built correctly.",
                             "Try different measurements. If this keeps happening, please report it."))
            continue
        pieces = geometry.piece_count(solid)
        if pieces > 1:
            out.append(Issue(ERROR, f"The {label} would fall apart into {pieces} separate pieces.",
                             "Holes are probably cutting it apart. Make them smaller or move them."))
    if parts.lid is not None and geometry.overlap_volume(parts.body, parts.lid) > 0.01:
        out.append(Issue(ERROR, "The lid bumps into the box and would not fit.",
                         "Use a looser fit or check the lid's lip size."))
    return out
