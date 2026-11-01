"""Text for labels: letter outlines read from a bundled TrueType font.

The font is DejaVu Sans Bold (cut down to the letters of European languages):
bold, plain letters print clearly. This reads just what's needed from the
font file (the letter shapes and their widths), so no extra library is needed.
"""

from __future__ import annotations

import math
import struct
from functools import lru_cache
from pathlib import Path

from manifold3d import CrossSection, FillRule

FONT_PATH = Path(__file__).parent / "fonts" / "DejaVuSans-Bold-subset.ttf"
CURVE_STEP = 0.35      # mm: curves are made of straight pieces about this long


class FontError(Exception):
    pass


class Font:
    """The parts of a TrueType font needed to draw text."""

    def __init__(self, data: bytes):
        self.data = data
        num_tables = struct.unpack_from(">H", data, 4)[0]
        self.tables = {}
        for i in range(num_tables):
            tag, _, offset, length = struct.unpack_from(">4sIII", data, 12 + 16 * i)
            self.tables[tag.decode("latin-1")] = (offset, length)
        for needed in ("head", "maxp", "cmap", "loca", "glyf", "hhea", "hmtx"):
            if needed not in self.tables:
                raise FontError(f"The font has no {needed} table.")
        head = self.tables["head"][0]
        self.units_per_em = struct.unpack_from(">H", data, head + 18)[0]
        long_loca = struct.unpack_from(">h", data, head + 50)[0] == 1
        self.num_glyphs = struct.unpack_from(">H", data, self.tables["maxp"][0] + 4)[0]
        loca = self.tables["loca"][0]
        if long_loca:
            self.loca = struct.unpack_from(f">{self.num_glyphs + 1}I", data, loca)
        else:
            self.loca = [2 * v for v in struct.unpack_from(f">{self.num_glyphs + 1}H", data, loca)]
        metrics = struct.unpack_from(">H", data, self.tables["hhea"][0] + 34)[0]
        hmtx = self.tables["hmtx"][0]
        self.advances = [struct.unpack_from(">H", data, hmtx + 4 * i)[0] for i in range(metrics)]
        self.cmap = self._read_cmap()
        self._contours: dict[int, list] = {}
        h = self.glyph_index("H")
        self.cap_height = self._bounds(h)[3] if h else 0.7 * self.units_per_em

    # ---- character map ------------------------------------------------------
    def _read_cmap(self) -> dict[int, int]:
        data, base = self.data, self.tables["cmap"][0]
        count = struct.unpack_from(">H", data, base + 2)[0]
        best = None
        for i in range(count):
            platform, encoding, offset = struct.unpack_from(">HHI", data, base + 4 + 8 * i)
            fmt = struct.unpack_from(">H", data, base + offset)[0]
            if fmt == 12 and (best is None or best[0] != 12):
                best = (12, base + offset)
            elif fmt == 4 and best is None and (platform, encoding) in ((3, 1), (0, 3), (0, 4)):
                best = (4, base + offset)
        if best is None:
            raise FontError("The font has no usable character map.")
        fmt, at = best
        mapping = {}
        if fmt == 4:
            segments = struct.unpack_from(">H", data, at + 6)[0] // 2
            ends = struct.unpack_from(f">{segments}H", data, at + 14)
            starts = struct.unpack_from(f">{segments}H", data, at + 16 + 2 * segments)
            deltas = struct.unpack_from(f">{segments}h", data, at + 16 + 4 * segments)
            range_at = at + 16 + 6 * segments
            offsets = struct.unpack_from(f">{segments}H", data, range_at)
            for s in range(segments):
                for code in range(starts[s], ends[s] + 1):
                    if code == 0xFFFF:
                        continue
                    if offsets[s] == 0:
                        glyph = (code + deltas[s]) & 0xFFFF
                    else:
                        where = range_at + 2 * s + offsets[s] + 2 * (code - starts[s])
                        glyph = struct.unpack_from(">H", data, where)[0]
                        if glyph:
                            glyph = (glyph + deltas[s]) & 0xFFFF
                    if glyph:
                        mapping[code] = glyph
        else:
            groups = struct.unpack_from(">I", data, at + 12)[0]
            for g in range(groups):
                first, last, glyph = struct.unpack_from(">III", data, at + 16 + 12 * g)
                for code in range(first, last + 1):
                    mapping[code] = glyph + code - first
        return mapping

    def glyph_index(self, char: str) -> int | None:
        return self.cmap.get(ord(char))

    def advance(self, glyph: int) -> int:
        return self.advances[min(glyph, len(self.advances) - 1)]

    # ---- letter shapes ------------------------------------------------------
    def _bounds(self, glyph: int) -> tuple[int, int, int, int]:
        start = self.loca[glyph]
        if self.loca[glyph + 1] == start:
            return 0, 0, 0, 0
        return struct.unpack_from(">4h", self.data, self.tables["glyf"][0] + start + 2)

    def contours(self, glyph: int, depth: int = 0) -> list[list[tuple[float, float, bool]]]:
        """The letter's outlines: lists of (x, y, on_curve) points in font units."""
        if glyph in self._contours:
            return self._contours[glyph]
        start, end = self.loca[glyph], self.loca[glyph + 1]
        result: list = []
        if end > start and depth < 8:
            at = self.tables["glyf"][0] + start
            count = struct.unpack_from(">h", self.data, at)[0]
            result = (self._simple(at, count) if count >= 0
                      else self._composite(at + 10, depth))
        self._contours[glyph] = result
        return result

    def _simple(self, at: int, count: int) -> list:
        data = self.data
        ends = struct.unpack_from(f">{count}H", data, at + 10)
        points = ends[-1] + 1 if count else 0
        pos = at + 10 + 2 * count
        pos += 2 + struct.unpack_from(">H", data, pos)[0]        # skip the instructions
        flags = []
        while len(flags) < points:
            flag = data[pos]
            pos += 1
            flags.append(flag)
            if flag & 8:                                          # repeated
                flags += [flag] * data[pos]
                pos += 1
        coords = []
        for short, same in ((2, 16), (4, 32)):
            value, values = 0, []
            for flag in flags[:points]:
                if flag & short:
                    delta = data[pos]
                    pos += 1
                    value += delta if flag & same else -delta
                elif not flag & same:
                    value += struct.unpack_from(">h", data, pos)[0]
                    pos += 2
                values.append(value)
            coords.append(values)
        xs, ys = coords
        contours, first = [], 0
        for last in ends:
            contours.append([(xs[i], ys[i], bool(flags[i] & 1)) for i in range(first, last + 1)])
            first = last + 1
        return contours

    def _composite(self, at: int, depth: int) -> list:
        data, result = self.data, []
        while True:
            flags, glyph = struct.unpack_from(">HH", data, at)
            at += 4
            if flags & 1:                                         # arguments are words
                dx, dy = struct.unpack_from(">hh", data, at)
                at += 4
            else:
                dx, dy = struct.unpack_from(">bb", data, at)
                at += 2
            if not flags & 2:                                     # point matching: rare
                dx = dy = 0
            a, b, c, d = 1.0, 0.0, 0.0, 1.0
            if flags & 8:
                a = d = struct.unpack_from(">h", data, at)[0] / 16384
                at += 2
            elif flags & 0x40:
                a, d = (v / 16384 for v in struct.unpack_from(">hh", data, at))
                at += 4
            elif flags & 0x80:
                a, b, c, d = (v / 16384 for v in struct.unpack_from(">4h", data, at))
                at += 8
            for contour in self.contours(glyph, depth + 1):
                result.append([(a * x + c * y + dx, b * x + d * y + dy, on) for x, y, on in contour])
            if not flags & 0x20:                                  # no more parts
                return result


