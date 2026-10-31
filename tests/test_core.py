import math

import numpy as np
import pytest

from threedn00b import geometry, project_io, validation
from threedn00b.model import (BACK, BOTTOM, BOX, CYLINDER, FRONT, INSIDE, LEFT, LID,
                              OUTSIDE, RIGHT, SIDE, Hole, Project, clamp_hole,
                              default_project, hole_edge_clearance, wall_limits)


def box_with_lid(**kw):
    p = default_project(BOX)
    p.lid.enabled = True
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def levels(issues):
    return [i.level for i in issues]


def messages(issues):
    return " | ".join(i.message for i in issues)


# ---- model ---------------------------------------------------------------

def test_inside_mode_adds_walls():
    p = Project(width=50, depth=40, height=30, wall=2, bottom=3, size_mode=INSIDE)
    assert (p.outer_width, p.outer_depth, p.outer_height) == (54, 44, 33)
    assert (p.inner_width, p.inner_depth, p.inner_height) == (50, 40, 30)


def test_switching_size_mode_keeps_object_unchanged():
    p = Project(width=80, depth=60, height=40, wall=2, bottom=2)
    p.set_size_mode(INSIDE)
    assert (p.width, p.depth, p.height) == (76, 56, 38)
    assert (p.outer_width, p.outer_depth, p.outer_height) == (80, 60, 40)
    p.set_size_mode(OUTSIDE)
    assert (p.width, p.depth, p.height) == (80, 60, 40)


def test_switching_shape_moves_wall_holes():
    p = default_project(BOX)
    p.holes = [Hole(RIGHT, 6, 5, 1), Hole(BOTTOM, 4, 3, 3)]
    p.set_shape(CYLINDER)
    assert p.holes[0].surface == SIDE
    assert p.holes[0].u == pytest.approx(90 + math.degrees(5 / 30), abs=0.1)
    assert p.holes[1].surface == BOTTOM
    p.set_shape(BOX)
    assert p.holes[0].surface == RIGHT


def test_wall_limits_respect_lid_lip():
    p = default_project(BOX)
    no_lid = wall_limits(p, FRONT, 8)
    p.lid.enabled = True
    with_lid = wall_limits(p, FRONT, 8)
    assert with_lid[3] == pytest.approx(no_lid[3] - p.lid.lip_height)


def test_huge_hole_does_not_fit():
    p = default_project(BOX)
    assert wall_limits(p, FRONT, 60) is None


def test_clamp_brings_hole_back_onto_surface():
    p = default_project(BOX)
    h = Hole(BOTTOM, 10, 100, 100)
    u, v = clamp_hole(p, h)
    h.u, h.v = u, v
    assert hole_edge_clearance(p, h) >= 2 - 1e-3   # comfortable margin = wall


# ---- geometry ------------------------------------------------------------

