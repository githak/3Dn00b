"""Rule-based checks that explain problems in everyday language.

Each rule returns Issue objects. "error" blocks export (the result would be
broken or unprintable), "warning" is probably a mistake, "info" is advice.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from . import geometry, mounts
from .model import (ALONG_V, BACK, BOTTOM, BOX, FRONT, LEFT, LID, MIN_EDGE, RIGHT,
                    SURFACE_LABELS, VENT, Hole, Project, clamp_hole, comfortable_margin,
                    compartment_size, divider_positions, divider_top, has_dividers,
                    hole_edge_clearance, hole_limits, lip_outer_offset, lip_wall, opening_gap,
                    point_near_opening)

ERROR, WARNING, INFO = "error", "warning", "info"
_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}


@dataclass
class Issue:
    level: str
    message: str
    hint: str = ""
    hole_id: str | None = None
    # Optional one-click fix: move hole `hole_id` (or posts `mount_id`) to (u, v).
    fix: tuple[float, float] | None = None
    fix_label: str = ""
    mount_id: str | None = None


def _mm(value: float) -> str:
    return f"{value:.1f} mm".replace(".0 mm", " mm")


def hole_name(project: Project, hole: Hole) -> str:
    index = next((i for i, h in enumerate(project.holes) if h.id == hole.id), 0) + 1
    return f"Hole {index}"


def _check_divider_size(p: Project) -> list[Issue]:
    if not has_dividers(p):
        return []
    w, d = compartment_size(p)
    if min(w, d) < 3:
        return [Issue(ERROR, "There are too many compartments for this size; they'd be too narrow.",
                      "Use fewer compartments, thinner dividers or a bigger box.")]
    return []


def check_size(project: Project) -> list[Issue]:
    """Only the basic size rules; cheap, and needed before geometry can be built."""
    issues = _check_size(project)
    if not has_errors(issues):
        issues += _check_divider_size(project)
    return sorted(issues, key=lambda i: _ORDER[i.level])


def check(project: Project, parts: geometry.Parts | None = None) -> list[Issue]:
    issues: list[Issue] = []
    issues += _check_size(project)
    if not has_errors(issues):
        issues += _check_divider_size(project)
    if not has_errors(issues):
        issues += _check_lid(project)
        issues += _check_holes(project)
        issues += _check_dividers(project)
        issues += _check_mounts(project)
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
        if hole_limits(p, hole, MIN_EDGE) is None:
            out.append(Issue(ERROR, f"{name} ({hole.size_label}) is too big for the {where}.",
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
        if hole.kind == VENT:
            out += _check_vent(hole, name)
        # The printer has to bridge across the top of an opening in a wall.
        bridge = (hole.slot if hole.kind == VENT and hole.slot_direction == ALONG_V
                  else hole.half_extents[0] * 2)
        if hole.surface not in (BOTTOM, LID) and bridge > 15:
            out.append(Issue(INFO, f"{name} is wide. Its top edge may print a bit rough.",
                             "That's normal for big openings in walls and usually fine.", hole.id))

    for a, b in itertools.combinations(placed, 2):
        if a.surface != b.surface:
            continue
        gap = opening_gap(p, a, b)
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


def _check_dividers(p: Project) -> list[Issue]:
    out = []
    if p.shape != BOX:
        if p.dividers.enabled:
            out.append(Issue(INFO, "Dividers are only for boxes, so this round container has none.",
                             "They come back if you switch to a box."))
        return out
    if not p.dividers.enabled:
        return out
    d = p.dividers
    w, dp = compartment_size(p)
    if min(w, dp) < 12:
        out.append(Issue(WARNING, f"Each compartment is only {_mm(w)} × {_mm(dp)}, which is hard "
                         "to reach into.", "Use fewer compartments or a bigger box."))
    if d.thickness < 1.0:
        out.append(Issue(WARNING, f"Dividers of {_mm(d.thickness)} are thin and may break.",
                         "1.2 to 2 mm works well."))
    if p.lid.enabled and d.height == 0:
        out.append(Issue(INFO, "The dividers have small notches at their ends so the lid's lip fits.",
                         "They also stop just below the lid."))
    xs, ys = divider_positions(p)
    top = divider_top(p)
    half = d.thickness / 2
    for hole in p.holes:
        hu, hv = hole.half_extents
        if hole.surface == BOTTOM:
            hit = (any(abs(hole.u - x) < hu + half for x in xs)
                   or any(abs(hole.v - y) < hv + half for y in ys))
        elif hole.surface in (FRONT, BACK, LEFT, RIGHT):
            along = {FRONT: xs, BACK: [-x for x in xs], LEFT: [-y for y in ys], RIGHT: ys}[hole.surface]
            low = p.outer_height / 2 + hole.v - hv
            hit = low < top and any(abs(hole.u - pos) < hu + half for pos in along)
        else:
            continue
        if hit:
            out.append(Issue(WARNING, f"{hole_name(p, hole)} is where a divider meets the "
                             f"{SURFACE_LABELS[hole.surface].lower()}, so the divider blocks part of it.",
                             "Move the hole into one of the compartments.", hole.id))
    return out


def mount_name(p: Project, m) -> str:
    index = next((i for i, x in enumerate(p.mounts) if x.id == m.id), 0) + 1
    return f"Posts {index} ({mounts.BOARDS[m.board].short})"


def _check_mounts(p: Project) -> list[Issue]:
    out = []
    xs, ys = divider_positions(p) if has_dividers(p) else ([], [])
    div_top = divider_top(p)
    for m in p.mounts:
        name = mount_name(p, m)
        screw = mounts.SCREWS[m.screw]
        size = mounts.board_size(m)
        top = mounts.board_bottom(p, m) + (mounts.BOARD_THICKNESS if size else 0.0)
        ceiling = p.outer_height - (p.lid.gap * 2 if p.lid.enabled else 0.0)
        if m.board == "custom" and (m.spacing_x >= m.board_width or m.spacing_y >= m.board_depth):
            out.append(Issue(ERROR, f"{name}: the holes are further apart than the board is big.",
                             "Check the board size and the hole spacing.", mount_id=m.id))
            continue
        if top > ceiling:
            what = "board" if size else "posts"
            out.append(Issue(ERROR, f"{name}: the {what} would stick out of the top of the box.",
                             "Make the posts shorter or the box taller.", mount_id=m.id))
        room = mounts.clearance(p, m)
        need = mounts.needed_clearance(p, m)
        fix = mounts.clamp_mount(p, m, m.u, m.v)
        fix_label = "Move to the nearest spot that fits"
        if room < 0:
            what = "The board doesn't fit" if size else "A post runs into the wall"
            out.append(Issue(ERROR, f"{name}: {what[0].lower() + what[1:]} there.",
                             "Move it further in, or turn it.", mount_id=m.id, fix=fix,
                             fix_label=fix_label))
        elif room < need - 1e-6:
            if need > 1.0:
                msg = f"{name}: the board would hit the lid's lip."
                hint = "Move it away from the wall, or make the posts shorter."
            else:
                msg = f"{name}: the board touches the wall."
                hint = "Leave at least 1 mm of room so it goes in easily."
            out.append(Issue(WARNING if need <= 1.0 else ERROR, msg, hint, mount_id=m.id,
                             fix=fix, fix_label=fix_label))
        if m.screw == "M1":
            out.append(Issue(WARNING, f"{name}: holes for M1 screws are tiny ({screw.pilot} mm) and "
                             "may close up when printed.", "You may need to drill them out.",
                             mount_id=m.id))
        if m.length > 6 * screw.post:
            out.append(Issue(WARNING, f"{name}: the posts are tall and thin and may snap.",
                             "Use shorter posts or a bigger screw size.", mount_id=m.id))
        r = mounts.post_radius(m)
        posts = mounts.post_positions(m)
        if any(abs(x - dx) < r + 0.8 for x, _ in posts for dx in xs) or \
                any(abs(y - dy) < r + 0.8 for _, y in posts for dy in ys):
            out.append(Issue(WARNING, f"{name}: a post stands on a divider.",
                             "Move the posts into a compartment.", mount_id=m.id))
        elif size and div_top > mounts.board_bottom(p, m):
            corners = mounts.board_corners(m)
            lo_x, hi_x = min(c[0] for c in corners), max(c[0] for c in corners)
            lo_y, hi_y = min(c[1] for c in corners), max(c[1] for c in corners)
            if any(lo_x < x < hi_x for x in xs) or any(lo_y < y < hi_y for y in ys):
                out.append(Issue(WARNING, f"{name}: the board would rest on a divider.",
                                 "Move it into one compartment, or use lower dividers.",
                                 mount_id=m.id))
        for hole in p.holes:
            if hole.surface == BOTTOM and any(
                    point_near_opening(p, hole, x, y, r) for x, y in posts):
                out.append(Issue(WARNING, f"{hole_name(p, hole)} is under a post of {name}.",
                                 "Move the hole or the posts.", hole.id))
    for a, b in itertools.combinations(p.mounts, 2):
        out += _check_stacking(p, a, b)
    return out


def _check_stacking(p: Project, a, b) -> list[Issue]:
    """Two sets of posts whose areas overlap, seen from above.

    That's fine when one board sits high enough above the other: flat boards
    are approved, boards with tall connectors get a reminder to check.
    """
    ax0, ax1, ay0, ay1 = mounts.footprint_box(a)
    bx0, bx1, by0, by1 = mounts.footprint_box(b)
    if ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0:
        return []
    lower, upper = sorted((a, b), key=lambda m: mounts.board_bottom(p, m))
    low_name, up_name = mount_name(p, lower), mount_name(p, upper)
    # Posts of the upper set stand on the floor: they must not need to go through the lower board.
    corners = mounts.board_corners(lower)
    if corners:
        x0, x1 = min(c[0] for c in corners), max(c[0] for c in corners)
        y0, y1 = min(c[1] for c in corners), max(c[1] for c in corners)
        r = mounts.post_radius(upper)
        if upper.length > lower.length and any(
                x0 - r < x < x1 + r and y0 - r < y < y1 + r for x, y in mounts.post_positions(upper)):
            return [Issue(ERROR, f"A post of {up_name} would have to go through the board of "
                          f"{low_name}.", "Turn or move one of them so the posts stand beside "
                          "the lower board.", mount_id=upper.id)]
    if not mounts.board_size(lower):
        if mounts.board_size(upper) and mounts.board_bottom(p, upper) - mounts.board_top(p, lower) >= -1e-6:
            return []           # a single post under a board just supports it
        return [Issue(WARNING, f"{low_name} and {up_name} overlap.", "Move one of them.",
                      mount_id=b.id)]
    gap = mounts.board_bottom(p, upper) - mounts.board_top(p, lower)
    need = mounts.room_above(lower)
    if gap < need - 1e-6:
        if gap <= 0:
            return [Issue(ERROR, f"{low_name} and {up_name} overlap at the same height.",
                          f"Move one of them, or make the posts of one at least {_mm(need - gap)} "
                          "taller so it sits above the other.", mount_id=b.id)]
        return [Issue(ERROR, f"{up_name} sits only {_mm(gap)} above {low_name}, which needs "
                      f"{_mm(need)} of room above it.",
                      f"Make the posts of {up_name} {_mm(need - gap)} taller.", mount_id=upper.id)]
    if not mounts.BOARDS[lower.board].flat:
        what = mounts.BOARDS[lower.board].tall_parts or "parts"
        return [Issue(WARNING, f"{up_name} sits {_mm(gap)} above {low_name}. Check that the "
                      f"{what} of {low_name} fit underneath.",
                      "Their height varies between board versions; measure yours.",
                      mount_id=upper.id)]
    return []


def _check_vent(hole: Hole, name: str) -> list[Issue]:
    out = []
    across = hole.width if hole.slot_direction == ALONG_V else hole.height
    if hole.slot > across:
        out.append(Issue(ERROR, f"The slots of {name} are wider than the vent itself.",
                         "Make the slots narrower or the vent bigger.", hole.id))
    if hole.gap < 1.2:
        out.append(Issue(WARNING, f"The strips between the slots of {name} are only {_mm(hole.gap)} "
                         "and may break.", "A gap of 1.5 to 2 mm is stronger.", hole.id))
    if hole.slot < 1.2:
        out.append(Issue(WARNING, f"The slots of {name} are only {_mm(hole.slot)} wide and may "
                         "close up when printed.", "1.5 mm or wider is more reliable.", hole.id))
    return out


def _behind_lip(p: Project, hole: Hole) -> bool:
    if not p.lid.enabled or hole.surface in (BOTTOM, LID):
        return False
    z = p.outer_height / 2 + hole.v
    return z + hole.half_extents[1] > p.outer_height - p.lid.lip_height


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