@lru_cache(maxsize=1)
def font() -> Font:
    return Font(FONT_PATH.read_bytes())


def missing_characters(text: str) -> str:
    """The characters of `text` the font can't draw (spaces are fine)."""
    f = font()
    seen = []
    for char in text:
        if not char.isspace() and f.glyph_index(char) is None and char not in seen:
            seen.append(char)
    return "".join(seen)


def _flatten(contour, scale: float, x0: float) -> list[tuple[float, float]]:
    """Turn a TrueType outline (straight lines and quadratic curves) into points in mm."""
    pts = [((x + x0) * scale, y * scale, on) for x, y, on in contour]
    if len(pts) < 2:
        return []
    # Start on a point that lies on the outline.
    start = next((i for i, p in enumerate(pts) if p[2]), None)
    if start is None:                     # all control points: start between two of them
        a, b = pts[-1], pts[0]
        pts.insert(0, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, True))
        start = 0
    pts = pts[start:] + pts[:start]
    out = [pts[0][:2]]
    current = pts[0]
    control = None
    for p in pts[1:] + pts[:1]:
        if p[2]:
            if control is None:
                out.append(p[:2])
            else:
                out += _curve(current, control, p)
                control = None
            current = p
        else:
            if control is not None:       # two control points: a point halfway is on the outline
                mid = ((control[0] + p[0]) / 2, (control[1] + p[1]) / 2, True)
                out += _curve(current, control, mid)
                current = mid
            control = p
    out.pop()                             # back at the start
    return out


def _curve(p0, c, p1) -> list[tuple[float, float]]:
    length = math.dist(p0[:2], c[:2]) + math.dist(c[:2], p1[:2])
    steps = max(1, min(12, math.ceil(length / CURVE_STEP)))
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        s = 1 - t
        out.append((s * s * p0[0] + 2 * s * t * c[0] + t * t * p1[0],
                    s * s * p0[1] + 2 * s * t * c[1] + t * t * p1[1]))
    return out


@lru_cache(maxsize=128)
def outline(text: str, size: float) -> CrossSection | None:
    """The text as a flat shape, `size` mm = height of the capital letters.

    It's centred on (0, 0): halfway along the text, and halfway up the capital
    letters (so tails of g and y reach below). Letters the font lacks are left out.
    """
    f = font()
    if size <= 0 or not text.strip():
        return None
    scale = size / f.cap_height
    polygons, x = [], 0.0
    for char in text:
        glyph = f.glyph_index(char)
        if glyph is None:
            if char.isspace():
                x += f.advance(f.glyph_index(" ") or 0)
            continue
        for contour in f.contours(glyph):
            points = _flatten(contour, scale, x)
            if len(points) >= 3:
                polygons.append(points)
        x += f.advance(glyph)
    if not polygons:
        return None
    shape = CrossSection(polygons, FillRule.NonZero)
    if shape.is_empty():
        return None
    return shape.translate([-x * scale / 2, -size / 2])


def text_size(text: str, size: float) -> tuple[float, float, float, float]:
    """Bounds (x_min, y_min, x_max, y_max) of the text's shape in mm, or zeros."""
    shape = outline(text, size)
    if shape is None:
        return 0.0, 0.0, 0.0, 0.0
    b = shape.bounds()
    return b[0], b[1], b[2], b[3]
