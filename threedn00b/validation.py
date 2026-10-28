"""Rule-based checks that explain problems in everyday language.

Each rule returns Issue objects. "error" blocks export (the result would be
broken or unprintable), "warning" is probably a mistake, "info" is advice.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from . import geometry, mounts
from .model import (ALONG_V, BACK, BOTTOM, BOX, CYLINDER, FRONT, LEFT, LID, MIN_EDGE, RIGHT,
                    SCREWS, SIDE, SNAP_BUMP, SURFACE_LABELS, VENT, Hole, Project, has_lip,
                    THREADED, has_screw_lid, has_sliding_lid, has_snap_lid, has_threaded_lid,
                    slide_engage, slide_groove, thread_sizes,
                    lid_ceiling, lid_pilot_depth, lid_screw_positions, wall_corner_zone, clamp_hole, comfortable_margin,
                    compartment_depths, compartment_size, compartment_widths, divider_fillet,
                    has_set_sizes, divider_positions, divider_top,
                    has_dividers, has_frame,
                    hole_edge_clearance, hole_limits, inside_fillet, lip_outer_offset, lip_wall, opening_gap,
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


def _check_inside_corners(p: Project) -> list[Issue]:
    f = inside_fillet(p)
    if f <= 0:
        return []
    room = min(p.inner_height - 2, min(p.inner_width, p.inner_depth) / 2 - 2)
    if has_threaded_lid(p):
        room = min(room, thread_sizes(p).slope_bottom - p.bottom - 1)
    if has_dividers(p):
        room = min(room, min(compartment_size(p)) / 2 - 2)   # dividers get the same joints
    if f > room:
        return [Issue(ERROR, f"Inside corners of {_mm(f)} are too big for this size.",
                      f"Use {_mm(max(room, 0))} or less, or make the object bigger.")]
    return []


def _check_divider_size(p: Project) -> list[Issue]:
    if not has_dividers(p):
        return []
    out = []
    d = p.dividers
    for sizes, count, chosen, across in ((compartment_widths(p), d.across, d.widths, "wide"),
                                         (compartment_depths(p), d.deep, d.depths, "deep")):
        if min(sizes) >= 3:
            continue
        if not has_set_sizes(chosen, count):
            out.append(Issue(ERROR, "There are too many compartments for this size; they'd be "
                                    "too narrow.", "Use fewer compartments, thinner dividers or a "
                                                   "bigger box."))
        elif sizes[-1] < 3:
            direction = "left to right" if across == "wide" else "front to back"
            out.append(Issue(ERROR, f"The compartment sizes set {direction} add up to more than "
                                    f"fits: the last one would be {_mm(sizes[-1])} {across}.",
                             "Make the others smaller, use fewer compartments, or make the box "
                             "bigger."))
        else:
            out.append(Issue(ERROR, f"A compartment only {_mm(min(sizes))} {across} is too narrow "
                                    "to print.", "Make it at least 3 mm."))
    return list({i.message: i for i in out}.values())     # say the same thing once


def check_size(project: Project) -> list[Issue]:
    """Only the basic size rules; cheap, and needed before geometry can be built."""
    issues = _check_size(project)
    if not has_errors(issues):
        issues += _check_divider_size(project) + _check_inside_corners(project)
    return sorted(issues, key=lambda i: _ORDER[i.level])


def check(project: Project, parts: geometry.Parts | None = None) -> list[Issue]:
    issues: list[Issue] = []
    issues += _check_size(project)
    if not has_errors(issues):
        issues += _check_divider_size(project) + _check_inside_corners(project)
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
    if has_screw_lid(p):
        return _check_screw_lid(p)
    if has_sliding_lid(p):
        return _check_sliding_lid(p)
    if p.lid.style == THREADED:
        return _check_threaded_lid(p)
    lid = p.lid
    out = []
    lip_inside = min(p.inner_width, p.inner_depth) - 2 * (lip_outer_offset(p) + lip_wall(p))
    if lip_inside <= 1:
        out.append(Issue(ERROR, "The box is too small inside to hold a lid.",
                         "Make the box bigger or the walls thinner."))
    if lid.lip_height > p.inner_height - 1:
        out.append(Issue(ERROR, "The lid's lip is deeper than the box.",
                         "Make the lip shorter or the box taller."))
    if lid.thickness < 1.2:
        out.append(Issue(WARNING, f"A lid top of {_mm(lid.thickness)} is thin and may bend.",
                         "1.6 mm or more is recommended."))
    if lid.lip_height < 2:
        out.append(Issue(WARNING, "A very short lip won't hold the lid in place well.",
                         "3 to 6 mm works well for most boxes."))
    out += _check_fit_gap(lid)
    if has_snap_lid(p):
        if lid.lip_height < 3.0:
            out.append(Issue(ERROR, "The lip is too short for the snap-on ridges.",
                             "Make the lip at least 3 mm deep."))
        left = p.wall - (SNAP_BUMP - lid.gap + 0.15)
        if left < 0.8:
            out.append(Issue(ERROR, f"The walls are too thin for the snap-on grooves "
                             f"(only {_mm(left)} would be left).", "Use walls of 2 mm or more."))
        out.append(Issue(INFO, "Press the lid down until it clicks into place.",
                         "If it's too hard to close or open, choose a looser fit and reprint "
                         "just the lid."))
    else:
        out.append(Issue(INFO, "How well the lid fits depends on your printer and material.",
                         "If it's too tight or too loose, change the Fit and reprint just the lid."))
    return out


def _check_fit_gap(lid) -> list[Issue]:
    if lid.gap < 0.1:
        return [Issue(WARNING, f"A fit gap of {lid.gap:.2f} mm is very tight. The lid may not go "
                      "on at all.", "Try the Normal fit first.")]
    if lid.gap > 0.6:
        return [Issue(WARNING, f"A fit gap of {lid.gap:.2f} mm is loose. The lid may fall off.",
                      "Try the Normal or Loose fit.")]
    return []


def _check_threaded_lid(p: Project) -> list[Issue]:
    lid = p.lid
    if p.shape != CYLINDER:
        return [Issue(ERROR, "Threaded lids only work on round containers.",
                      "Choose another type of lid, or make it a round container.")]
    out = []
    t = thread_sizes(p)
    if t.opening < 8:                                  # under 16 mm across is hardly usable
        out.append(Issue(ERROR, "The container is too narrow for a threaded lid.",
                         "Make it at least 30 mm across."))
    if t.slope_bottom - p.bottom < 5:
        out.append(Issue(ERROR, "The container is too short for a threaded lid.",
                         f"Make it at least {_mm(p.outer_height - t.slope_bottom + p.bottom + 5)} tall."))
    if lid.thickness < 1.2:
        out.append(Issue(WARNING, f"A lid of {_mm(lid.thickness)} is thin and may bend.",
                         "1.6 mm or more is recommended."))
    out += _check_fit_gap(lid)
    out.append(Issue(INFO, f"Screw the lid on clockwise. The opening at the top is "
                     f"{2 * t.opening:.0f} mm across, a little narrower than the inside.",
                     "If it's stiff, choose a looser fit and reprint just the lid."))
    return out


def _check_sliding_lid(p: Project) -> list[Issue]:
    lid = p.lid
    if p.shape != BOX:
        return [Issue(ERROR, "Sliding lids only work on boxes.", "Choose another type of lid.")]
    out = []
    left = p.wall - slide_engage(p) - lid.gap
    if left < 0.6:
        out.append(Issue(ERROR, f"The walls are too thin to hold a sliding lid (only {_mm(left)} "
                         "would be left beside the groove).", "Use walls of 2 mm or more."))
    if slide_groove(p)[0] - p.bottom < 5:
        out.append(Issue(ERROR, "The box is too low for a sliding lid.", "Make it taller."))
    if lid.thickness < 1.2:
        out.append(Issue(WARNING, f"A lid of {_mm(lid.thickness)} is thin and may bend.",
                         "1.6 mm or more is recommended."))
    out += _check_fit_gap(lid)
    out.append(Issue(INFO, "Slide the lid in from the front.",
                     "If it's stiff, choose a looser fit and reprint just the lid."))
    return out


def _check_screw_lid(p: Project) -> list[Issue]:
    out = []
    lid = p.lid
    screw = SCREWS[lid.screw]
    r = screw.post / 2
    positions = lid_screw_positions(p)
    if p.shape == CYLINDER:
        crowded = math.dist(positions[0], positions[1]) < 2 * r + 1
    else:
        crowded = min(p.inner_width, p.inner_depth) < 4 * r + 2
    if crowded:
        out.append(Issue(ERROR, "The box is too small for the lid's screw columns.",
                         "Make the box bigger, or use smaller screws or a push-on lid."))
    depth = lid_pilot_depth(p)
    if depth < 5:
        out.append(Issue(WARNING, f"The lid screws only have {_mm(depth)} to bite into.",
                         "Make the box taller so they hold better."))
    if lid.thickness < 1.6:
        out.append(Issue(WARNING, f"A lid of {_mm(lid.thickness)} is thin and may crack at the screws.",
                         "2 mm or more is recommended."))
    if lid.screw == "M1":
        out.append(Issue(WARNING, f"Holes for M1 screws are tiny ({screw.pilot} mm) and may close "
                         "up when printed.", "You may need to drill them out."))
    longest = math.floor((lid.thickness + depth - 0.5) * 2) / 2
    out.append(Issue(INFO, f"The lid needs {len(positions)} {lid.screw} screws, up to {longest:g} mm "
                     "long. They cut their own thread into the corner columns.",
                     "Don't overtighten them, or the thread in the plastic can strip."))
    # Things that would run into the screw columns.
    for hole in p.holes:
        name = hole_name(p, hole)
        hu, _ = hole.half_extents
        if hole.surface == SIDE:
            inner_r = p.outer_diameter / 2 - p.wall
            for x, y in positions:
                angle = math.degrees(math.atan2(x, -y))
                arc = math.radians(abs((hole.u - angle + 180.0) % 360.0 - 180.0)) * inner_r
                if arc - hu - r < MIN_EDGE:
                    out.append(Issue(ERROR, f"{name} runs into one of the lid's screw columns.",
                                     "Turn it so it sits between two columns.", hole.id))
                    break
        elif hole.surface == BOTTOM:
            if any(point_near_opening(p, hole, x, y, r) for x, y in positions):
                out.append(Issue(WARNING, f"{name} is under one of the lid's screw columns.",
                                 "Move it away from the corner.", hole.id))
        elif hole.surface == LID:
            for x, y in positions:
                screw_hole = Hole(LID, diameter=screw.clearance, u=x, v=y)
                if opening_gap(p, hole, screw_hole) < 1.0:
                    out.append(Issue(WARNING, f"{name} is too close to a screw hole in the lid.",
                                     "Move it away from the corner.", hole.id))
                    break
    for m in p.mounts:
        if mounts.column_clearance(p, m) < mounts.COLUMN_ROOM - 1e-6:
            out.append(Issue(ERROR, f"{mount_name(p, m)} runs into one of the lid's screw columns.",
                             "Move it away from the corner.", mount_id=m.id,
                             fix=mounts.clamp_mount(p, m, m.u, m.v),
                             fix_label="Move to the nearest spot that fits"))
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
        if _on_neck(p, hole):
            out.append(Issue(ERROR, f"{name} is on the neck, where the lid screws on.",
                             "Move the hole lower.", hole.id, fix, fix_label))
        elif _in_slide_groove(p, hole):
            out.append(Issue(ERROR, f"{name} is where the sliding lid's groove is.",
                             "Move the hole lower.", hole.id, fix, fix_label))
        elif _behind_lip(p, hole):
            out.append(Issue(ERROR, f"{name} is behind the lid's lip, so the lid would cover it from inside.",
                             "Move the hole lower, or make the lid's lip shorter.", hole.id, fix, fix_label))
        elif clearance < MIN_EDGE and _near_screw_column(p, hole):
            out.append(Issue(ERROR, f"{name} runs into the lid's screw column in the corner.",
                             "Move it further from the corner or make it smaller.", hole.id, fix,
                             fix_label))
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
        same = not has_set_sizes(d.widths, d.across) and not has_set_sizes(d.depths, d.deep)
        what = "Each compartment is" if same else "The smallest compartments are"
        out.append(Issue(WARNING, f"{what} only {_mm(w)} × {_mm(dp)}, which is hard "
                         "to reach into.", "Use fewer or bigger compartments, or a bigger box."))
    if d.thickness < 1.0:
        out.append(Issue(WARNING, f"Dividers of {_mm(d.thickness)} are thin and may break.",
                         "1.2 to 2 mm works well."))
    if has_lip(p) and d.height == 0:
        out.append(Issue(INFO, "The dividers have small notches at their ends so the lid's lip fits.",
                         "They also stop just below the lid."))
    if inside_fillet(p) > 0 and divider_fillet(p) == 0:
        out.append(Issue(INFO, "The dividers are lower than the inside corners are big, so where "
                         "they meet the floor and the walls stays sharp.",
                         "Make the dividers taller or the corners smaller to round them too."))
    xs, ys = divider_positions(p)
    top = divider_top(p)
    half = d.thickness / 2 + divider_fillet(p)      # the rounded joint isn't flat either
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
        ceiling = lid_ceiling(p)
        if mounts.is_custom(m) and not mounts.holes_on_board(m):
            what = "the hole is outside" if m.board == "custom1" else "the holes don't fit on"
            out.append(Issue(ERROR, f"{name}: {what} the board.",
                             "Check the board size and where the holes are.", mount_id=m.id))
            continue
        if m.board == "custom2" and m.spacing_x == 0 and m.spacing_y == 0:
            out.append(Issue(ERROR, f"{name}: both holes are in the same place.",
                             "Set how far apart the holes are.", mount_id=m.id))
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
        reach = r + 0.8 + divider_fillet(p)
        if any(abs(x - dx) < reach for x, _ in posts for dx in xs) or \
                any(abs(y - dy) < reach for _, y in posts for dy in ys):
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
        out += _check_frames(p, m, name)
    for a, b in itertools.combinations(p.mounts, 2):
        out += _check_stacking(p, a, b)
    return out


FRAME_ROOM = 0.5      # room kept between a board and a hole's strengthening frame


def _check_frames(p: Project, m, name: str) -> list[Issue]:
    """Does the board run into the frame around a strengthened wall hole?"""
    corners = mounts.board_corners(m)
    if not corners or not any(has_frame(p, h) for h in p.holes):
        return []
    outline = geometry.CrossSection([corners]).offset(FRAME_ROOM, geometry.JoinType.Miter)
    z = mounts.board_bottom(p, m)
    board = geometry.Manifold.extrude(outline, mounts.BOARD_THICKNESS).translate([0.0, 0.0, z])
    out = []
    for hole in p.holes:
        frame = geometry.frame_solid(p, hole)
        if frame is not None and geometry.overlap_volume(board, frame) > 0.001:
            out.append(Issue(ERROR, f"{name}: the board runs into the frame around "
                             f"{hole_name(p, hole)}.",
                             "Move the board away from the wall, change the post length, or turn "
                             "off the hole's frame.", mount_id=m.id))
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


def _near_screw_column(p: Project, hole: Hole) -> bool:
    """Is a wall hole stopped by a screw column (rather than by the wall's end)?"""
    if not has_screw_lid(p) or hole.surface not in (FRONT, BACK, LEFT, RIGHT):
        return False
    span = p.inner_width if hole.surface in (FRONT, BACK) else p.inner_depth
    reach = abs(hole.u) + hole.half_extents[0]
    room_with_column = span / 2 - wall_corner_zone(p, hole.surface) - reach
    room_without = span / 2 - p.inner_corner_radius - reach
    return room_with_column < MIN_EDGE <= room_without


def _on_neck(p: Project, hole: Hole) -> bool:
    if not has_threaded_lid(p) or hole.surface in (BOTTOM, LID):
        return False
    z = p.outer_height / 2 + hole.v
    return z + hole.half_extents[1] > thread_sizes(p).slope_bottom


def _in_slide_groove(p: Project, hole: Hole) -> bool:
    if not has_sliding_lid(p) or hole.surface in (BOTTOM, LID):
        return False
    z = p.outer_height / 2 + hole.v
    return z + hole.half_extents[1] > slide_groove(p)[0]


def _behind_lip(p: Project, hole: Hole) -> bool:
    if not has_lip(p) or hole.surface in (BOTTOM, LID):
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
