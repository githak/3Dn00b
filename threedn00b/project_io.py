"""Saving/loading editable projects and exporting printable STL files."""

from __future__ import annotations

import json
import re
import struct
from dataclasses import asdict, fields
from pathlib import Path

import numpy as np

from . import geometry, mounts
from .model import (HOLE_KIND_LABELS, INSIDE_CORNER_LABELS, LID_STYLE_LABELS, SCREWS, SHAPES,
                    Dividers, Hole, Lid, Mount, Project)

FORMAT_NAME = "3dn00b-project"
FORMAT_VERSION = 11  # 2: rectangular holes; 3: air vents; 4: dividers; 5: screw posts;
                     # 6: screwed-down lids; 7: snap-on and sliding lids; 8: threaded lids;
                     # 9: custom boards with 1 or 2 holes; 10: rounded/angled inside corners;
                     # 11: rounded hole corners and strengthened hole edges
PROJECT_SUFFIX = ".3dn00b"


class ProjectFileError(Exception):
    """A project file could not be read. The message is shown to the user."""


def to_dict(project: Project) -> dict:
    return {"format": FORMAT_NAME, "version": FORMAT_VERSION, "project": asdict(project)}


def from_dict(data: dict) -> Project:
    if not isinstance(data, dict) or data.get("format") != FORMAT_NAME:
        raise ProjectFileError("This isn't a 3Dn00b project file.")
    version = data.get("version")
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise ProjectFileError("This project was made with a newer version of 3Dn00b. "
                               "Please update the app to open it.")
    raw = data.get("project")
    if not isinstance(raw, dict):
        raise ProjectFileError("The project file is damaged.")
    try:
        lid = _build(Lid, raw.get("lid") or {})
        dividers = _build(Dividers, raw.get("dividers") or {})
        mount_list = [_build(Mount, m) for m in raw.get("mounts") or []]
        holes = [_build(Hole, h) for h in raw.get("holes") or []]
        rest = {k: v for k, v in raw.items() if k not in ("lid", "holes", "dividers", "mounts")}
        project = _build(Project, rest)
    except (TypeError, ValueError) as exc:
        raise ProjectFileError("The project file is damaged.") from exc
    if (project.shape not in SHAPES or any(h.kind not in HOLE_KIND_LABELS for h in holes)
            or any(m.board not in mounts.BOARDS or m.screw not in mounts.SCREWS
                   or m.rotation not in mounts.ROTATIONS for m in mount_list)
            or lid.style not in LID_STYLE_LABELS or lid.screw not in SCREWS
            or project.inside_corners not in INSIDE_CORNER_LABELS):
        raise ProjectFileError("The project uses a shape this version doesn't know.")
    project.lid, project.holes, project.dividers = lid, holes, dividers
    project.mounts = mount_list
    return project


def _build(cls, raw: dict):
    """Create a dataclass from a dict, ignoring unknown keys and checking types."""
    kwargs = {}
    for f in fields(cls):
        if f.name not in raw or f.name in ("lid", "holes", "dividers", "mounts"):
            continue
        value = raw[f.name]
        default = getattr(cls(), f.name)
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise ValueError(f.name)
        elif isinstance(default, int):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f.name)
        elif isinstance(default, float):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f.name)
            value = float(value)
        elif isinstance(default, str) and not isinstance(value, str):
            raise ValueError(f.name)
        kwargs[f.name] = value
    return cls(**kwargs)


def save_project(project: Project, path: str | Path) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(to_dict(project), indent=2), encoding="utf-8")
    tmp.replace(path)


