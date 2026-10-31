"""Interactive 3D preview based on pyqtgraph's OpenGL widget."""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph.opengl as gl
from pyqtgraph.opengl import shaders
from pyqtgraph import Vector
from PySide6.QtCore import QCoreApplication, QPoint, Qt, Signal
from PySide6.QtGui import QSurfaceFormat, QVector4D
from PySide6.QtWidgets import QLabel

from .. import geometry, mounts
from . import theme
from ..model import (BOTTOM, LID, RECT, SIDE, VENT, Hole, Project, hole_center_3d,
                     corner_rounding, surface_frame, vent_openings)

# Soft two-sided lighting: a light near the camera plus a fill light and ambient,
# so the inside of the box and faces turned away are still readable.
SOFT_SHADER = shaders.ShaderProgram("n00b_soft", [
    shaders.VertexShader("""
        uniform mat4 u_mvp;
        uniform mat3 u_normal;
        attribute vec4 a_position;
        attribute vec3 a_normal;
        attribute vec4 a_color;
        varying vec4 v_color;
        varying vec3 v_normal;
        void main() {
            v_normal = normalize(u_normal * a_normal);
            v_color = a_color;
            gl_Position = u_mvp * a_position;
        }
    """),
    shaders.FragmentShader("""
        #ifdef GL_ES
        precision mediump float;
        #endif
        varying vec4 v_color;
        varying vec3 v_normal;
        void main() {
            vec3 n = normalize(v_normal);
            float key = abs(dot(n, normalize(vec3(-0.4, 0.6, 1.0))));
            float fill = abs(dot(n, normalize(vec3(0.8, -0.3, 0.4))));
            vec3 rgb = v_color.rgb * (0.38 + 0.5 * key + 0.17 * fill);
            gl_FragColor = vec4(min(rgb, vec3(1.0)), v_color.a);
        }
    """),
])

BODY_COLOR = (0.40, 0.60, 0.90, 1.0)        # soft blue, like the accent colour
LID_COLOR = (0.95, 0.66, 0.32, 1.0)         # warm amber, so the lid stands apart
HOLE_COLOR = (0.06, 0.07, 0.09, 0.95)
SELECTED_COLOR = theme.gl_color("#ff5fa2")
PROBLEM_COLOR = theme.gl_color(theme.DANGER)
BOARD_COLOR = theme.gl_color(theme.SUCCESS)
BACKGROUND = (19, 22, 28)
GRID_COLOR = (74, 83, 101, 110)
LID_LIFT = 15.0   # extra space between body and lid in the preview
# Camera presets: (elevation, azimuth) in degrees. The front of the object faces -y.
VIEWS = {"3d": (28.0, -62.0), "front": (6.0, -90.0), "top": (89.9, -90.0), "side": (6.0, 0.0)}


def prepare_opengl():
    """Must run before the QApplication is created.

    pyqtgraph compiles its shaders once per process, so all OpenGL contexts
    have to share resources (e.g. when a window is re-created).
    """
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    fmt = QSurfaceFormat.defaultFormat()
    fmt.setSamples(4)            # smoother edges in the 3D preview
    QSurfaceFormat.setDefaultFormat(fmt)


