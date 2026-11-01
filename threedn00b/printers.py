"""The user's printer and filament: bed size, nozzle and material.

Used for checks (does it fit on the bed? are the walls a whole number of lines?)
and for the estimate of how much plastic a design uses and what it costs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Printer:
    name: str
    width: float          # build plate, left to right (mm)
    depth: float          # build plate, front to back (mm)
    height: float         # how tall a print can be (mm)
    nozzle: float = 0.4


# Build volumes from the makers' specifications.
PRINTERS = {
    "prusa-mk4": Printer("Prusa MK4 / MK4S", 250, 210, 220),
    "prusa-mk3": Printer("Prusa MK3S+", 250, 210, 210),
    "prusa-core-one": Printer("Prusa CORE One", 250, 220, 270),
    "prusa-mini": Printer("Prusa MINI+", 180, 180, 180),
    "prusa-xl": Printer("Prusa XL", 360, 360, 360),
    "bambu-a1": Printer("Bambu Lab A1", 256, 256, 256),
    "bambu-a1-mini": Printer("Bambu Lab A1 mini", 180, 180, 180),
    "bambu-p1": Printer("Bambu Lab P1S / P1P / X1C", 256, 256, 256),
    "ender-3": Printer("Creality Ender 3 (V2, V3, S1)", 220, 220, 250),
    "creality-k1": Printer("Creality K1 / K1C", 220, 220, 250),
    "creality-k1-max": Printer("Creality K1 Max", 300, 300, 300),
    "kobra-2-neo": Printer("Anycubic Kobra 2 Neo", 220, 220, 250),
    "kobra-3": Printer("Anycubic Kobra 3", 250, 250, 260),
    "neptune-4": Printer("Elegoo Neptune 4 / 4 Pro", 225, 225, 265),
    "sovol-sv06": Printer("Sovol SV06", 220, 220, 250),
}
CUSTOM = "custom"
NOZZLES = (0.2, 0.4, 0.6, 0.8)

# Density in g/cm³.
MATERIALS = {"PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "ASA": 1.07, "TPU": 1.21}

PLATE_MARGIN = 2.0      # keep this far from the edges of the plate
PART_GAP = 10.0         # between parts on the same plate (as in the 3MF export)


def fits(size: tuple[float, float, float], printer: Printer) -> bool:
    """Does a part (x, y, z mm) fit, turned either way on the plate?"""
    x, y, z = size
    w, d = printer.width - 2 * PLATE_MARGIN, printer.depth - 2 * PLATE_MARGIN
    return z <= printer.height and ((x <= w and y <= d) or (y <= w and x <= d))


def fit_together(sizes: list[tuple[float, float, float]], printer: Printer) -> bool:
    """Do two parts fit on the plate at the same time, side by side either way?"""
    if len(sizes) < 2:
        return all(fits(s, printer) for s in sizes)
    (ax, ay, _), (bx, by, _) = sizes[:2]
    w, d = printer.width - 2 * PLATE_MARGIN, printer.depth - 2 * PLATE_MARGIN
    for a in ((ax, ay), (ay, ax)):
        for b in ((bx, by), (by, bx)):
            if a[0] + PART_GAP + b[0] <= w and max(a[1], b[1]) <= d:
                return True
            if a[1] + PART_GAP + b[1] <= d and max(a[0], b[0]) <= w:
                return True
    return False


def lines(thickness: float, nozzle: float) -> float:
    """How many lines of plastic a wall this thick is, for this nozzle."""
    return thickness / nozzle


def solid_lines(thickness: float, nozzle: float) -> float:
    """The nearest thickness that is a whole number of lines (at least two); halfway
    rounds up, to the stronger wall."""
    return round(max(2, int(thickness / nozzle + 0.5 + 1e-9)) * nozzle, 2)


def grams(volume_mm3: float, material: str) -> float:
    """Weight of a solid print. Thin-walled boxes print nearly solid, so this is close."""
    return volume_mm3 / 1000.0 * MATERIALS.get(material, MATERIALS["PLA"])