def _edges_shared_twice(solid):
    _, tris = geometry.mesh_arrays(solid)
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    edges.sort(axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return np.all(counts == 2)


@pytest.mark.parametrize("shape", [BOX, CYLINDER])
def test_parts_are_watertight_single_solids(shape):
    p = default_project(shape)
    p.lid.enabled = True
    wall = FRONT if shape == BOX else SIDE
    p.holes = [Hole(wall, 8, 0, 0), Hole(BOTTOM, 5, 5, 5), Hole(LID, 6, 0, 0)]
    parts = geometry.build_parts(p)
    for solid in (parts.body, parts.lid):
        assert geometry.is_valid_solid(solid)
        assert geometry.piece_count(solid) == 1
        assert _edges_shared_twice(solid)


def test_plain_box_volume_matches_hand_calculation():
    p = Project(width=50, depth=40, height=30, wall=2, bottom=2, corner_radius=0)
    body = geometry.build_body(p)
    expected = 50 * 40 * 30 - 46 * 36 * 28
    assert body.volume() == pytest.approx(expected, rel=1e-6)


def test_hole_removes_expected_material():
    p = Project(corner_radius=0)
    before = geometry.build_body(p).volume()
    p.holes.append(Hole(FRONT, 10, 0, 0))
    after = geometry.build_body(p).volume()
    assert before - after == pytest.approx(math.pi * 25 * p.wall, rel=0.02)


@pytest.mark.parametrize("fit", ["tight", "normal", "loose"])
def test_lid_does_not_collide_with_body(fit):
    p = box_with_lid()
    p.lid.fit = fit
    parts = geometry.build_parts(p)
    assert geometry.overlap_volume(parts.body, parts.lid) < 1e-6


def test_lid_lip_gap_matches_fit():
    p = Project(width=50, depth=40, wall=2, corner_radius=0)
    p.lid.enabled = True
    lid = geometry.build_lid(p)
    lo = lid.bounding_box()
    # The lip is below the top of the body; its width = inner - 2 * gap.
    lip = lid.trim_by_plane([0, 0, -1], -(p.outer_height - 0.5))
    bb = lip.bounding_box()
    assert bb[3] - bb[0] == pytest.approx(p.inner_width - 2 * p.lid.gap, abs=1e-6)
    assert lo[5] == pytest.approx(p.outer_height + p.lid.thickness)


def test_printable_parts_sit_on_the_plate():
    p = box_with_lid()
    for solid in geometry.build_parts(p).printable().values():
        assert solid.bounding_box()[2] == pytest.approx(0.0, abs=1e-9)


# ---- validation ----------------------------------------------------------

def test_default_box_has_no_problems():
    issues = validation.check(box_with_lid(holes=[Hole(FRONT, 8, 0, -5)]))
    assert not validation.has_errors(issues), messages(issues)
    assert "warning" not in levels(issues), messages(issues)


def test_walls_too_thick_is_an_error():
    issues = validation.check(Project(width=12, depth=12, wall=6, corner_radius=0))
    assert validation.has_errors(issues)


def test_thin_walls_warn():
    issues = validation.check(Project(wall=0.8))
    assert any("thin" in i.message for i in issues)


def test_hole_off_the_edge_is_error_with_fix():
    p = default_project(BOX)
    p.holes = [Hole(FRONT, 8, 39, 0)]
    issues = [i for i in validation.check(p) if i.hole_id]
    assert issues[0].level == "error"
    assert issues[0].fix is not None
    p.holes[0].u, p.holes[0].v = issues[0].fix
    assert not validation.has_errors(validation.check(p))


def test_hole_behind_lid_lip_is_detected():
    p = box_with_lid()
    p.holes = [Hole(FRONT, 6, 0, 16)]
    issues = validation.check(p)
    assert any("lip" in i.message and i.level == "error" for i in issues)


def test_overlapping_holes_warn():
    p = default_project(BOX)
    p.holes = [Hole(FRONT, 8, 0, 0), Hole(FRONT, 8, 5, 0)]
    assert any("overlap" in i.message for i in validation.check(p))


def test_close_holes_on_round_wall_use_arc_distance():
    p = default_project(CYLINDER)
    p.holes = [Hole(SIDE, 8, 179, 0), Hole(SIDE, 8, -179, 0)]
    assert any("overlap" in i.message for i in validation.check(p))


def test_lid_hole_without_lid_is_error():
    p = default_project(BOX)
    p.holes = [Hole(LID, 5, 0, 0)]
    assert validation.has_errors(validation.check(p))


def test_lip_deeper_than_box_is_error():
    p = box_with_lid(height=10)
    p.lid.lip_height = 20
    assert validation.has_errors(validation.check(p))


def test_cut_into_pieces_is_detected():
    p = Project(width=30, depth=30, height=12, corner_radius=0)
    p.holes = [Hole(FRONT, 30, 0, 0), Hole(BACK, 30, 0, 0),
               Hole(LEFT, 30, 0, 0), Hole(RIGHT, 30, 0, 0)]
    # These holes are far too big for their walls, so they are rejected early.
    assert validation.has_errors(validation.check(p))


# ---- persistence and export ----------------------------------------------

def test_project_round_trip(tmp_path):
    p = box_with_lid(name="Screws", size_mode=INSIDE)
    p.lid.fit = "custom"
    p.lid.custom_gap = 0.3
    p.holes = [Hole(FRONT, 7.5, 3, -2), Hole(LID, 5, 0, 0)]
    path = tmp_path / "screws.3dn00b"
    project_io.save_project(p, path)
    assert project_io.load_project(path) == p


def test_newer_file_version_is_rejected(tmp_path):
    data = project_io.to_dict(default_project())
    data["version"] = 99
    with pytest.raises(project_io.ProjectFileError, match="newer"):
        project_io.from_dict(data)


def test_damaged_file_is_rejected(tmp_path):
    data = project_io.to_dict(default_project())
    data["project"]["width"] = "wide"
    with pytest.raises(project_io.ProjectFileError):
        project_io.from_dict(data)
    path = tmp_path / "bad.3dn00b"
    path.write_text("{not json")
    with pytest.raises(project_io.ProjectFileError):
        project_io.load_project(path)


def test_stl_export_writes_each_part(tmp_path):
    p = box_with_lid(name="Tool box!")
    p.holes = [Hole(FRONT, 8, 0, 0)]
    files = project_io.export_stl_files(p, tmp_path)
    assert [f.name for f in files] == ["tool-box-body.stl", "tool-box-lid.stl"]
    tris = project_io.read_stl(files[0])
    assert len(tris) > 12
    assert tris[..., 2].min() == pytest.approx(0, abs=1e-5)
    assert tris[..., 0].max() - tris[..., 0].min() == pytest.approx(p.outer_width, abs=1e-3)


def test_shape_switch_keeps_sideways_offset():
    p = default_project(BOX)
    p.holes = [Hole(FRONT, 6, 10, 0)]
    p.set_shape(CYLINDER)
    assert p.holes[0].u == pytest.approx(math.degrees(10 / 30), abs=0.1)
    p.set_shape(BOX)
    assert p.holes[0].surface == FRONT
    assert p.holes[0].u == pytest.approx(10, abs=0.1)


# ---- picking -------------------------------------------------------------

from threedn00b import picking  # noqa: E402


def test_pick_box_walls_from_outside_and_inside():
    p = default_project(BOX)   # 80 x 60 x 40
    assert picking.surface_at(p, (5, -30, 25), (0, -1, 0), "body") == (FRONT, 5, 5)
    # Inside face of the front wall, seen from above.
    assert picking.surface_at(p, (5, -28, 25), (0, 1, 0), "body")[0] == FRONT
    assert picking.surface_at(p, (40, 7, 20), (1, 0, 0), "body") == (RIGHT, 7, 0)
    assert picking.surface_at(p, (-40, 7, 20), (-1, 0, 0), "body") == (LEFT, -7, 0)
    assert picking.surface_at(p, (3, 4, 2), (0, 0, 1), "body") == (BOTTOM, 3, 4)
    assert picking.surface_at(p, (0, -29, 40), (0, 0, 1), "body") is None   # rim


def test_pick_round_wall_angle():
    p = default_project(CYLINDER)
    surface, u, v = picking.surface_at(p, (30, 0, 50), (1, 0, 0), "body")
    assert surface == SIDE and u == pytest.approx(90)


def test_find_and_snap():
    p = default_project(BOX)
    p.holes = [Hole(FRONT, 8, 10, 0)]
    assert picking.find_hole(p, FRONT, 12, 1) is p.holes[0]
    assert picking.find_hole(p, FRONT, 30, 0) is None
    assert picking.snap(FRONT, 2.4, -1.0) == (0.0, 0.0)
    assert picking.snap(SIDE, 87, 10) == (90.0, 10)


@pytest.mark.parametrize("path", sorted((__import__("pathlib").Path(__file__).parent.parent
                                         / "examples").glob("*.3dn00b")))
def test_examples_open_without_problems(path):
    p = project_io.load_project(path)
    assert not validation.has_errors(validation.check(p))


def test_missing_xcb_cursor_gives_friendly_message(monkeypatch):
    from threedn00b import app
    monkeypatch.setattr(app.sys, "platform", "linux")
    monkeypatch.setattr(app.ctypes.util, "find_library", lambda name: None)
    env = {}
    monkeypatch.setattr(app.os, "environ", env)   # keep the real environment untouched
    assert "sudo apt install libxcb-cursor0" in app.check_display_libraries()
    # On Wayland the app switches to Qt's Wayland backend instead.
    env["WAYLAND_DISPLAY"] = "wayland-0"
    assert app.check_display_libraries() is None
    assert env["QT_QPA_PLATFORM"] == "wayland"
    del env["QT_QPA_PLATFORM"]
    # With the library present nothing changes.
    monkeypatch.setattr(app.ctypes.util, "find_library", lambda name: "libxcb-cursor.so.0")
    assert app.check_display_libraries() is None


# ---- dragging ------------------------------------------------------------

def test_ray_meets_front_wall():
    p = default_project(BOX)   # front wall at y = -30, height 40
    t, u, v, exact = picking.surface_hit(p, FRONT, (5, -100, 25), (0, 1, 0))
    assert exact and t == pytest.approx(70) and (u, v) == pytest.approx((5, 5))
    assert picking.surface_hit(p, FRONT, (5, -100, 25), (0, -1, 0)) is None   # behind


def test_ray_meets_round_wall_and_handles_misses():
    p = default_project(CYLINDER)   # radius 30
    t, u, v, exact = picking.surface_hit(p, SIDE, (100, 0, 40), (-1, 0, 0))
    assert exact and t == pytest.approx(70) and u == pytest.approx(90)
    *_, exact = picking.surface_hit(p, SIDE, (100, 50, 40), (-1, 0, 0))
    assert not exact      # missed, but still gives a usable position for dragging


def test_hole_under_ray_ignores_hidden_holes():
    p = default_project(BOX)
    front, back = Hole(FRONT, 8, 0, 0), Hole(BACK, 8, 0, 0)
    p.holes = [back, front]
    origin, direction = (0, -100, 20), (0, 1, 0)
    assert picking.hole_under_ray(p, origin, direction, mesh_distance=None) is front
    p.holes = [back]
    # The ray hits the front wall 70 mm away; the back hole is hidden behind it.
    assert picking.hole_under_ray(p, origin, direction, mesh_distance=70.0) is None
    assert picking.hole_under_ray(p, (30, -100, 20), direction, None) is None   # off to the side


def test_drag_snaps_to_centre_and_other_holes():
    p = default_project(BOX)
    a, b = Hole(FRONT, 6, -20, 5), Hole(FRONT, 6, 10, 0)
    p.holes = [a, b]
    u, v, note = picking.snap_drag(p, b, 1.5, 4.0)
    assert (u, v) == (0.0, 5.0) and "centre" in note and "Hole 1" in note
    assert picking.snap_drag(p, b, 12.0, -10.0)[:2] == (12.0, -10.0)
    side = default_project(CYLINDER)
    h = Hole(SIDE, 6, 0, 0)
    side.holes = [h]
    assert abs(picking.snap_drag(side, h, 178.0, 20.0)[0]) == 180.0   # straight at the back


def test_broken_pyside_version_is_reported(monkeypatch):
    import PySide6
    from threedn00b import app
    monkeypatch.setattr(app.sys, "version_info", (3, 11, 9))
    monkeypatch.setattr(PySide6, "__version__", "6.12.0")
    assert "pip install -e ." in app.check_pyside_version()
    monkeypatch.setattr(PySide6, "__version__", "6.11.2")
    assert app.check_pyside_version() is None
    monkeypatch.setattr(app.sys, "version_info", (3, 13, 0))
    monkeypatch.setattr(PySide6, "__version__", "6.12.0")
    assert app.check_pyside_version() is None


# ---- rectangular holes -----------------------------------------------------

from threedn00b.model import RECT, opening_gap, surface_frame  # noqa: E402


def _wall_is_open(solid, project, surface, u, v):
    """Shoot a ray straight at the surface at (u, v); True if it passes through that wall."""
    c, n, right, up = surface_frame(project, surface)
    p = np.array(c) + np.array(right) * u + np.array(up) * v
    hits = solid.ray_cast(list(p + np.array(n) * 5), list(p - np.array(n) * 0.5))
    return not hits


@pytest.mark.parametrize("surface", [FRONT, BACK, LEFT, RIGHT, BOTTOM, LID])
def test_rectangle_is_oriented_along_its_surface(surface):
    p = box_with_lid(corner_radius=0)
    hole = Hole(surface, kind=RECT, width=20, height=6, u=4, v=-2)
    p.holes = [hole]
    parts = geometry.build_parts(p)
    solid = parts.lid if surface == LID else parts.body
    assert _wall_is_open(solid, p, surface, 4 + 9, -2)        # near the end of the long side
    assert _wall_is_open(solid, p, surface, 4 - 9, -2 + 2.5)
    assert not _wall_is_open(solid, p, surface, 4, -2 + 4)    # just past the short side
    assert not _wall_is_open(solid, p, surface, 4 + 11, -2)   # just past the long side
    assert geometry.piece_count(solid) == 1 and _edges_shared_twice(solid)


def test_rectangle_on_round_wall():
    p = default_project(CYLINDER)
    p.holes = [Hole(SIDE, kind=RECT, width=12, height=5, u=90, v=0)]
    body = geometry.build_body(p)
    assert body.ray_cast([60, 0, 40], [-60, 0, 40])[0].position[0] < 0   # passes into the far wall
    assert body.ray_cast([60, 0, 44], [-60, 0, 44])[0].position[0] > 0   # above the slot: solid
    assert not validation.has_errors(validation.check(p))


def test_rectangle_limits_and_clamp():
    p = default_project(BOX)    # inner 76 wide, 38 tall walls
    hole = Hole(FRONT, kind=RECT, width=30, height=10, u=40, v=0)
    p.holes = [hole]
    issues = validation.check(p)
    assert validation.has_errors(issues)
    fix = next(i.fix for i in issues if i.fix)
    hole.u, hole.v = fix
    assert not validation.has_errors(validation.check(p))
    assert hole.u + 15 <= 76 / 2 - 2 + 1e-6      # keeps the comfortable margin
    p.holes = [Hole(FRONT, kind=RECT, width=80, height=5)]
    assert any("too big" in i.message for i in validation.check(p))


def test_rectangle_in_rounded_corner_of_bottom_is_detected():
    p = Project(corner_radius=20)                 # inner corner radius 18
    hole = Hole(BOTTOM, kind=RECT, width=10, height=10, u=31, v=21)
    p.holes = [hole]
    assert validation.has_errors(validation.check(p))


def test_gaps_between_mixed_shapes():
    p = default_project(BOX)
    rect = Hole(FRONT, kind=RECT, width=10, height=4, u=0, v=0)
    near = Hole(FRONT, diameter=4, u=9, v=0)        # circle edge 2 mm from the rectangle
    corner = Hole(FRONT, diameter=2, u=8, v=5)     # diagonal from the corner
    other = Hole(FRONT, kind=RECT, width=4, height=4, u=0, v=6)
    assert opening_gap(p, rect, near) == pytest.approx(2.0)
    assert opening_gap(p, rect, corner) == pytest.approx(math.hypot(3, 3) - 1)
    assert opening_gap(p, rect, other) == pytest.approx(2.0)
    assert opening_gap(p, rect, Hole(FRONT, diameter=2, u=1, v=1)) < 0


def test_rectangle_round_trip_and_old_files(tmp_path):
    p = box_with_lid()
    p.holes = [Hole(LEFT, kind=RECT, width=9.5, height=3.6, u=2, v=-4)]
    path = tmp_path / "usb.3dn00b"
    project_io.save_project(p, path)
    assert project_io.load_project(path) == p
    data = project_io.to_dict(p)
    assert data["version"] == project_io.FORMAT_VERSION
    data["version"] = 1                        # files from 0.1/0.2 have no "kind"
    for h in data["project"]["holes"]:
        for key in ("kind", "width", "height"):
            del h[key]
    assert project_io.from_dict(data).holes[0].kind == "round"


# ---- air vents ---------------------------------------------------------------

from threedn00b.model import ALONG_U, VENT  # noqa: E402


def test_vent_fits_as_many_slots_as_possible():
    v = Hole(kind=VENT, width=30, height=15, slot=2, gap=2)
    assert v.slot_count == 8                      # 8 * 2 + 7 * 2 = 30
    v.width = 29.9
    assert v.slot_count == 7
    offsets = [du for du, *_ in Hole(kind=VENT, width=30, height=15).slot_rects()]
    assert offsets[0] == pytest.approx(-offsets[-1])   # centred
    v.slot_direction = ALONG_U
    assert v.slot_count == 4 and v.slot_rects()[0][2:] == (29.9, 2)


@pytest.mark.parametrize("surface", [FRONT, LEFT, BOTTOM, LID])
@pytest.mark.parametrize("direction", ["along_v", "along_u"])
def test_vent_slots_are_cut_where_expected(surface, direction):
    p = box_with_lid(corner_radius=0)
    vent = Hole(surface, kind=VENT, width=20, height=12, slot=2, gap=2, u=3, v=-1,
                slot_direction=direction)
    p.holes = [vent]
    parts = geometry.build_parts(p)
    solid = parts.lid if surface == LID else parts.body
    first, second = vent.slot_rects()[:2]
    # Centre of a slot is open; the strip between two slots is solid.
    assert _wall_is_open(solid, p, surface, 3 + first[0], -1 + first[1])
    between = ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
    assert not _wall_is_open(solid, p, surface, 3 + between[0], -1 + between[1])
    assert geometry.piece_count(solid) == 1 and _edges_shared_twice(solid)


def test_vent_on_round_wall_follows_the_curve():
    p = default_project(CYLINDER)
    vent = Hole(SIDE, kind=VENT, width=40, height=20, u=0, v=0)
    p.holes = [vent]
    body = geometry.build_body(p)
    before = geometry.build_body(default_project(CYLINDER)).volume()
    # Every slot cuts all the way through the curved wall.
    assert before - body.volume() == pytest.approx(vent.slot_count * 2 * 20 * p.wall, rel=0.08)
    assert not validation.has_errors(validation.check(p))


def test_vent_checks():
    p = default_project(BOX)
    p.holes = [Hole(FRONT, kind=VENT, width=20, height=10, slot=1.0, gap=1.0)]
    messages_ = messages(validation.check(p))
    assert "may break" in messages_ and "close up" in messages_
    p.holes = [Hole(FRONT, kind=VENT, width=4, height=10, slot=6)]
    assert validation.has_errors(validation.check(p))
    p.holes = [Hole(FRONT, kind=VENT, width=80, height=10)]          # wall is 76 mm inside
    assert any("runs off" in i.message or "too big" in i.message for i in validation.check(p))


def test_vent_overlapping_a_hole_is_reported():
    p = default_project(BOX)
    p.holes = [Hole(FRONT, kind=VENT, width=30, height=15), Hole(FRONT, diameter=6, u=17, v=0)]
    assert any("overlap" in i.message for i in validation.check(p))


def test_vent_round_trip_and_unknown_kinds(tmp_path):
    p = box_with_lid()
    p.holes = [Hole(LID, kind=VENT, width=25, height=10, slot=1.6, gap=2.4,
                    slot_direction="along_u")]
    path = tmp_path / "vent.3dn00b"
    project_io.save_project(p, path)
    assert project_io.load_project(path) == p
    data = project_io.to_dict(p)
    data["project"]["holes"][0]["kind"] = "hexagon"
    with pytest.raises(project_io.ProjectFileError):
        project_io.from_dict(data)


# ---- dividers --------------------------------------------------------------

from threedn00b.model import (Dividers, TRAY_TEMPLATE, compartment_size,  # noqa: E402
                              divider_positions, divider_top)


def test_compartments_are_evenly_sized():
    p = Project(width=100, depth=60, wall=2, corner_radius=0, dividers=Dividers(across=3, deep=2,
                                                                                 thickness=2))
    w, d = compartment_size(p)
    assert w == pytest.approx((96 - 2 * 2) / 3) and d == pytest.approx((56 - 2) / 2)
    xs, ys = divider_positions(p)
    edges = [-48] + [x for x in xs for x in (x - 1, x + 1)] + [48]
    widths = [b - a for a, b in zip(edges[::2], edges[1::2])]
    assert widths == pytest.approx([w] * 3) and ys == pytest.approx([0])


def test_dividers_add_the_expected_material():
    p = Project(width=100, depth=60, height=30, wall=2, bottom=2, corner_radius=0)
    plain = geometry.build_body(p).volume()
    p.dividers = Dividers(across=2, deep=1, thickness=2)
    body = geometry.build_body(p)
    assert body.volume() - plain == pytest.approx(2 * 56 * 28, rel=1e-6)
    assert geometry.piece_count(body) == 1 and _edges_shared_twice(body)


@pytest.mark.parametrize("fit", ["tight", "normal", "loose"])
@pytest.mark.parametrize("corner", [0.0, 4.0, 15.0])
def test_dividers_leave_room_for_the_lid(fit, corner):
    p = box_with_lid(corner_radius=corner, dividers=Dividers(across=3, deep=3))
    p.lid.fit = fit
    parts = geometry.build_parts(p)
    assert geometry.overlap_volume(parts.body, parts.lid) < 1e-6
    assert geometry.piece_count(parts.body) == 1 and _edges_shared_twice(parts.body)
    assert not validation.has_errors(validation.check(p, parts))


def test_lower_dividers():
    p = default_project(BOX)
    p.dividers = Dividers(across=2, height=10)
    assert divider_top(p) == pytest.approx(p.bottom + 10)
    xs, _ = divider_positions(p)
    body = geometry.build_body(p)
    hits = body.ray_cast([xs[0], 0, 100], [xs[0], 0, 0])
    assert hits[0].position[2] == pytest.approx(p.bottom + 10)


def test_hole_where_divider_meets_wall_or_floor_is_reported():
    p = default_project(BOX)
    p.dividers = Dividers(across=2, deep=2)
    p.holes = [Hole(FRONT, 6, 0, 0), Hole(BOTTOM, 5, 10, 0), Hole(LEFT, 5, 10, 0)]
    blocked = {i.hole_id for i in validation.check(p) if "divider meets" in i.message}
    assert blocked == {p.holes[0].id, p.holes[1].id}
    p.dividers.height = 5                       # low dividers stay below the front hole
    blocked = {i.hole_id for i in validation.check(p) if "divider meets" in i.message}
    assert blocked == {p.holes[1].id}


def test_too_many_compartments_is_an_error():
    p = default_project(BOX)
    p.dividers = Dividers(across=12, thickness=5)
    issues = validation.check(p)
    assert validation.has_errors(issues) and validation.has_errors(validation.check_size(p))
    p.dividers = Dividers(across=6)
    assert any("hard to reach" in i.message for i in validation.check(p))


def test_round_containers_ignore_dividers():
    p = default_project(BOX)
    p.dividers = Dividers(across=3)
    p.set_shape(CYLINDER)
    assert geometry.build_dividers(p) is None
    assert any("only for boxes" in i.message for i in validation.check(p))


def test_tray_template_is_ready_to_print():
    p = default_project(TRAY_TEMPLATE)
    assert p.dividers.across * p.dividers.deep == 6
    issues = validation.check(p)
    assert not validation.has_errors(issues) and "warning" not in levels(issues)


def test_dividers_round_trip_and_type_checks(tmp_path):
    p = box_with_lid(dividers=Dividers(across=4, deep=2, thickness=1.2, height=12))
    path = tmp_path / "organiser.3dn00b"
    project_io.save_project(p, path)
    assert project_io.load_project(path) == p
    data = project_io.to_dict(p)
    data["project"]["dividers"]["across"] = 2.5
    with pytest.raises(project_io.ProjectFileError):
        project_io.from_dict(data)
    del data["project"]["dividers"]           # files from before dividers existed
    assert project_io.from_dict(data).dividers == Dividers()


# ---- screw posts -------------------------------------------------------------

from threedn00b import mounts  # noqa: E402
from threedn00b.model import Mount  # noqa: E402


def _spacing(m):
    pts = mounts.post_positions(m)
    xs, ys = sorted({round(x, 2) for x, _ in pts}), sorted({round(y, 2) for _, y in pts})
    return round(xs[-1] - xs[0], 2), round(ys[-1] - ys[0], 2)


def test_board_hole_patterns_match_the_datasheets():
    assert _spacing(Mount(board="rpi-ab")) == (58.0, 49.0)
    assert _spacing(Mount(board="rpi-3a")) == (58.0, 49.0)
    assert _spacing(Mount(board="rpi-zero")) == (58.0, 23.0)
    assert _spacing(Mount(board="pico")) == (47.0, 11.4)
    assert _spacing(Mount(board="custom", spacing_x=50, spacing_y=30)) == (50.0, 30.0)
    for key, board in mounts.BOARDS.items():
        m = mounts.new_mount(Project(width=200, depth=200), key)   # with its starting sizes
        size = mounts.board_size(m)
        if size:   # every hole lies inside its board
            assert all(abs(x) < size[0] / 2 and abs(y) < size[1] / 2
                       for x, y in mounts.post_positions(m)), key


def test_turning_keeps_the_pattern():
    m = Mount(board="uno", u=5, v=-3)
    before = mounts.post_positions(m)
    m.rotation = 90
    after = mounts.post_positions(m)
    dist = lambda pts: sorted(round(math.dist(a, b), 6) for a in pts for b in pts)  # noqa: E731
    assert dist(before) == dist(after)
    assert mounts.half_extents(m) == pytest.approx((53.3 / 2, 68.6 / 2))


def test_posts_have_pilot_holes_that_stop_at_the_floor():
    p = Project(width=110, depth=80, height=40)
    m = mounts.new_mount(p, "rpi-ab")
    p.mounts = [m]
    body = geometry.build_body(p)
    assert geometry.piece_count(body) == 1 and _edges_shared_twice(body)
    x, y = mounts.post_positions(m)[0]
    pilot = mounts.SCREWS["M2.5"].pilot / 2
    assert body.ray_cast([x, y, 100], [x, y, -5])[0].position[2] == pytest.approx(p.bottom)
    assert body.ray_cast([x + pilot + 0.2, y, 100], [x + pilot + 0.2, y, -5])[0].position[2] == \
        pytest.approx(p.bottom + m.length)
    assert body.ray_cast([x, y, -5], [x, y, 100])[0].position[2] == pytest.approx(0)  # floor intact
    assert mounts.max_screw_length(m) == 7.0


def test_board_that_does_not_fit_is_an_error():
    p = default_project(BOX)                     # 76 x 56 inside: a Pi 4 (85 x 56) can't fit
    p.mounts = [mounts.new_mount(p, "rpi-ab")]
    assert validation.has_errors(validation.check(p))
    p.width = 110
    p.mounts = [mounts.new_mount(p, "rpi-ab")]
    assert not validation.has_errors(validation.check(p))


def test_board_near_a_wall_gets_a_fix():
    p = Project(width=110, depth=80, height=40)
    m = mounts.new_mount(p, "rpi-ab")
    m.u = 12
    p.mounts = [m]
    issue = next(i for i in validation.check(p) if i.mount_id)
    assert issue.level == "error" and issue.fix
    m.u, m.v = issue.fix
    assert not any(i.mount_id for i in validation.check(p) if i.level != "info")
    m.u += 1.0     # now only 0.5 mm from the wall
    assert any(i.level == "warning" and "touches the wall" in i.message for i in validation.check(p))


def test_board_too_high_or_hitting_the_lid_lip():
    p = Project(width=110, depth=80, height=30)
    p.lid.enabled = True
    m = mounts.new_mount(p, "rpi-zero")
    p.mounts = [m]
    m.length = 30
    assert any("stick out" in i.message for i in validation.check(p))
    m.length = 23                                # board top 26.6: level with the lid's lip
    lim = p.inner_width / 2 - 65 / 2
    m.u = lim - 1.5                              # 1.5 mm from the wall: fine without a lid
    assert any("lip" in i.message for i in validation.check(p))
    p.lid.enabled = False
    assert not any(i.mount_id for i in validation.check(p) if i.level != "info")


def test_posts_and_dividers_holes_and_other_boards():
    p = Project(width=150, depth=100, height=40, dividers=Dividers(across=2))
    pico = mounts.new_mount(p, "single")
    p.mounts = [pico]
    assert any("stands on a divider" in i.message for i in validation.check(p))
    zero = mounts.new_mount(p, "rpi-zero")
    p.mounts = [zero]
    assert any("rest on a divider" in i.message for i in validation.check(p))
    p.dividers.height = 3                        # low dividers stay under the board
    assert not any("divider" in i.message for i in validation.check(p))
    x, y = mounts.post_positions(zero)[0]
    p.holes = [Hole(BOTTOM, 3, x, y)]
    assert any("under a post" in i.message for i in validation.check(p))
    p.holes = []
    p.mounts = [zero, mounts.new_mount(p, "pico")]
    assert any("overlap" in i.message for i in validation.check(p))


def test_screw_warnings_and_custom_board_errors():
    p = Project(width=110, depth=80, height=60)
    single = mounts.new_mount(p, "single")
    single.screw, single.length = "M1", 30
    p.mounts = [single]
    msgs = messages(validation.check(p))
    assert "tiny" in msgs and "tall and thin" in msgs
    p.mounts = [Mount(board="custom", spacing_x=70, board_width=60)]
    assert validation.has_errors(validation.check(p))


def test_posts_in_round_container():
    p = default_project(CYLINDER)               # 56 mm across inside
    p.mounts = [mounts.new_mount(p, "pico")]
    assert not validation.has_errors(validation.check(p))
    p.mounts = [mounts.new_mount(p, "rpi-ab")]
    assert validation.has_errors(validation.check(p))


def test_posts_round_trip_and_bad_values(tmp_path):
    p = Project(width=110, depth=80, height=40)
    m = mounts.new_mount(p, "uno")
    m.rotation, m.length = 270, 8
    p.mounts = [m, Mount(board="custom", spacing_x=40, spacing_y=20, board_width=50, board_depth=30)]
    path = tmp_path / "board.3dn00b"
    project_io.save_project(p, path)
    assert project_io.load_project(path) == p
    for key, bad in (("board", "rpi-99"), ("screw", "M7"), ("rotation", 45)):
        data = project_io.to_dict(p)
        data["project"]["mounts"][0][key] = bad
        with pytest.raises(project_io.ProjectFileError):
            project_io.from_dict(data)


# ---- stacked boards ----------------------------------------------------------

def _stack(lower_board, upper_board, upper_length, turn=90, box=(110, 100, 45)):
    p = Project(width=box[0], depth=box[1], height=box[2])
    lower, upper = mounts.new_mount(p, lower_board), mounts.new_mount(p, upper_board)
    upper.rotation, upper.length = turn, upper_length
    p.mounts = [lower, upper]
    return p, [i for i in validation.check(p) if i.mount_id]


def test_flat_boards_can_cross_when_there_is_room():
    # Pi Zero on 6 mm posts: board top at 7.6 mm above the floor, needs 4 + 1 mm above it.
    _, issues = _stack("rpi-zero", "rpi-zero", 12.6)
    assert issues == []
    _, issues = _stack("rpi-zero", "rpi-zero", 12.0)
    assert issues[0].level == "error" and "0.6 mm taller" in issues[0].hint


def test_same_height_overlap_is_an_error():
    _, issues = _stack("rpi-zero", "rpi-zero", 6.0)
    assert issues[0].level == "error" and "same height" in issues[0].message


def _zero_reaching_over_pi4(length):
    # The Pi Zero's posts stand just behind the Pi 4 (their edges at y 3.25), while
    # its board reaches over the Pi 4's back edge (from y 2.75).
    p = Project(width=110, depth=140, height=60)
    pi4 = Mount(board="rpi-ab", v=-25)                       # spans y -53 .. 3
    zero = Mount(board="rpi-zero", v=17.75, length=length)   # posts at y 6.25 and 29.25
    p.mounts = [pi4, zero]
    return [i for i in validation.check(p) if i.mount_id]


def test_boards_with_tall_sockets_only_get_a_reminder():
    issues = _zero_reaching_over_pi4(30.0)
    assert [i.level for i in issues] == ["warning"]
    assert "USB and network sockets" in issues[0].message
    issues = _zero_reaching_over_pi4(15.0)                 # Pi 4 needs 17 mm above its top
    assert [i.level for i in issues] == ["error"]


def test_posts_may_not_go_through_the_lower_board():
    # Same direction, stacked straight above: the upper posts land on the lower board.
    _, issues = _stack("rpi-zero", "rpi-zero", 20.0, turn=0)
    assert issues[0].level == "error" and "go through" in issues[0].message


def test_parts_height_can_be_changed():
    p, _ = _stack("rpi-zero", "rpi-zero", 12.6)
    p.mounts[0].parts_height = 8.5               # GPIO header soldered on
    assert any("needs 9.5 mm" in i.message for i in validation.check(p))
    data = project_io.to_dict(p)
    del data["project"]["mounts"][0]["parts_height"]     # files from 0.6.0
    assert mounts.parts_height(project_io.from_dict(data).mounts[0]) == 4.0


# ---- screwed-down lid --------------------------------------------------------

from threedn00b.model import SCREWED, lid_screw_positions  # noqa: E402


def screwed_box(**kw):
    p = box_with_lid(**kw)
    p.lid.style = SCREWED
    return p


def test_screw_columns_sit_in_the_corners():
    p = screwed_box(corner_radius=0)              # inside 76 x 56, M3 column radius 3.5
    assert sorted(lid_screw_positions(p)) == [(-34.5, -24.5), (-34.5, 24.5), (34.5, -24.5), (34.5, 24.5)]
    p = screwed_box(corner_radius=15)             # inside corner radius 13: tangent to the curve
    x, y = lid_screw_positions(p)[0]
    arc_centre = (-(38 - 13), -(28 - 13))
    assert math.dist((x, y), arc_centre) == pytest.approx(13 - 3.5)


@pytest.mark.parametrize("shape,corner", [(BOX, 0.0), (BOX, 4.0), (BOX, 20.0), (CYLINDER, 0.0)])
def test_screwed_lid_geometry(shape, corner):
    p = default_project(shape)
    p.corner_radius = corner
    p.lid.enabled, p.lid.style = True, SCREWED
    parts = geometry.build_parts(p)
    body, lid = parts.body, parts.lid
    for solid in (body, lid):
        assert geometry.piece_count(solid) == 1 and _edges_shared_twice(solid)
    assert body.bounding_box() == pytest.approx(geometry.build_body(default_project(shape)).bounding_box())
    assert lid.bounding_box()[2] == pytest.approx(p.outer_height)        # flat: no lip
    assert geometry.overlap_volume(body, lid) < 1e-6
    for x, y in lid_screw_positions(p):
        # Pilot hole from the top, 16 mm deep; the lid's hole goes right through.
        assert body.ray_cast([x, y, 200], [x, y, -5])[0].position[2] == pytest.approx(p.outer_height - 16)
        assert not lid.ray_cast([x, y, 200], [x, y, p.outer_height - 0.5])
    assert not validation.has_errors(validation.check(p, parts))


def test_screwed_lid_checks():
    p = screwed_box(width=18, depth=18, corner_radius=0)       # 14 mm inside, columns need 16
    assert any("too small for the lid's screw columns" in i.message for i in validation.check(p))
    p = screwed_box(height=7)                                  # 4 mm for the screws to bite into
    assert any("only have" in i.message for i in validation.check(p))
    p = screwed_box()
    info = next(i for i in validation.check(p) if "screws, up to" in i.message)
    assert "4 M3 screws, up to 17.5 mm" in info.message


def test_wall_hole_near_a_screw_column():
    p = screwed_box(corner_radius=0)
    hole = Hole(FRONT, 6, 33, 0)                  # column covers 31 .. 38 along the front wall
    p.holes = [hole]
    issue = next(i for i in validation.check(p) if i.hole_id)
    assert issue.level == "error" and "screw column" in issue.message
    hole.u, hole.v = issue.fix
    assert not validation.has_errors(validation.check(p))
    hole.v = 14                     # high up is fine: a screwed lid has no lip
    assert not validation.has_errors(validation.check(p))
    hole.v = 18                     # off the top edge: not blamed on the column
    issue = next(i for i in validation.check(p) if i.hole_id)
    assert "runs off the edge" in issue.message


def test_round_wall_hole_between_columns():
    p = default_project(CYLINDER)
    p.lid.enabled, p.lid.style = True, SCREWED
    p.holes = [Hole(SIDE, 6, 45, 0)]
    assert any("screw columns" in i.message for i in validation.check(p))
    p.holes = [Hole(SIDE, 6, 0, 0)]               # columns are at 45°, 135° ...
    assert not validation.has_errors(validation.check(p))


def test_floor_and_lid_holes_near_columns():
    p = screwed_box(corner_radius=0)
    p.holes = [Hole(BOTTOM, 4, 34, 24), Hole(LID, 4, 32, 22)]
    msgs = messages(validation.check(p))
    assert "under one of the lid's screw columns" in msgs and "too close to a screw hole" in msgs


def test_board_hitting_a_screw_column_gets_a_fix():
    p = screwed_box(width=100, depth=74, height=40, corner_radius=0)
    m = mounts.new_mount(p, "rpi-ab")
    p.mounts = [m]
    assert not validation.has_errors(validation.check(p))   # placed clear of the columns
    m.u, m.v = 4, 4                 # still clear of the walls, but a corner hits a column
    issues = [i for i in validation.check(p) if i.mount_id]
    assert issues and "screw columns" in issues[0].message
    m.u, m.v = issues[0].fix
    assert not validation.has_errors(validation.check(p))


def test_screwed_lid_round_trip(tmp_path):
    p = screwed_box()
    p.lid.screw = "M2.5"
    path = tmp_path / "screwed.3dn00b"
    project_io.save_project(p, path)
    assert project_io.load_project(path) == p
    data = project_io.to_dict(p)
    data["project"]["lid"]["style"] = "magnetic"
    with pytest.raises(project_io.ProjectFileError):
        project_io.from_dict(data)
    del data["project"]["lid"]["style"]           # older files: push-on lid
    assert project_io.from_dict(data).lid.style == "push"


# ---- snap-on and sliding lids ----------------------------------------------------

from threedn00b.model import SLIDING, SNAP, slide_groove  # noqa: E402


def lid_box(style, **kw):
    p = box_with_lid(**kw)
    p.lid.style = style
    return p


@pytest.mark.parametrize("fit", ["tight", "normal", "loose"])
@pytest.mark.parametrize("shape,corner", [(BOX, 0.0), (BOX, 4.0), (BOX, 20.0), (CYLINDER, 0.0)])
def test_snap_lid_fits_without_collision(fit, shape, corner):
    p = default_project(shape)
    p.corner_radius = corner
    p.lid.enabled, p.lid.style, p.lid.fit = True, SNAP, fit
    parts = geometry.build_parts(p)
    for solid in (parts.body, parts.lid):
        assert geometry.piece_count(solid) == 1 and _edges_shared_twice(solid)
    assert geometry.overlap_volume(parts.body, parts.lid) < 1e-6
    assert not validation.has_errors(validation.check(p, parts))


def test_snap_ridges_sit_in_the_middle_of_each_side():
    p = lid_box(SNAP, corner_radius=0)          # lip outside face at y = -(30 - 2 - 0.25)
    lid, body = geometry.build_lid(p), geometry.build_body(p)
    z = p.outer_height - p.lid.lip_height + 1.6  # middle of the ridge
    lip_face = -(p.inner_depth / 2 - p.lid.gap)

    def lid_front(x):
        return lid.ray_cast([x, -100, z], [x, 0, z])[0].position[1]
    assert lid_front(0) == pytest.approx(lip_face - (0.5 - 0.0), abs=1e-6)   # ridge in the middle
    assert lid_front(30) == pytest.approx(lip_face, abs=1e-6)                # no ridge near corners
    # The matching groove is cut into the inside of the wall.
    inside = body.ray_cast([0, 0, z], [0, -100, z])[0].position[1]
    assert inside < -p.inner_depth / 2 - 0.2
    plain = body.ray_cast([30, 0, z], [30, -100, z])[0].position[1]
    assert plain == pytest.approx(-p.inner_depth / 2)


def test_snap_lid_checks():
    p = lid_box(SNAP)
    p.lid.lip_height = 2.5
    assert any("too short for the snap" in i.message for i in validation.check(p))
    p = lid_box(SNAP, wall=1.2)
    assert any("too thin for the snap" in i.message for i in validation.check(p))


@pytest.mark.parametrize("corner", [0.0, 4.0, 12.0])
def test_sliding_lid_slides_all_the_way_out(corner):
    p = lid_box(SLIDING, corner_radius=corner)
    parts = geometry.build_parts(p)
    assert geometry.piece_count(parts.body) == 1 and _edges_shared_twice(parts.body)
    assert p.closed_height == p.outer_height             # the lid sits inside the walls
    for dy in range(0, -int(p.outer_depth) - 2, -4):     # pull it out step by step
        assert geometry.overlap_volume(parts.body, parts.lid.translate([0, dy, 0])) < 1e-6
    # It can't come out upwards or sideways: the walls hold it.
    assert geometry.overlap_volume(parts.body, parts.lid.translate([0, 0, 1.0])) > 1
    assert geometry.overlap_volume(parts.body, parts.lid.translate([1.0, 0, 0])) > 1
    assert not validation.has_errors(validation.check(p, parts))


def test_sliding_lid_checks_and_limits():
    p = default_project(CYLINDER)
    p.lid.enabled, p.lid.style = True, SLIDING
    assert any("only work on boxes" in i.message for i in validation.check(p))
    p = lid_box(SLIDING, wall=1.2)
    assert any("too thin to hold a sliding lid" in i.message for i in validation.check(p))
    p = lid_box(SLIDING, height=8)
    assert any("too low for a sliding lid" in i.message for i in validation.check(p))
    p = lid_box(SLIDING)
    g0, _ = slide_groove(p)
    hole = Hole(FRONT, 6, 0, g0 - p.outer_height / 2)    # reaching into the groove
    p.holes = [hole]
    issue = next(i for i in validation.check(p) if i.hole_id)
    assert "sliding lid's groove" in issue.message
    hole.u, hole.v = issue.fix
    assert not validation.has_errors(validation.check(p))


def test_sliding_lid_keeps_dividers_and_boards_below_it():
    p = lid_box(SLIDING, width=110, depth=80, dividers=Dividers(across=2))
    g0, _ = slide_groove(p)
    assert divider_top(p) < g0
    parts = geometry.build_parts(p)
    assert geometry.overlap_volume(parts.body, parts.lid) < 1e-6
    m = mounts.new_mount(p, "rpi-zero")
    m.u = 25
    m.length = g0 - p.bottom - 1.0
    p.mounts = [m]
    p.dividers = Dividers()
    assert any("stick out" in i.message for i in validation.check(p))


def test_new_lid_types_round_trip(tmp_path):
    for style in (SNAP, SLIDING):
        p = lid_box(style)
        path = tmp_path / f"{style}.3dn00b"
        project_io.save_project(p, path)
        assert project_io.load_project(path) == p


# ---- threaded lid ------------------------------------------------------------

from threedn00b.model import THREAD_DEPTH, THREAD_PITCH, THREADED, thread_sizes  # noqa: E402


def jar(diameter=60.0, height=80.0, fit="normal"):
    p = default_project(CYLINDER)
    p.diameter, p.height = diameter, height
    p.lid.enabled, p.lid.style, p.lid.fit = True, THREADED, fit
    return p


def test_thread_flanks_print_without_support():
    # The steepest part of the rounded thread rises pi * depth / pitch mm per mm.
    assert math.pi * THREAD_DEPTH / THREAD_PITCH <= 1.0


@pytest.mark.parametrize("fit", ["tight", "normal", "loose"])
@pytest.mark.parametrize("diameter", [40.0, 60.0, 100.0])
def test_threaded_lid_unscrews_without_collision(fit, diameter):
    p = jar(diameter, fit=fit)
    parts = geometry.build_parts(p)
    body, lid = parts.body, parts.lid
    for solid in (body, lid):
        assert geometry.is_valid_solid(solid) and geometry.piece_count(solid) == 1
    for deg in range(0, 721, 30):                       # two full turns, turning and lifting
        moved = lid.rotate([0, 0, deg]).translate([0, 0, THREAD_PITCH * deg / 360])
        assert geometry.overlap_volume(body, moved) < 0.05, deg
    # The thread holds: pulling straight up, or turning the wrong way, is blocked.
    assert geometry.overlap_volume(body, lid.translate([0, 0, 2])) > 10
    assert geometry.overlap_volume(body, lid.rotate([0, 0, -90]).translate([0, 0, 1])) > 10
    assert not validation.has_errors(validation.check(p, parts))


def test_threaded_lid_is_flush_and_prints_flat():
    p = jar()
    parts = geometry.build_parts(p)
    lo, hi = parts.lid.bounding_box()[:3], parts.lid.bounding_box()[3:]
    assert hi[0] - lo[0] == pytest.approx(p.outer_diameter, abs=0.01)   # same width as the jar
    assert parts.body.bounding_box()[3] == pytest.approx(p.outer_diameter / 2, abs=0.01)
    assert p.closed_height == pytest.approx(hi[2], abs=1e-6)
    lid_print = parts.printable()["lid"]
    assert lid_print.bounding_box()[2] == pytest.approx(0)
    t = thread_sizes(p)
    # Inside: full width low down, narrowing at 45 degrees to the neck's opening.
    body = parts.body
    assert body.ray_cast([0, 0, 10], [40, 0, 10])[0].position[0] == pytest.approx(30 - p.wall, abs=0.05)
    assert body.ray_cast([0, 0, p.outer_height - 1], [40, 0, p.outer_height - 1])[0].position[0] == \
        pytest.approx(t.opening, abs=0.05)


def test_threaded_lid_checks():
    p = jar()
    p.shape = BOX
    assert any("only work on round containers" in i.message for i in validation.check(p))
    assert geometry.build_lid(p) is None
    assert any("too narrow" in i.message for i in validation.check(jar(diameter=22)))
    assert any("too short" in i.message for i in validation.check(jar(height=15)))
    p = jar()
    hole = Hole(SIDE, 6, 0, 30)                         # up on the neck
    p.holes = [hole]
    issue = next(i for i in validation.check(p) if i.hole_id)
    assert "on the neck" in issue.message
    hole.u, hole.v = issue.fix
    assert not validation.has_errors(validation.check(p))


def test_holes_in_threaded_lid():
    p = jar()
    p.holes = [Hole(LID, 8, 0, 0)]
    parts = geometry.build_parts(p)
    assert not parts.lid.ray_cast([0, 0, 200], [0, 0, p.outer_height])
    assert not validation.has_errors(validation.check(p, parts))
    p.holes = [Hole(LID, 8, 26, 0)]                     # outside the opening
    assert validation.has_errors(validation.check(p))


def test_threaded_lid_round_trip(tmp_path):
    p = jar()
    path = tmp_path / "jar.3dn00b"
    project_io.save_project(p, path)
    assert project_io.load_project(path) == p


# ---- 3MF export --------------------------------------------------------------

def test_3mf_holds_every_part_exactly(tmp_path):
    p = box_with_lid(name="Tool box")
    p.holes = [Hole(FRONT, 8, 0, 0)]
    path = project_io.export_3mf_file(p, tmp_path)
    assert path.name == "tool-box.3mf"
    printable = geometry.build_parts(p).printable()
    parts = project_io.read_3mf(path)
    assert [q["name"] for q in parts] == ["Tool box body", "Tool box lid"]
    for q, solid in zip(parts, printable.values()):
        verts, tris = geometry.mesh_arrays(solid)
        assert q["unit"] == "millimeter"
        assert len(q["triangles"]) == len(tris)
        assert q["vertices"] == pytest.approx(verts, abs=1e-4)
        assert (q["triangles"] == tris).all()
        edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
        edges.sort(axis=1)
        assert (np.unique(edges, axis=0, return_counts=True)[1] == 2).all()   # watertight


def test_3mf_lays_parts_side_by_side(tmp_path):
    p = jar()
    parts = project_io.read_3mf(project_io.export_3mf_file(p, tmp_path))
    spans = []
    for q in parts:
        xs = q["vertices"][:, 0] + q["offset"][0]
        spans.append((xs.min(), xs.max()))
        assert q["vertices"][:, 2].min() == pytest.approx(0, abs=1e-4)         # on the plate
    (a0, a1), (b0, b1) = spans
    assert b0 - a1 == pytest.approx(project_io.PART_SPACING, abs=1e-3)     # 10 mm apart
    assert (a0 + b1) / 2 == pytest.approx(0, abs=1e-3)                      # centred


def test_3mf_with_one_part_and_awkward_names(tmp_path):
    import zipfile
    p = default_project(BOX)
    p.name = 'Tom & Jerry\'s "box" <1>'
    path = project_io.export_3mf_file(p, tmp_path)
    parts = project_io.read_3mf(path)
    assert [q["name"] for q in parts] == ['Tom & Jerry\'s "box" <1> body']
    assert parts[0]["offset"][0] == pytest.approx(0)
    with zipfile.ZipFile(path) as zf:
        assert {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"} <= set(zf.namelist())


# ---- custom boards with 1 or 2 holes -------------------------------------------

def test_two_hole_board_in_a_line_or_diagonal():
    p = Project(width=100, depth=70, height=35)
    m = mounts.new_mount(p, "custom2")
    assert (m.board_width, m.board_depth, m.spacing_x, m.spacing_y) == (30, 20, 24, 0)
    assert sorted(mounts.post_positions(m)) == [(-12.0, 0.0), (12.0, 0.0)]
    m.spacing_y = 10                                      # diagonal holes
    assert sorted(mounts.post_positions(m)) == [(-12.0, -5.0), (12.0, 5.0)]
    m.spacing_y = -10                                     # the other diagonal
    assert sorted(mounts.post_positions(m)) == [(-12.0, 5.0), (12.0, -5.0)]
    p.mounts = [m]
    body = geometry.build_body(p)
    assert geometry.piece_count(body) == 1
    for x, y in mounts.post_positions(m):                # a post with a pilot hole at each
        assert body.ray_cast([x, y, 100], [x, y, -5])[0].position[2] == pytest.approx(p.bottom)
    assert not validation.has_errors(validation.check(p))


def test_one_hole_board():
    p = Project(width=100, depth=70, height=35)
    m = mounts.new_mount(p, "custom1")
    assert mounts.post_positions(m) == [(0.0, 0.0)]
    m.spacing_x, m.spacing_y = 6, -4                      # hole off-centre on the board
    m.u, m.v = 10, 5
    assert mounts.post_positions(m) == [(16.0, 1.0)]
    m.rotation = 90
    assert mounts.post_positions(m)[0] == pytest.approx((14.0, 11.0))
    p.mounts = [m]
    assert not validation.has_errors(validation.check(p))
    assert mounts.board_corners(m)                        # the outline is still checked


def test_custom_board_hole_checks():
    p = Project(width=100, depth=70, height=35)
    two = mounts.new_mount(p, "custom2")
    two.spacing_x = 40                                    # wider than the 30 mm board
    p.mounts = [two]
    assert any("don't fit on the board" in i.message for i in validation.check(p))
    two.spacing_x = two.spacing_y = 0
    assert any("same place" in i.message for i in validation.check(p))
    one = mounts.new_mount(p, "custom1")
    one.spacing_y = 12                                    # beyond the 20 mm board's edge
    p.mounts = [one]
    assert any("hole is outside the board" in i.message for i in validation.check(p))


def test_custom_boards_round_trip(tmp_path):
    p = Project(width=100, depth=70, height=35)
    a, b = mounts.new_mount(p, "custom2"), mounts.new_mount(p, "custom1")
    a.spacing_y, b.spacing_x, a.u, b.u = -6, 3, -25, 25
    p.mounts = [a, b]
    path = tmp_path / "boards.3dn00b"
    project_io.save_project(p, path)
    assert project_io.load_project(path) == p


# ---- rounded / angled inside corners ---------------------------------------------

from threedn00b.model import inside_fillet  # noqa: E402


def corner_box(style, size, shape=BOX, **kw):
    p = default_project(shape)
    p.corner_radius = 0
    p.inside_corners, p.inside_corner_size = style, size
    for k, v in kw.items():
        setattr(p, k, v)
    return p


@pytest.mark.parametrize("shape", [BOX, CYLINDER])
def test_inside_corner_profiles(shape):
    for style, at_half, at_two in (("angled", 3.5, 2.0), ("rounded", 4 - math.sqrt(16 - 3.5 ** 2),
                                                          4 - math.sqrt(12))):
        p = corner_box(style, 4.0, shape)
        body = geometry.build_body(p)
        wall = p.inner_width / 2

        def inside_at(z):
            return body.ray_cast([0, 0, z], [100, 0, z])[0].position[0]
        # The curve is made of short straight steps: within 0.05 mm of a true circle.
        assert inside_at(p.bottom + 0.5) == pytest.approx(wall - at_half, abs=0.05)
        assert inside_at(p.bottom + 2) == pytest.approx(wall - at_two, abs=0.05)
        assert inside_at(p.bottom + 6) == pytest.approx(wall, abs=1e-6)       # normal wall above
        assert geometry.piece_count(body) == 1 and _edges_shared_twice(body)


def test_inside_corners_add_material_where_expected():
    sharp = geometry.build_body(corner_box("sharp", 3.0)).volume()
    angled = geometry.build_body(corner_box("angled", 3.0)).volume()
    rounded = geometry.build_body(corner_box("rounded", 3.0)).volume()
    p = corner_box("angled", 3.0)
    perimeter = 2 * (p.inner_width + p.inner_depth)
    # Roughly a 3 mm triangle (angled) or the area outside a quarter circle (rounded)
    # all along the floor edge, plus the rounded vertical corners.
    vertical = 4 * 9 * (1 - math.pi / 4) * (p.inner_height - 3)
    assert angled - sharp == pytest.approx(perimeter * 4.5 + vertical, rel=0.1)
    assert rounded - sharp == pytest.approx(perimeter * 9 * (1 - math.pi / 4) + vertical, rel=0.1)


def test_vertical_inside_corners_are_rounded_too():
    p = corner_box("rounded", 5.0)                     # outside corners sharp, inside 5 mm
    assert p.inner_corner_radius == 5.0
    body = geometry.build_body(p)
    z, d = 20.0, 100.0
    hit = body.ray_cast([0, 0, z], [d, d * p.inner_depth / p.inner_width, z])[0].position
    sharp_corner = math.hypot(p.inner_width / 2, p.inner_depth / 2)
    assert math.hypot(hit[0], hit[1]) < sharp_corner - 1.5        # the corner is filled in


def test_things_keep_clear_of_the_inside_corners():
    p = corner_box("rounded", 5.0)
    lim = wall_limits(p, FRONT, 6)
    assert lim[2] == pytest.approx(p.bottom + 5 + 3 + 0.4 - p.outer_height / 2)   # above the curve
    hole = Hole(BOTTOM, 6, 34, 0)                      # floor hole in the curved part
    p.holes = [hole]
    issue = next(i for i in validation.check(p) if i.hole_id)
    assert issue.level == "error"
    hole.u, hole.v = issue.fix
    assert not validation.has_errors(validation.check(p))
    p.holes = []
    m = mounts.new_mount(p, "single")
    m.u = 35
    p.mounts = [m]
    assert validation.has_errors(validation.check(p))  # the post would stand on the slope


@pytest.mark.parametrize("lid", ["push", "snap", "sliding", "screwed"])
def test_inside_corners_work_with_every_box_lid(lid):
    p = corner_box("rounded", 4.0, corner_radius=2.0, dividers=Dividers(across=2))
    p.lid.enabled, p.lid.style = True, lid
    parts = geometry.build_parts(p)
    assert geometry.overlap_volume(parts.body, parts.lid) < 1e-6
    assert not validation.has_errors(validation.check(p, parts))


def test_inside_corners_with_threaded_lid_still_unscrew():
    p = corner_box("rounded", 3.0, CYLINDER)
    p.lid.enabled, p.lid.style = True, "threaded"
    parts = geometry.build_parts(p)
    for deg in range(0, 721, 60):
        moved = parts.lid.rotate([0, 0, deg]).translate([0, 0, THREAD_PITCH * deg / 360])
        assert geometry.overlap_volume(parts.body, moved) < 0.05
    assert not validation.has_errors(validation.check(p, parts))


def test_inside_corner_size_checks_and_saving(tmp_path):
    assert validation.has_errors(validation.check(corner_box("angled", 30.0)))   # 56 mm deep inside
    assert not validation.has_errors(validation.check(corner_box("angled", 20.0)))
    p = corner_box("angled", 2.5)
    assert inside_fillet(p) == 2.5 and inside_fillet(corner_box("sharp", 2.5)) == 0
    path = tmp_path / "corners.3dn00b"
    project_io.save_project(p, path)
    assert project_io.load_project(path) == p
    data = project_io.to_dict(p)
    data["project"]["inside_corners"] = "wavy"
    with pytest.raises(project_io.ProjectFileError):
        project_io.from_dict(data)
    del data["project"]["inside_corners"]           # older files: sharp corners
    assert project_io.from_dict(data).inside_corners == "sharp"


# ---- rounded divider joints ------------------------------------------------------

from threedn00b.model import divider_fillet  # noqa: E402


def divider_box(style, size, **kw):
    p = corner_box(style, size, dividers=Dividers(across=2, deep=2), **kw)
    p.lid.enabled = False
    return p


@pytest.mark.parametrize("style", ["angled", "rounded"])
def test_divider_joints_follow_the_inside_corners(style):
    p = divider_box(style, 3.0)
    assert divider_fillet(p) == 3.0
    body = geometry.build_body(p)
    face = p.dividers.thickness / 2                  # the dividers are on the centre lines
    y = p.inner_depth / 4                            # in the middle of a compartment

    def reach(h):
        """How far the joint at the floor reaches out from the divider, h mm up."""
        z = p.bottom + h
        return body.ray_cast([20, y, z], [-20, y, z])[0].position[0] - face
    for h in (1.0, 2.0):
        expected = 3 - h if style == "angled" else 3 - math.sqrt(9 - (3 - h) ** 2)
        assert reach(h) == pytest.approx(expected, abs=0.05)
    assert reach(5.0) == pytest.approx(0, abs=1e-6)
    # Where a divider meets a wall, the joint is rounded too: a ray from inside a
    # compartment straight at that corner stops short of it.
    z = p.bottom + 10
    corner = np.array([face, -p.inner_depth / 2, z])
    start = corner + [8, 8, 0]
    pos = np.array(body.ray_cast(start.tolist(), corner.tolist())[0].position)
    assert np.linalg.norm(pos - corner) == pytest.approx(3 * (math.sqrt(2) - 1), abs=0.05)
    assert geometry.piece_count(body) == 1 and _edges_shared_twice(body)


def test_rounded_divider_joints_add_material():
    sharp = geometry.build_body(divider_box("sharp", 3.0)).volume()
    rounded = geometry.build_body(divider_box("rounded", 3.0)).volume()
    plain = geometry.build_body(corner_box("rounded", 3.0)).volume() - \
        geometry.build_body(corner_box("sharp", 3.0)).volume()
    p = divider_box("rounded", 3.0)
    # Both sides of both dividers along the floor, and 12 upright joints:
    # 8 where the dividers meet the walls and 4 where they cross.
    floor_joints = 2 * (p.inner_width + p.inner_depth) * 9 * (1 - math.pi / 4)
    upright = 12 * 9 * (1 - math.pi / 4) * (p.inner_height - 3)
    assert rounded - sharp == pytest.approx(plain + floor_joints + upright, rel=0.1)


@pytest.mark.parametrize("lid", ["push", "snap", "sliding", "screwed"])
def test_rounded_divider_joints_leave_room_for_every_lid(lid):
    p = divider_box("rounded", 4.0, corner_radius=3.0)
    p.lid.enabled, p.lid.style = True, lid
    parts = geometry.build_parts(p)
    assert geometry.overlap_volume(parts.body, parts.lid) < 1e-6
    assert geometry.is_valid_solid(parts.body) and geometry.piece_count(parts.body) == 1
    assert not validation.has_errors(validation.check(p, parts))


@pytest.mark.parametrize("style", ["angled", "rounded"])
@pytest.mark.parametrize("lid", [False, True])
def test_rounded_dividers_make_a_clean_mesh(style, lid):
    """No zero-area triangles: some slicers report those as errors to repair."""
    p = default_project(TRAY_TEMPLATE)
    p.inside_corners, p.inside_corner_size, p.lid.enabled = style, 3.0, lid
    p.holes = [Hole(FRONT, kind=RECT, width=12, height=6, rounding=1, strengthen=True, u=30)]
    verts, tris = geometry.mesh_arrays(geometry.build_body(p))
    a, b, c = (verts[tris[:, i]] for i in range(3))
    assert np.linalg.norm(np.cross(b - a, c - a), axis=1).min() > 2e-6


def test_divider_joint_checks():
    p = divider_box("rounded", 3.0, height=60)
    p.dividers.height = 3.0                          # lower than the corners: stays sharp
    assert divider_fillet(p) == 0
    assert any("stays sharp" in i.message for i in validation.check(p))
    p.dividers.height = 0
    p.dividers.across = 6                            # narrow compartments: corners too big
    p.inside_corner_size = 8
    assert validation.has_errors(validation.check_size(p))
    p.dividers.across, p.inside_corner_size = 2, 3.0
    # A wall hole next to a divider is flagged when it reaches the rounded joint.
    face = p.dividers.thickness / 2
    p.holes = [Hole(FRONT, 4, face + 2 + 1.5, 0)]
    assert any("divider" in i.message for i in validation.check(p) if i.hole_id)
    p.holes[0].u = face + 3 + 2.5
    assert not any("divider" in i.message for i in validation.check(p) if i.hole_id)


# ---- rounded hole corners and strengthened hole edges -----------------------------

import copy  # noqa: E402

from threedn00b.model import FRAME_RIM, corner_rounding, frame_thickness, vent_openings  # noqa: E402


def test_rounded_rectangle_hole_corners():
    p = default_project(BOX)
    hole = Hole(FRONT, kind=RECT, width=12, height=6, rounding=2.0)
    cut = geometry._hole_cutter(p, hole)
    length = cut.bounding_box()[4] - cut.bounding_box()[1]
    assert cut.volume() / length == pytest.approx(72 - (4 - math.pi) * 4, rel=0.01)
    hole.rounding = 50                               # capped: a slot with round ends
    assert corner_rounding(hole) == 3.0
    assert geometry._hole_cutter(p, hole).volume() / length == pytest.approx(
        36 + math.pi * 9, rel=0.01)
    assert corner_rounding(Hole(FRONT, 8, rounding=2)) == 0          # round holes: no corners
    vent = Hole(FRONT, kind=VENT, width=20, height=10, slot=2, gap=2, rounding=1)
    p.holes = [vent]
    assert all(s.rounding == 1 for s in vent_openings(p, vent))
    assert not validation.has_errors(validation.check(p))


@pytest.mark.parametrize("shape,surfaces", [(BOX, [FRONT, BACK, LEFT, RIGHT]), (CYLINDER, [SIDE])])
def test_strengthening_frames(shape, surfaces):
    p = default_project(shape)
    p.lid.enabled = False
    p.holes = [Hole(s, kind=RECT, width=12, height=6, rounding=1, strengthen=True,
                    u=0 if shape == BOX else 90 * i, v=-5)
               for i, s in enumerate(surfaces)]
    body = geometry.build_body(p)
    plain = copy.deepcopy(p)
    for h in plain.holes:
        h.strengthen = False
    assert body.volume() > geometry.build_body(plain).volume() + 50 * len(surfaces)
    assert geometry.piece_count(body) == 1 and _edges_shared_twice(body)
    t = frame_thickness(p)
    z = p.outer_height / 2 - 5
    if shape == BOX:
        y_in = -p.inner_depth / 2
        # Straight through the openings and their frames (front and back): nothing in the way.
        assert not body.ray_cast([0, -60, z], [0, 60, z])
        # Next to the opening the frame stands out by its full thickness...
        beside = body.ray_cast([6 + FRAME_RIM / 2, 0, z], [6 + FRAME_RIM / 2, -60, z])[0]
        assert beside.position[1] == pytest.approx(y_in + t, abs=0.02)
        # ...then slopes back to the wall at 45°.
        slope = body.ray_cast([6 + FRAME_RIM + t / 2, 0, z], [6 + FRAME_RIM + t / 2, -60, z])[0]
        assert slope.position[1] == pytest.approx(y_in + t / 2, abs=0.05)
        far = body.ray_cast([6 + FRAME_RIM + t + 1, 0, z], [6 + FRAME_RIM + t + 1, -60, z])[0]
        assert far.position[1] == pytest.approx(y_in, abs=1e-6)
    else:
        d = np.array([0.0, -100.0, 0.0])
        assert not body.ray_cast([0, 0, z], (d + [0, 0, z]).tolist())    # the opening is clear
        assert body.ray_cast([7, 0, z], (d + [7, 0, z]).tolist())[0].position[1] == \
            pytest.approx(-(p.outer_diameter / 2 - p.wall) + t, abs=0.05)  # beside: the frame


def test_frames_keep_out_of_the_lids_way():
    for style in ("push", "snap", "sliding", "screwed"):
        p = default_project(BOX)
        p.lid.enabled, p.lid.style = True, style
        hole = Hole(FRONT, kind=RECT, width=12, height=6, strengthen=True)
        p.holes = [hole]
        hole.u, hole.v = clamp_hole(p, Hole(FRONT, kind=RECT, width=12, height=6, v=100))
        parts = geometry.build_parts(p)
        assert geometry.overlap_volume(parts.body, parts.lid) < 1e-6, style
        assert not validation.has_errors(validation.check(p, parts)), style
    p = default_project(CYLINDER)
    p.lid.enabled, p.lid.style = True, "threaded"
    hole = Hole(SIDE, kind=RECT, width=10, height=6, strengthen=True)
    hole.u, hole.v = clamp_hole(p, Hole(SIDE, kind=RECT, width=10, height=6, v=100))
    p.holes = [hole]
    parts = geometry.build_parts(p)
    for deg in range(0, 721, 90):
        moved = parts.lid.rotate([0, 0, deg]).translate([0, 0, THREAD_PITCH * deg / 360])
        assert geometry.overlap_volume(parts.body, moved) < 0.05


def test_frames_only_on_walls_and_boards_keep_clear():
    p = default_project(BOX)
    p.holes = [Hole(BOTTOM, 8, strengthen=True)]
    plain = default_project(BOX)
    plain.holes = [Hole(BOTTOM, 8)]
    assert geometry.build_body(p).volume() == pytest.approx(geometry.build_body(plain).volume())
    hole = Hole(FRONT, kind=RECT, width=12, height=6, strengthen=True,
                v=-p.outer_height / 2 + p.bottom + 8)
    m = mounts.new_mount(p, "rpi-zero")
    m.length = 5
    p.holes, p.mounts = [hole], [m]
    assert not any("frame" in i.message for i in validation.check(p))
    m.v = -p.inner_depth / 2 + 1 + 15                # 1 mm from the wall: fine without a frame
    assert mounts.clearance(p, m) >= 1 - 1e-6
    issues = validation.check(p)
    assert any("frame" in i.message and i.level == "error" for i in issues)
    hole.strengthen = False
    assert not any("frame" in i.message for i in validation.check(p))


def test_hole_options_are_saved(tmp_path):
    p = default_project(BOX)
    p.holes = [Hole(FRONT, kind=RECT, rounding=1.5, strengthen=True)]
    path = tmp_path / "holes.3dn00b"
    project_io.save_project(p, path)
    assert project_io.load_project(path) == p
    data = project_io.to_dict(p)
    for key in ("rounding", "strengthen"):            # older files: sharp, no frame
        del data["project"]["holes"][0][key]
    old = project_io.from_dict(data).holes[0]
    assert old.rounding == 0 and old.strengthen is False


# ---- compartments of different sizes ----------------------------------------------

from threedn00b.model import compartment_depths, compartment_widths, resized_sizes  # noqa: E402


def test_compartments_of_set_sizes():
    p = Project(width=100, depth=60, height=30, wall=2, bottom=2, corner_radius=0,
                dividers=Dividers(across=3, deep=2, thickness=2, widths=[20, 30], depths=[15]))
    assert compartment_widths(p) == pytest.approx([20, 30, 42])      # the last gets the rest
    assert compartment_depths(p) == pytest.approx([15, 39])
    assert compartment_size(p) == pytest.approx((20, 15))
    xs, ys = divider_positions(p)
    assert xs == pytest.approx([-27, 5]) and ys == pytest.approx([-12])
    body = geometry.build_body(p)
    # Walk along the floor from the left: walls of the compartments where expected.
    z = p.bottom + 5
    hit = body.ray_cast([-47, -20, z], [47, -20, z])[0].position
    assert hit[0] == pytest.approx(-28)
    assert body.ray_cast([0, 0, z], [0, -40, z])[0].position[1] == pytest.approx(-11)
    assert not validation.has_errors(validation.check(p))


def test_set_sizes_that_dont_fit():
    p = default_project(BOX)
    p.dividers = Dividers(across=3, widths=[40, 40])           # 76 mm inside: nothing left
    issues = validation.check_size(p)
    assert validation.has_errors(issues)
    assert "add up to more than fits" in issues[0].message
    p.dividers.widths = [2, 30]
    assert "too narrow to print" in validation.check_size(p)[0].message
    p.dividers.widths = [20, 30]
    assert not validation.has_errors(validation.check(p))
    p.dividers.across = 4                                         # sizes no longer match: equal
    assert compartment_widths(p) == pytest.approx([(p.inner_width - 3 * 1.6) / 4] * 4)


def test_changing_the_number_keeps_set_sizes():
    assert resized_sizes(96, 5, 2, [20, 30]) == pytest.approx([20, 30, 12.7, 12.7])
    assert resized_sizes(96, 2, 2, [20, 30]) == [20]
    assert resized_sizes(96, 1, 2, [20, 30]) == []
    assert resized_sizes(96, 3, 2, []) == pytest.approx([30.7, 30.7])


@pytest.mark.parametrize("lid", ["push", "snap", "sliding", "screwed"])
@pytest.mark.parametrize("style", ["sharp", "rounded"])
def test_set_sizes_with_every_lid(lid, style):
    p = default_project(TRAY_TEMPLATE)
    p.dividers.widths, p.dividers.depths = [20.0, 70.0], [30.0]
    p.inside_corners, p.inside_corner_size = style, 3.0
    p.wall = 2.4                                      # thick enough for a sliding lid
    p.lid.enabled, p.lid.style = True, lid
    parts = geometry.build_parts(p)
    assert geometry.overlap_volume(parts.body, parts.lid) < 1e-6
    assert geometry.piece_count(parts.body) == 1 and _edges_shared_twice(parts.body)
    assert not validation.has_errors(validation.check(p, parts))


def test_set_sizes_are_saved(tmp_path):
    p = default_project(TRAY_TEMPLATE)
    p.dividers.widths = [20.0, 70.0]
    path = tmp_path / "sizes.3dn00b"
    project_io.save_project(p, path)
    assert project_io.load_project(path) == p
    data = project_io.to_dict(p)
    data["project"]["dividers"]["widths"] = ["wide"]
    with pytest.raises(project_io.ProjectFileError):
        project_io.from_dict(data)
    del data["project"]["dividers"]["widths"]             # older files: all the same size
    assert project_io.from_dict(data).dividers.widths == []


# ---- easy-opening tab and finger notch ----------------------------------------------

from threedn00b.model import TAB_REACH, notch_size  # noqa: E402


@pytest.mark.parametrize("shape", [BOX, CYLINDER])
@pytest.mark.parametrize("style", ["push", "snap"])
def test_lid_tab_and_finger_notch(shape, style):
    p = default_project(shape)
    p.lid.enabled, p.lid.style, p.lid.opening = True, style, "both"
    plain = copy.deepcopy(p)
    plain.lid.opening = "none"
    parts, before = geometry.build_parts(p), geometry.build_parts(plain)
    front = p.outer_depth / 2 if shape == BOX else p.outer_diameter / 2
    # The tab sticks out at the front, flush with the top of the lid.
    lo, hi = geometry._bounds(parts.lid)
    assert lo[1] == pytest.approx(-front - TAB_REACH) and hi[1] == pytest.approx(front, abs=0.01)
    tab = parts.lid.volume() - before.lid.volume()
    assert tab == pytest.approx(20 * TAB_REACH * p.lid.thickness, rel=0.15)
    top = p.outer_height + p.lid.thickness
    assert parts.lid.ray_cast([0, -front - 3, top + 5], [0, -front - 3, 0])[0].position[2] == \
        pytest.approx(top)
    # The notch: the front wall stops lower in the middle.
    width, depth = notch_size(p)

    def wall_top(x):
        """Height of the front wall, x mm from the middle (measured mid-wall)."""
        y = -front + p.wall / 2 if shape == BOX else -math.sqrt((front - p.wall / 2) ** 2 - x * x)
        return parts.body.ray_cast([x, y, 100], [x, y, 0])[0].position[2]
    assert wall_top(0) == pytest.approx(p.outer_height - depth, abs=0.01)
    assert wall_top(width / 2 + 1) == pytest.approx(p.outer_height)
    assert geometry.overlap_volume(parts.body, parts.lid) < 1e-6
    assert geometry.piece_count(parts.body) == 1 and geometry.piece_count(parts.lid) == 1
    assert _edges_shared_twice(parts.body) and _edges_shared_twice(parts.lid)
    assert not validation.has_errors(validation.check(p, parts))
    # Printed upside down, the tab lies on the plate with the rest of the top.
    assert geometry._bounds(parts.printable()["lid"])[0][2] == pytest.approx(0)


def test_opening_only_for_lids_with_a_lip(tmp_path):
    for style in ("sliding", "screwed"):
        p = default_project(BOX)
        p.wall = 2.4
        p.lid.enabled, p.lid.style, p.lid.opening = True, style, "both"
        plain = copy.deepcopy(p)
        plain.lid.opening = "none"
        assert geometry.build_body(p).volume() == pytest.approx(geometry.build_body(plain).volume())
        assert geometry.build_lid(p).volume() == pytest.approx(geometry.build_lid(plain).volume())
    p = default_project(BOX)
    p.lid.enabled, p.lid.opening = True, "tab"
    path = tmp_path / "tab.3dn00b"
    project_io.save_project(p, path)
    assert project_io.load_project(path) == p
    data = project_io.to_dict(p)
    data["project"]["lid"]["opening"] = "lever"
    with pytest.raises(project_io.ProjectFileError):
        project_io.from_dict(data)
    del data["project"]["lid"]["opening"]                # older files: nothing extra
    assert project_io.from_dict(data).lid.opening == "none"


# ---- templates --------------------------------------------------------------------

from threedn00b import templates  # noqa: E402


@pytest.mark.parametrize("key", list(templates.TEMPLATES))
def test_templates_are_ready_to_print(key, tmp_path):
    p = templates.from_template(key)
    parts = geometry.build_parts(p)
    issues = validation.check(p, parts)
    assert [i.message for i in issues if i.level != "info"] == []
    assert geometry.piece_count(parts.body) == 1 and _edges_shared_twice(parts.body)
    if parts.lid is not None:
        assert geometry.overlap_volume(parts.body, parts.lid) < 1e-6
    path = tmp_path / "t.3dn00b"
    project_io.save_project(p, path)
    assert project_io.load_project(path) == p
    assert templates.from_template(key) is not p      # a fresh copy every time


@pytest.mark.parametrize("key", [k for k in templates.ELECTRONICS
                                 if templates.from_template(k).mounts])   # boards on posts
def test_board_openings_face_the_sockets(key):
    """Every wall opening is next to a board edge and at the height of its sockets."""
    p = templates.from_template(key)
    walls = [h for h in p.holes if h.surface in (FRONT, BACK, LEFT, RIGHT)]
    assert walls
    for hole in walls:
        half = hole.half_extents[1]
        z0, z1 = p.outer_height / 2 + hole.v - half, p.outer_height / 2 + hole.v + half
        near = []
        for m in p.mounts:
            low = mounts.board_bottom(p, m)
            top = low + mounts.BOARD_THICKNESS
            xs = [c[0] for c in mounts.board_corners(m)]
            ys = [c[1] for c in mounts.board_corners(m)]
            # How far the board's nearest edge is from this wall.
            gap = {FRONT: min(ys) + p.inner_depth / 2, BACK: p.inner_depth / 2 - max(ys),
                   LEFT: min(xs) + p.inner_width / 2, RIGHT: p.inner_width / 2 - max(xs)}
            if z0 < top + 3 and z1 > low - 4:
                near.append(gap[hole.surface])
        assert near and min(near) <= 20.5, hole


def test_stacked_template_is_approved():
    p = templates.from_template("pi-zero-stack")
    lower, upper = p.mounts
    assert upper.rotation == 90 and upper.length > lower.length
    assert not any(i.mount_id for i in validation.check(p) if i.level != "info")


def test_fan_fits_under_the_lid():
    from manifold3d import Manifold
    p = templates.from_template("pi5-fan")
    fan = next(h for h in p.holes if h.surface == LID and h.diameter == 26)
    body = geometry.build_body(p)
    h = p.outer_height
    box = Manifold.cube([30, 30, 10], True).translate([fan.u, fan.v, h - 5])
    assert geometry.overlap_volume(body, box) == 0             # clear of the walls and lip
    # ...and of the tall USB and network sockets (from 64 mm along the board).
    m = p.mounts[0]
    usb_x = m.u - 42.5 + 64
    top = mounts.board_bottom(p, m) + mounts.BOARD_THICKNESS
    assert fan.u + 15 < usb_x or h - 10 > top + 16
    screws = [x for x in p.holes if x.surface == LID and x.diameter == 3.4]
    assert sorted({round(abs(s.u - fan.u), 6) for s in screws}) == [12.0]


def test_template_groups_list_every_template_once():
    listed = [key for _, keys in templates.GROUPS for key in keys]
    assert sorted(listed) == sorted(templates.TEMPLATES) and len(set(listed)) == len(listed)


def test_mega_has_six_posts_inside_the_board():
    p = templates.from_template("mega")
    m = p.mounts[0]
    posts = mounts.post_positions(m)
    corners = mounts.board_corners(m)
    assert len(posts) == 6
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    assert all(min(xs) < x < max(xs) and min(ys) < y < max(ys) for x, y in posts)


# ---- which side a lid slides in from, and where the tab and notch are -------------

SIDE_DIRECTIONS = {"front": (0, -1), "back": (0, 1), "left": (-1, 0), "right": (1, 0)}


@pytest.mark.parametrize("side", list(SIDE_DIRECTIONS))
@pytest.mark.parametrize("corner", [0.0, 6.0])
def test_sliding_lid_from_any_side(side, corner):
    p = lid_box(SLIDING, corner_radius=corner)
    p.width, p.depth = 90.0, 60.0                       # not square, so the sides differ
    p.lid.slide_from = side
    parts = geometry.build_parts(p)
    assert geometry.piece_count(parts.body) == 1 and _edges_shared_twice(parts.body)
    dx, dy = SIDE_DIRECTIONS[side]
    for step in range(0, int(max(p.outer_width, p.outer_depth)) + 2, 4):   # out that way
        moved = parts.lid.translate([dx * step, dy * step, 0])
        assert geometry.overlap_volume(parts.body, moved) < 1e-6
    # Held in every other direction.
    assert geometry.overlap_volume(parts.body, parts.lid.translate([0, 0, 1.0])) > 1
    for ox, oy in SIDE_DIRECTIONS.values():
        if (ox, oy) != (dx, dy):
            assert geometry.overlap_volume(parts.body, parts.lid.translate([ox, oy, 0])) > 1
    issues = validation.check(p, parts)
    assert not validation.has_errors(issues)
    assert any(f"from the {side}" in i.message for i in issues)


@pytest.mark.parametrize("shape", [BOX, CYLINDER])
@pytest.mark.parametrize("side", list(SIDE_DIRECTIONS))
def test_tab_and_notch_on_any_side(shape, side):
    p = default_project(shape)
    p.width, p.depth = 90.0, 60.0
    p.lid.enabled, p.lid.opening, p.lid.opening_side = True, "both", side
    parts = geometry.build_parts(p)
    dx, dy = SIDE_DIRECTIONS[side]
    lo, hi = geometry._bounds(parts.lid)
    half_x, half_y = p.outer_width / 2, p.outer_depth / 2
    if shape == CYLINDER:
        half_x = half_y = p.outer_diameter / 2
    # The tab sticks out on that side only.
    out = {"front": -lo[1] - half_y, "back": hi[1] - half_y,
           "left": -lo[0] - half_x, "right": hi[0] - half_x}
    for s, amount in out.items():
        assert amount == pytest.approx(TAB_REACH if s == side else 0, abs=0.01)
    # The notch is in that wall, in the middle.
    _, depth = notch_size(p)
    x, y = dx * (half_x - p.wall / 2), dy * (half_y - p.wall / 2)     # in the middle of the wall
    top = parts.body.ray_cast([x, y, 200], [x, y, 0])[0].position[2]
    assert top == pytest.approx(p.outer_height - depth, abs=0.01)
    assert geometry.overlap_volume(parts.body, parts.lid) < 1e-6
    assert not validation.has_errors(validation.check(p, parts))


def test_lid_sides_are_saved(tmp_path):
    p = default_project(BOX)
    p.lid.enabled, p.lid.slide_from, p.lid.opening_side = True, "left", "back"
    path = tmp_path / "sides.3dn00b"
    project_io.save_project(p, path)
    assert project_io.load_project(path) == p
    data = project_io.to_dict(p)
    data["project"]["lid"]["slide_from"] = "top"
    with pytest.raises(project_io.ProjectFileError):
        project_io.from_dict(data)
    del data["project"]["lid"]["slide_from"], data["project"]["lid"]["opening_side"]
    old = project_io.from_dict(data).lid                    # older files: the front
    assert old.slide_from == old.opening_side == "front"


def test_templates_remember_where_they_came_from(tmp_path):
    p = templates.from_template("pi")
    assert p.template == "pi" and default_project(BOX).template == ""
    path = tmp_path / "pi.3dn00b"
    project_io.save_project(p, path)
    assert project_io.load_project(path).template == "pi"
    data = project_io.to_dict(p)
    del data["project"]["template"]                       # older files: not from a template
    assert project_io.from_dict(data).template == ""