class Viewer(gl.GLViewWidget):
    """Shows the body and the (lifted) lid; reports clicks on surfaces.

    Signals carry (part, point, normal) where point is in *assembled*
    coordinates, i.e. as if the lid were sitting on the box.
    """

    surfaceDoubleClicked = Signal(str, tuple, tuple)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundColor(BACKGROUND)
        self.setMinimumSize(420, 360)
        self._press_pos: QPoint | None = None
        self._dragging = False
        self.drag_handler = None
        self.setMouseTracking(True)
        self._solids: dict[str, object] = {}
        self._lid_offset = 0.0
        self._mesh_items: list = []
        self._marker_items: list = []
        self._mount_items: list = []
        self._grid = gl.GLGridItem()
        self._grid.setColor(GRID_COLOR)
        self.addItem(self._grid)
        self.show_lid = True
        self._fitted_size = None
        self._overlay = None

        self.hint = QLabel(
            "Drag to turn  ·  Scroll or right-drag to zoom  ·  Middle-drag to move\n"
            "Drag a hole or board to move it  ·  Double-click a wall to add a hole", self)
        self.hint.setObjectName("viewHint")

    def set_overlay(self, widget):
        """Floating controls shown in the top right corner of the view."""
        widget.setParent(self)
        self._overlay = widget
        self._place_overlays()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place_overlays()

    def _place_overlays(self):
        margin = 12
        if self._overlay is not None:
            self._overlay.adjustSize()
            self._overlay.move(self.width() - self._overlay.width() - margin, margin)
            self._overlay.raise_()
        self.hint.adjustSize()
        self.hint.move(margin, self.height() - self.hint.height() - margin)

    # ---- content --------------------------------------------------------
    def set_parts(self, project: Project, parts: geometry.Parts | None):
        for item in self._mesh_items:
            self.removeItem(item)
        self._mesh_items.clear()
        self._solids.clear()
        if parts is None:
            return
        self._lid_offset = project.lid.lip_height + LID_LIFT
        self._add_mesh(parts.body, BODY_COLOR, 0.0)
        self._solids["body"] = parts.body
        if parts.lid is not None and self.show_lid:
            self._add_mesh(parts.lid, LID_COLOR, self._lid_offset)
            self._solids["lid"] = parts.lid
        size = max(project.outer_width, project.outer_depth)
        grid = max(50.0, math.ceil(size * 1.6 / 10) * 10)
        self._grid.setSize(grid, grid)
        self._grid.setSpacing(10, 10)
        key = (round(size), round(project.closed_height))
        if self._fitted_size is None:
            self.reset_view(project)
        self._fitted_size = key

    def release_geometry(self):
        """Forget the solids used for click picking (see release_window)."""
        self._solids.clear()

    def _add_mesh(self, solid, color, z_offset):
        verts, tris = geometry.mesh_arrays(solid)
        if len(tris) == 0:
            return
        data = gl.MeshData(vertexes=verts.astype(np.float32), faces=tris.astype(np.int32))
        item = gl.GLMeshItem(meshdata=data, smooth=False, shader=SOFT_SHADER, color=color,
                             glOptions="opaque")
        item.translate(0, 0, z_offset)
        self.addItem(item)
        self._mesh_items.append(item)

    def set_hole_markers(self, project: Project, selected_id: str | None, problem_ids: set):
        for item in self._marker_items:
            self.removeItem(item)
        self._marker_items.clear()
        for hole in project.holes:
            if hole.surface == LID and ("lid" not in self._solids):
                continue
            if hole.id == selected_id:
                color, width = SELECTED_COLOR, 4
            elif hole.id in problem_ids:
                color, width = PROBLEM_COLOR, 3
            else:
                color, width = HOLE_COLOR, 1.5
            for ring in _hole_rings(project, hole):
                if hole.surface == LID:
                    ring = ring + np.array([0, 0, self._lid_offset])
                item = gl.GLLinePlotItem(pos=ring, color=color, width=width, antialias=True,
                                         glOptions="translucent")
                self.addItem(item)
                self._marker_items.append(item)

    def set_mount_markers(self, project: Project, selected_id: str | None, problem_ids: set):
        """Board outlines (where the board will sit, not printed) and post rings."""
        for item in self._mount_items:
            self.removeItem(item)
        self._mount_items.clear()
        for m in project.mounts:
            if m.id == selected_id:
                color, width = SELECTED_COLOR, 3.5
            elif m.id in problem_ids:
                color, width = PROBLEM_COLOR, 3
            else:
                color, width = BOARD_COLOR, 2
            z = mounts.board_bottom(project, m) + 0.05
            lines = []
            corners = mounts.board_corners(m)
            if corners:
                lines.append(np.array([(x, y, z) for x, y in corners + corners[:1]]))
            t = np.linspace(0, 2 * np.pi, 33)
            r = mounts.post_radius(m) + 0.5
            for x, y in mounts.post_positions(m):
                lines.append(np.column_stack([x + r * np.cos(t), y + r * np.sin(t), np.full_like(t, z)]))
            for line in lines:
                item = gl.GLLinePlotItem(pos=line, color=color, width=width, antialias=True,
                                         glOptions="translucent")
                self.addItem(item)
                self._mount_items.append(item)

    def reset_view(self, project: Project):
        self.set_view(project, "3d")

    def set_view(self, project: Project, name: str):
        """Look at the whole object from one of the VIEWS."""
        size = max(project.outer_width, project.outer_depth, project.closed_height)
        center_z = (project.closed_height + (LID_LIFT + project.lid.lip_height
                                             if project.lid.enabled else 0)) / 2
        elevation, azimuth = VIEWS[name]
        self.setCameraPosition(pos=Vector(0, 0, center_z), distance=size * 2.6,
                               elevation=elevation, azimuth=azimuth)

    # ---- picking --------------------------------------------------------
    # ---- mouse: drag holes, otherwise turn the view ------------------------
    # `drag_handler` (the main window) decides what can be dragged. It provides:
    #   hole_at(origin, direction, mesh_distance) -> bool
    #   drag_begin(origin, direction, mesh_distance) -> bool
    #   drag_move(origin, direction), drag_end()
    def mousePressEvent(self, ev):
        self._press_pos = ev.position().toPoint()
        if ev.button() == Qt.MouseButton.LeftButton and self.drag_handler is not None:
            ray = self.mouse_ray(ev)
            if ray and self.drag_handler.drag_begin(*ray, self.mesh_distance(*ray)):
                self._dragging = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                ev.accept()
                return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._dragging:
            ray = self.mouse_ray(ev)
            if ray:
                self.drag_handler.drag_move(*ray)
            ev.accept()
            return
        if ev.buttons() == Qt.MouseButton.NoButton and self.drag_handler is not None:
            ray = self.mouse_ray(ev)
            over = bool(ray) and self.drag_handler.hole_at(*ray, self.mesh_distance(*ray))
            if over:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.unsetCursor()
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.drag_handler.drag_end()
            ev.accept()
            return
        super().mouseReleaseEvent(ev)
        self._press_pos = None

    def mouse_ray(self, ev):
        """Normalised (origin, direction) of the ray under the mouse."""
        pos = ev.position()
        ray = self.ray(pos.x(), pos.y())
        if ray is None:
            return None
        origin, end = ray
        direction = end - origin
        length = np.linalg.norm(direction)
        if length == 0:
            return None
        return origin, direction / length

    def mesh_distance(self, origin, direction):
        """Distance along a ray to the first visible part of the model, or None."""
        best = None
        far = origin + direction * 1e5
        for part, solid in self._solids.items():
            shift = np.array([0, 0, self._lid_offset if part == "lid" else 0.0])
            hits = solid.ray_cast(list(origin - shift), list(far - shift))
            if hits:
                d = float(np.linalg.norm(np.array(hits[0].position) - (origin - shift)))
                best = d if best is None else min(best, d)
        return best

    def project_point(self, point):
        """Widget pixel position of a 3D point (used by tests)."""
        viewport = self.getViewport()
        mvp = self.projectionMatrix(viewport, viewport) * self.viewMatrix()
        p = mvp.map(QVector4D(float(point[0]), float(point[1]), float(point[2]), 1.0))
        x, y = p.x() / p.w(), p.y() / p.w()
        return (x + 1) / 2 * self.width(), (1 - y) / 2 * self.height()

    @property
    def lid_offset(self) -> float:
        return self._lid_offset

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            pos = ev.position().toPoint()
            hit = self.pick(pos.x(), pos.y())
            if hit:
                self.surfaceDoubleClicked.emit(*hit)

    def ray(self, x: float, y: float):
        """World-space ray (origin, end) through a widget pixel."""
        w, h = max(self.width(), 1), max(self.height(), 1)
        viewport = self.getViewport()
        proj = self.projectionMatrix(viewport, viewport)
        mvp = proj * self.viewMatrix()
        inv, ok = mvp.inverted()
        if not ok:
            return None
        nx, ny = 2.0 * x / w - 1.0, 1.0 - 2.0 * y / h
        pts = []
        for nz in (-1.0, 1.0):
            p = inv.map(QVector4D(nx, ny, nz, 1.0))
            pts.append(np.array([p.x(), p.y(), p.z()]) / p.w())
        return pts

    def pick(self, x: float, y: float):
        ray = self.ray(x, y)
        if ray is None:
            return None
        origin, end = ray
        best = None
        for part, solid in self._solids.items():
            shift = np.array([0, 0, self._lid_offset if part == "lid" else 0.0])
            hits = solid.ray_cast(list(origin - shift), list(end - shift))
            if hits and (best is None or hits[0].distance < best[0]):
                best = (hits[0].distance, part, hits[0])
        if best is None:
            return None
        _, part, hit = best
        return part, tuple(float(c) for c in hit.position), tuple(float(c) for c in hit.normal)


