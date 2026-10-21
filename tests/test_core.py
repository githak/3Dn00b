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
    assert data["version"] == 2
    data["version"] = 1                        # files from 0.1/0.2 have no "kind"
    for h in data["project"]["holes"]:
        for key in ("kind", "width", "height"):
            del h[key]
    assert project_io.from_dict(data).holes[0].kind == "round"
