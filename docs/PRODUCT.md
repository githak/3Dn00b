# 3Dn00b product definition

> A beginner should be able to make a useful, correctly sized, printable box or
> container with a hole and a lid in minutes, not spend hours learning CAD.

3Dn00b is a small, guided Linux desktop app for making simple printable
objects: storage boxes, small electronics enclosures, round containers. It
should feel like *configuring a physical object*, not operating CAD software.
It is deliberately **not** a general CAD program and does not try to replace
FreeCAD, Blender, Fusion or Onshape.

## Decisions agreed for version 0.1

| Question | Decision |
| --- | --- |
| First lid type | **Push-on (friction-fit) lid** with a lip and a fit setting (Tight 0.15 / Normal 0.25 / Loose 0.40 mm per side, or custom) |
| Outside or inside sizes | **A simple switch, outside size by default.** The other measurement is always shown, and switching never changes the object |
| How holes stay put when the object is resized | **Offset from the centre of their surface.** A centred hole stays centred; a hole that no longer fits is flagged with a fix |
| How holes are placed | **Choose a surface (or double-click it in 3D) and set the position with numbers, or drag the hole in 3D** (added in 0.2). Position ranges are limited to valid values |

Defaults I chose myself, which are easy to change:

- Height means the body without the lid. The height with the lid on is shown.
- Holes keep at least `max(1.5 mm, wall thickness)` of material to the edge.
  Closer than 0.4 mm is an error, and anything in between is a warning.
- Common hole sizes are offered: M3 and M4 screw clearance, and cables.

## Must-haves (done)

- Box (with rounded corners) and round container, with outside or inside sizes,
  wall and bottom thickness.
- Live 3D preview: rotate, zoom, double-click a wall to add a hole.
- Drag holes in 3D along their own surface, with snapping to centre lines and
  to other holes, and a safe margin from the edges. Each drag is one undo step.
- Round holes on walls, the bottom and the lid: add, edit, remove, centre.
- Rectangular holes (0.3) with the same placement rules, for USB ports and
  switches, with common sizes and a reminder to measure the real part. Sharp
  corners only; rounded corners were left out to keep the controls minimal.
- Air vents (0.4): one feature with a size, slot width, gap and direction; the
  app fits the slots. For placement it behaves like one rectangle, so all the
  usual rules apply. Up-and-down slots are the default on walls because they
  print without long bridges.
- Compartments (0.5): evenly spaced dividers in boxes (left to right and front
  to back), full height or lower. With a lid they are notched at the ends for
  the lip and stop just below the lid, automatically. Holes where a divider
  meets a wall or the floor are flagged. A "Shallow tray with compartments"
  template is in the New menu. Round containers have no dividers yet.
- Screw posts (0.6), requested by the project owner: posts on the floor for
  M1, M2, M2.5, M3 or M4 screws, with a chosen length. Decisions: the screw
  **cuts its own thread** (pilot hole slightly smaller than the screw, ending at
  the floor), and the **board outline is shown and checked** against the walls,
  the lid's lip, the top of the box, dividers, floor holes and other boards.
  Board presets (from the manufacturers' drawings): Raspberry Pi Zero / Zero W /
  Zero 2 W, 3 B / 3 B+ / 4 / 5, 3 A+, Pico, Arduino Uno, plus a custom 4-hole
  board and a single post. A board's posts move and turn (90° steps) as one
  group. Posts stand on the floor only for now.
- Push-on lid that follows the box size, with fit presets.
- Plain-language checks covering impossible sizes, thin walls, holes off the
  edge, holes behind the lid lip, overlapping or too-close holes, a lid that
  doesn't fit, parts falling apart, and invalid geometry. Errors block export.
- Undo and redo for all edits.
- Save and open versioned, editable project files.
- STL export of each printable part, positioned for printing.

## Deliberate non-goals

Sketching or constraint solvers, a visible feature-history tree, many
toolbars, workbenches or modes, mesh or sculpt editing, assemblies, scripting
in the normal workflow, cloud accounts, AI design features, built-in slicing,
STL import and editing.

## Postponed (candidates for later, in rough priority order)

1. A screw-fastened lid (can reuse the screw posts).
2. Snap-fit and sliding lids. A threaded lid for round containers may come later.
3. 3MF export, if users need it. STEP is unlikely, since the geometry engine is mesh-based.
4. A packaged app (Flatpak or AppImage).

Each addition must pass the brief's test: does it make a common beginner task
much easier, without CAD vocabulary, and without making the interface busier?

## Technical approach

| Area | Choice | Why |
| --- | --- | --- |
| Language | Python 3.10+ | Easy to read and to contribute to |
| GUI | PySide6 (Qt 6), LGPL | Native-looking Linux desktop app, installs from pip |
| 3D preview | pyqtgraph `GLViewWidget` with a custom soft-lit shader | Small, pure Python, works on integrated graphics (OpenGL 2-era shaders) |
| Geometry | **Manifold** (`manifold3d`), Apache-2.0 | Fast, robust Boolean operations whose results are **always watertight**. That is exactly what an STL needs. It is a small pip wheel with no system dependencies |
| Project files | Versioned JSON (`"format": "3dn00b-project", "version": 5`) | Human-readable, diffable, forward-compatible |

**Why not CadQuery or build123d (OpenCascade)?** They are excellent, but they
bring a large binary dependency (OCP), a slower and more fragile pipeline for
what is a box-with-holes problem, and B-rep concepts this app never exposes.
Their main extra benefit is STEP export, which beginners printing on FDM
printers rarely need. If STEP becomes important, the geometry module can be
swapped without touching the model, validation or GUI.

### Known risks and limitations

- **Fit depends on the printer.** The app gives presets and says so clearly; it
  cannot promise a perfect lid fit.
- Round surfaces are made of small flat facets (about 0.6 to 0.8 mm edges),
  which is finer than typical FDM nozzles.
- The 3D view needs OpenGL. Very old or virtual machines without a GL driver
  may fail to show the preview.
- pyqtgraph's shaders are compiled once per process, so the app shares OpenGL
  contexts (`AA_ShareOpenGLContexts`).