def _outline(hole, steps: int = 48):
    """Outline of an opening as (du, dv) offsets in mm, a little larger than the opening."""
    if hole.kind == RECT:
        hu, hv = hole.width / 2 + 0.6, hole.height / 2 + 0.6
        r = corner_rounding(hole)
        if r <= 0:
            return (np.array([-hu, hu, hu, -hu, -hu]), np.array([-hv, -hv, hv, hv, -hv]))
        r += 0.6
        # Quarter circles in each corner, going round anticlockwise.
        t = np.linspace(0, np.pi / 2, steps // 4 + 1)
        du, dv = [], []
        for (su, sv), start in (((1, 1), 0.0), ((-1, 1), np.pi / 2), ((-1, -1), np.pi),
                                ((1, -1), 1.5 * np.pi)):
            du.append(su * (hu - r) + r * np.cos(t + start))
            dv.append(sv * (hv - r) + r * np.sin(t + start))
        du, dv = np.concatenate(du), np.concatenate(dv)
        return np.append(du, du[0]), np.append(dv, dv[0])
    r = hole.diameter / 2 + 0.6
    t = np.linspace(0, 2 * np.pi, steps + 1)
    return r * np.cos(t), r * np.sin(t)


def _hole_rings(project: Project, hole) -> list[np.ndarray]:
    """Outline(s) of a hole, drawn just outside the surface it is on."""
    if hole.kind == VENT:
        # The vent's whole area (what you grab and move) plus each slot.
        area = Hole(surface=hole.surface, kind=RECT, width=hole.width, height=hole.height,
                    u=hole.u, v=hole.v, rounding=hole.rounding)
        rings = _hole_rings(project, area)
        for slot in vent_openings(project, hole):
            # Undo the outline's extra margin so slot outlines match the slots.
            slot.width, slot.height = max(slot.width - 1.2, 0.2), max(slot.height - 1.2, 0.2)
            rings += _hole_rings(project, slot)
        return rings
    du, dv = _outline(hole)
    rings = []
    if hole.surface == SIDE:
        big_r = project.outer_diameter / 2 + 0.3
        if hole.kind == RECT:
            # Add points along the long edges so they follow the curve.
            du = np.concatenate([np.linspace(a, b, 12, endpoint=False) for a, b in zip(du[:-1], du[1:])] + [du[-1:]])
            dv = np.concatenate([np.linspace(a, b, 12, endpoint=False) for a, b in zip(dv[:-1], dv[1:])] + [dv[-1:]])
        angles = np.radians(hole.u) + du / big_r
        z = project.outer_height / 2 + hole.v + dv
        rings.append(np.column_stack([np.sin(angles) * big_r, -np.cos(angles) * big_r, z]))
        return rings
    center, _ = hole_center_3d(project, hole)
    _, n, right, up = surface_frame(project, hole.surface)
    c = np.array(center) + np.array(n) * 0.3
    ring = c + np.outer(du, right) + np.outer(dv, up)
    rings.append(ring)
    if hole.surface == BOTTOM:
        # Also show it on the inside floor, which is what you usually see.
        rings.append(ring + np.array([0, 0, project.bottom + 0.6]))
    elif hole.surface != LID:
        # Wall holes: also outline on the inside face.
        rings.append(ring - np.array(n) * (project.wall + 0.6))
    return rings
