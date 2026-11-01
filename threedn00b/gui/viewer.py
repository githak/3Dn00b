"""Interactive 3D preview based on pyqtgraph's OpenGL widget."""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph.opengl as gl
from OpenGL import GL
from pyqtgraph.opengl import shaders
from pyqtgraph import Vector
from PySide6.QtCore import QCoreApplication, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QSurfaceFormat, QVector3D, QVector4D
from PySide6.QtWidgets import QLabel

from .. import geometry, measure, mounts
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
# See-through view: the parts are drawn faint, and the outlines of holes and boards on
# top of everything, so you can see where things sit against the walls.
GHOST_ALPHA = {"body": 0.30, "lid": 0.22}
GHOST_HOLE_COLOR = (0.86, 0.90, 1.0, 0.95)        # light: the walls behind are dark
BLEND = (GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
GHOST_OPTIONS = {GL.GL_DEPTH_TEST: True, GL.GL_BLEND: True, GL.GL_CULL_FACE: False,
                 "glBlendFunc": BLEND, "glDepthMask": (GL.GL_FALSE,)}
ON_TOP_OPTIONS = {GL.GL_DEPTH_TEST: False, GL.GL_BLEND: True, "glBlendFunc": BLEND}
# Measurements (the Sizes button): the outside size in grey, the selected hole's place in pink.
SIZE_LINE_COLOR = (0.62, 0.67, 0.76, 0.9)
SIZE_TEXT_COLOR = theme.TEXT
HOLE_MEASURE_TEXT = "#ff9cc9"
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


class GhostMesh(gl.GLMeshItem):
    """A see-through mesh: blended, and not hiding what's behind it (no depth writes)."""

    def paint(self):
        super().paint()
        GL.glDepthMask(GL.GL_TRUE)      # the next frame must be able to clear the depth buffer


class MeasureLabel(gl.GLTextItem):
    """A measurement's text on a small dark tag, so it reads over the model and the grid."""

    def paint(self):
        if not self.text:
            return
        self.setupGLState()
        point = self.compute_projection().map(QVector3D(*self.pos)).toPointF()
        painter = QPainter(self.view())
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self.font)
        metrics = painter.fontMetrics()
        width, height = metrics.horizontalAdvance(self.text) + 12, metrics.height() + 4
        rect = QRectF(point.x() - width / 2, point.y() - height / 2, width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(BACKGROUND[0], BACKGROUND[1], BACKGROUND[2], 225))
        painter.drawRoundedRect(rect, 5, 5)
        painter.setPen(self.color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text)
        painter.end()


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
        self._label_items: list = []
        self._measure_items: list = []
        self.show_sizes = True
        self._measured = None              # (project, hole) the measurements are for
        self._facing = (1, -1)             # the sides they're drawn along
        self._grid = gl.GLGridItem()
        self._grid.setColor(GRID_COLOR)
        self.addItem(self._grid)
        self.show_lid = True
        self.see_through = False
        self._fitted_size = None
        self._overlay = None

        self.hint = QLabel(
            "Drag to turn  ·  Scroll or right-drag to zoom  ·  Middle-drag to move\n"
            "Drag a hole, board or text to move it  ·  Double-click a wall to add a hole", self)
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
        self._add_mesh(parts.body, BODY_COLOR, 0.0, "body")
        self._solids["body"] = parts.body
        if parts.lid is not None and self.show_lid:
            self._add_mesh(parts.lid, LID_COLOR, self._lid_offset, "lid")
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
        self._measured = None

    def _add_mesh(self, solid, color, z_offset, part):
        verts, tris = geometry.mesh_arrays(solid)
        if len(tris) == 0:
            return
        data = gl.MeshData(vertexes=verts.astype(np.float32), faces=tris.astype(np.int32))
        if self.see_through:
            item = GhostMesh(meshdata=data, smooth=False, shader=SOFT_SHADER,
                             color=color[:3] + (GHOST_ALPHA[part],), glOptions=GHOST_OPTIONS)
            item.setDepthValue(5)                   # after the solid things, before outlines
        else:
            item = gl.GLMeshItem(meshdata=data, smooth=False, shader=SOFT_SHADER, color=color,
                                 glOptions="opaque")
        item.translate(0, 0, z_offset)
        self.addItem(item)
        self._mesh_items.append(item)

    def set_hole_markers(self, project: Project, selected_id: str | None, problem_ids: set):
        self.set_measurements(project, project.hole(selected_id) if selected_id else None)
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
                color, width = (GHOST_HOLE_COLOR if self.see_through else HOLE_COLOR), 1.5
            for ring in _hole_rings(project, hole):
                if hole.surface == LID:
                    ring = ring + np.array([0, 0, self._lid_offset])
                self._marker_items.append(self._outline(ring, color, width))

    def set_measurements(self, project: Project, hole: Hole | None = None):
        """The outside size, and where the selected hole is (when Sizes is on). The size
        lines go along the sides you look at, and move when you turn the view."""
        for item in self._measure_items:
            self.removeItem(item)
        self._measure_items.clear()
        self._measured = (project, hole)
        self._facing = measure.facing_sides(self.opts["azimuth"])
        if not self.show_sizes or "body" not in self._solids:
            return
        groups = [(measure.size_measures(project, self._facing), SIZE_LINE_COLOR, SIZE_TEXT_COLOR)]
        if hole is not None and hole.surface in project.surfaces() and (
                hole.surface != LID or "lid" in self._solids):
            groups.append((measure.hole_measures(project, hole, self._lid_offset),
                           SELECTED_COLOR, HOLE_MEASURE_TEXT))
        font = QFont(self.font())
        font.setPointSizeF(max(8.5, font.pointSizeF() * 0.95))
        for measures, line_color, text_color in groups:
            segments = []
            for m in measures:
                segments += [m.start, m.end]
                for a, b in m.marks:
                    segments += [a, b]
            if not segments:
                continue
            lines = gl.GLLinePlotItem(pos=np.array(segments, dtype=float), mode="lines",
                                      color=line_color, width=1.5, antialias=True,
                                      glOptions=ON_TOP_OPTIONS if self.see_through else "translucent")
            lines.setDepthValue(11)
            self.addItem(lines)
            self._measure_items.append(lines)
            for m in measures:
                label = MeasureLabel(pos=np.array(m.middle, dtype=float), text=m.text,
                                     color=QColor(text_color), font=font)
                label.setDepthValue(20)              # drawn last, over everything
                self.addItem(label)
                self._measure_items.append(label)

    def _camera_moved(self):
        """Turned to look at other sides: move the size lines to them."""
        measured = getattr(self, "_measured", None)      # (not yet set while starting up)
        if measured is not None and measure.facing_sides(self.opts["azimuth"]) != self._facing:
            self.set_measurements(*measured)

    def orbit(self, azim, elev):
        super().orbit(azim, elev)
        self._camera_moved()

    def setCameraPosition(self, *args, **kwargs):
        super().setCameraPosition(*args, **kwargs)
        self._camera_moved()

    def set_label_markers(self, project: Project, selected_id: str | None, problem_ids: set):
        """A frame around the selected text, and around text with a problem."""
        from ..picking import label_area
        for item in self._label_items:
            self.removeItem(item)
        self._label_items.clear()
        for label in project.labels:
            if label.surface not in project.surfaces() or not label.text.strip():
                continue
            if label.surface == LID and "lid" not in self._solids:
                continue
            if label.id == selected_id:
                color, width = SELECTED_COLOR, 3
            elif label.id in problem_ids:
                color, width = PROBLEM_COLOR, 2.5
            else:
                continue
            area = label_area(label)
            area.width += 1.0                 # a little room around the letters
            area.height += 1.0
            out = label.depth + 0.2 if label.style == "raised" else 0.0
            for ring in _hole_rings(project, area, out):
                if label.surface == LID:
                    ring = ring + np.array([0, 0, self._lid_offset])
                self._label_items.append(self._outline(ring, color, width))

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
                self._mount_items.append(self._outline(line, color, width))

    def _outline(self, points, color, width):
        """A marker line; in the see-through view it's drawn on top of everything."""
        item = gl.GLLinePlotItem(pos=points, color=color, width=width, antialias=True,
                                 glOptions=ON_TOP_OPTIONS if self.see_through else "translucent")
        item.setDepthValue(10)
        self.addItem(item)
        return item

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


def _hole_rings(project: Project, hole, out: float = 0.0) -> list[np.ndarray]:
    """Outline(s) of a hole, drawn just outside the surface it is on (`out` mm further,
    for raised text)."""
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
        big_r = project.outer_diameter / 2 + 0.3 + out
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
    c = np.array(center) + np.array(n) * (0.3 + out)
    ring = c + np.outer(du, right) + np.outer(dv, up)
    rings.append(ring)
    if hole.surface == BOTTOM:
        # Also show it on the inside floor, which is what you usually see.
        rings.append(ring + np.array([0, 0, project.bottom + 0.6 + out]))
    elif hole.surface != LID:
        # Wall holes: also outline on the inside face.
        rings.append(ring - np.array(n) * (project.wall + 0.6 + out))
    return rings