def load_project(path: str | Path) -> Project:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise ProjectFileError(f"Couldn't open the file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProjectFileError("The project file is damaged.") from exc
    return from_dict(data)


# ---------------------------------------------------------------------------
# STL export
# ---------------------------------------------------------------------------

def write_stl(solid, path: str | Path, name: str = "3dn00b") -> None:
    """Write a binary STL file."""
    verts, tris = geometry.mesh_arrays(solid)
    tri_pts = verts[tris].astype(np.float32)               # (M, 3, 3)
    normals = np.cross(tri_pts[:, 1] - tri_pts[:, 0], tri_pts[:, 2] - tri_pts[:, 0])
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, lengths, out=np.zeros_like(normals), where=lengths > 0)
    record = np.zeros(len(tris), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    record["n"] = normals
    record["v"] = tri_pts
    header = name.encode("ascii", "replace")[:80].ljust(80, b" ")
    with open(path, "wb") as fh:
        fh.write(header)
        fh.write(struct.pack("<I", len(tris)))
        fh.write(record.tobytes())


def read_stl(path: str | Path) -> np.ndarray:
    """Read a binary STL into an (M, 3, 3) array of triangle corners (used by tests)."""
    data = Path(path).read_bytes()
    count = struct.unpack("<I", data[80:84])[0]
    record = np.frombuffer(data[84:84 + count * 50],
                           dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    return record["v"].copy()


def safe_file_stem(name: str) -> str:
    stem = re.sub(r"[^\w\-]+", "-", name.strip()).strip("-").lower()
    return stem or "3dn00b"


def export_stl_files(project: Project, folder: str | Path, stem: str | None = None) -> list[Path]:
    """Export each printable part as its own STL file, ready for the slicer."""
    folder = Path(folder)
    stem = safe_file_stem(stem or project.name)
    written = []
    for part, solid in geometry.build_parts(project).printable().items():
        path = folder / f"{stem}-{part}.stl"
        write_stl(solid, path, f"{project.name} {part}")
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# 3MF export: all printable parts in one file, laid out on the build plate.
# ---------------------------------------------------------------------------

_3MF_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>
"""
_3MF_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0"
    Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""
_3MF_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PART_SPACING = 10.0       # gap between parts on the build plate


def _xml_text(value: str) -> str:
    from xml.sax.saxutils import escape
    return escape(value, {'"': "&quot;"})


def _mesh_xml(solid) -> str:
    verts, tris = geometry.mesh_arrays(solid)
    vertices = "\n".join(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in verts)
    triangles = "\n".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
    return f"<mesh>\n<vertices>\n{vertices}\n</vertices>\n<triangles>\n{triangles}\n</triangles>\n</mesh>"


def write_3mf(parts: dict, path: str | Path, title: str) -> None:
    """Write named solids (already flat side down) side by side into one 3MF file."""
    import zipfile
    objects, items = [], []
    widths = [solid.bounding_box()[3] - solid.bounding_box()[0] for solid in parts.values()]
    x = -(sum(widths) + PART_SPACING * (len(widths) - 1)) / 2     # centre the row of parts
    for index, ((name, solid), width) in enumerate(zip(parts.items(), widths), start=1):
        box = solid.bounding_box()
        offset = x + width / 2 - (box[0] + box[3]) / 2
        objects.append(f'<object id="{index}" name="{_xml_text(title + " " + name)}" type="model">\n'
                       f'{_mesh_xml(solid)}\n</object>')
        items.append(f'<item objectid="{index}" transform="1 0 0 0 1 0 0 0 1 {offset:.4f} 0 0"/>')
        x += width + PART_SPACING
    model = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
             f'<model unit="millimeter" xml:lang="en-US" xmlns="{_3MF_NS}">\n'
             f'<metadata name="Title">{_xml_text(title)}</metadata>\n'
             f'<metadata name="Application">3Dn00b</metadata>\n'
             '<resources>\n' + "\n".join(objects) + '\n</resources>\n'
             '<build>\n' + "\n".join(items) + '\n</build>\n</model>\n')
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _3MF_CONTENT_TYPES)
        zf.writestr("_rels/.rels", _3MF_RELS)
        zf.writestr("3D/3dmodel.model", model)
    tmp.replace(path)


def read_3mf(path: str | Path) -> list[dict]:
    """Read back a 3MF file (used by tests): name, vertices, triangles and offset per part."""
    import xml.etree.ElementTree as ET
    import zipfile
    ns = {"m": _3MF_NS}
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("3D/3dmodel.model"))
    offsets = {item.get("objectid"): [float(v) for v in item.get("transform").split()[9:12]]
               for item in root.find("m:build", ns)}
    parts = []
    for obj in root.find("m:resources", ns):
        mesh = obj.find("m:mesh", ns)
        verts = np.array([[float(v.get(k)) for k in "xyz"] for v in mesh.find("m:vertices", ns)])
        tris = np.array([[int(t.get(k)) for k in ("v1", "v2", "v3")]
                         for t in mesh.find("m:triangles", ns)])
        parts.append({"name": obj.get("name"), "vertices": verts, "triangles": tris,
                      "offset": offsets[obj.get("id")], "unit": root.get("unit")})
    return parts


def export_3mf_file(project: Project, folder: str | Path, stem: str | None = None) -> Path:
    """Export every printable part into one 3MF file, ready for the slicer."""
    path = Path(folder) / f"{safe_file_stem(stem or project.name)}.3mf"
    write_3mf(geometry.build_parts(project).printable(), path, project.name)
    return path
