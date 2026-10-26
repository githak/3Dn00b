# 3Dn00b

Software for people getting into 3D printing and want to start with something easier than CAD software. The goal is to have everyone interested in starting 3D printing in focus, not advanced designers. The program is vibe-coded, so if that's not you thing you can look elsewhere.

![3Dn00b showing a box with holes and a push-on lid](docs/screenshot.png)

**3Dn00b is deliberately *not* a CAD program.** You pick a shape, type the
sizes in millimetres, add holes and a lid, and export files your slicer can
print. No sketches, no constraints, no feature trees.

## What it can do (version 0.10)

- **Box** (with rounded corners) or **round container**.
- Sizes as **outside size** or **inside space**, with a single switch.
  The other measurement is always shown.
- Wall and bottom thickness.
- **Compartments**: split a box into evenly sized compartments (for example
  3 × 2), full height or lower. With a lid, the dividers are notched
  automatically so the lid still fits. **New ▸ Shallow tray with compartments**
  starts a ready-made organiser tray.
- **Round and rectangular holes** on any wall, the bottom or the lid. Rectangles
  are for USB ports, switches and small displays, with common sizes built in.
- **Air vents**: set the vent's size, slot width and gap, and the app fits as
  many evenly spaced slots as possible. It warns if the strips between slots
  are thin enough to break. Double-click a wall
  in the 3D view to put a hole there, or use **Add hole**. **Drag a hole** to
  move it: it slides along its own wall, snaps to the centre lines and lines up
  with other holes, and always keeps a safe distance from the edges. Common
  sizes are built in (M3/M4 screws, cables).
- **Screw posts for circuit boards**: pick a board (Raspberry Pi Zero / Zero 2 W,
  3 / 4 / 5, 3 A+, Pico, Arduino Uno, or your own 4-hole board) and all its posts
  appear in the right pattern. Choose the screw size (M1 to M4) and how tall the
  posts are; the screw cuts its own thread into the post. Drag the board's green
  outline to move all its posts together, or turn it in 90° steps. The app checks
  that the board fits, doesn't touch the walls or the lid, and doesn't stick out.
  Boards can be **stacked**: one may overlap another if its posts are tall enough
  to leave room for the lower board's parts (set under "Parts on top").
- A **push-on lid** with a lip and a Tight / Normal / Loose fit (or a custom
  gap). It resizes itself with the box.
- Or a **snap-on lid**: like the push-on lid, but small ridges on its lip click
  into grooves inside the walls.
- Or a **sliding lid** (boxes): a flat panel that slides in from the front along
  grooves in the walls, so the box gets no taller.
- Or a **threaded lid** (round containers): screws on like a jar. The top of the
  container becomes a neck with a thread that prints without supports.
- Or a **screwed-down lid**: a flat lid held by a screw in each corner (M2 to M4).
  The box gets a column in each corner for the screws to cut their own thread
  into, and the app tells you how many screws you need and how long they can be.
- **Checks in plain language**, for example a hole running off the edge of a
  wall, a hole hidden behind the lid's lip, holes that overlap, walls that are
  too thin, or a lid that won't fit. Many come with a one-click **Fix** that
  you can undo.
- **Undo / redo** for every change.
- **Save and reopen** editable projects (`.3dn00b` files, plain JSON).
- **Export for printing** as **STL** (one file per part) or **3MF** (all parts in
  one file, laid out side by side, with the size in millimetres). Parts are flat
  side down and ready for your slicer (the lid comes out upside down, which is how
  it prints best). Every exported part is guaranteed to be watertight.

## Install and run (Linux)

You need Python 3.10 or newer and a working OpenGL driver (any normal
desktop, including integrated graphics).

First install the system packages Qt needs to open a window:

```bash
sudo apt install python3-venv libxcb-cursor0     # Debian / Ubuntu / Mint
sudo dnf install xcb-util-cursor                 # Fedora
sudo pacman -S xcb-util-cursor                   # Arch / Manjaro
```

Then:

```bash
git clone https://github.com/githak/3Dn00b.git
cd 3Dn00b
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/3dn00b                      # or: .venv/bin/3dn00b examples/screw-box.3dn00b
```

To get a menu entry, copy `data/3dn00b.desktop` to `~/.local/share/applications/`
and make sure `3dn00b` is on your `PATH` (for example by symlinking
`.venv/bin/3dn00b` into `~/.local/bin/`).

### Updating

After `git pull`, run `.venv/bin/pip install -e .` again so the right library
versions are installed. (For example, PySide6 6.12.0 has a bug that crashes the
app on Python 3.11, and 3Dn00b now avoids that version.)

## How to use it

1. **Shape**: choose Box or Round container, type the sizes and, for a box,
   choose how many compartments you want.
2. **Holes**: click **Round hole**, **Rectangle** or **Air vent** (or double-click a
   wall in the 3D view), then pick where it goes, how big it is and where on
   that surface it sits. Positions
   are measured from the middle of the surface, so `0` means centred.
3. **Posts** (optional): add screw posts for a circuit board.
4. **Lid**: tick **Add a lid** and choose its type: push-on, snap-on, sliding
   screwed down or threaded.
5. **Check & Export**: read the checks, fix anything marked ✖, pick the file
   type and click **Export for printing**.

In the 3D view: drag a hole to move it, drag anywhere else to turn the view,
scroll or right-drag to zoom, middle-drag to pan, and double-click a wall to
add a hole. Each drag is one step for Undo.

## Examples

The `examples/` folder has a Raspberry Pi box, a Pi Zero box with a screwed-down lid, a screw box with a snap-on lid, a pencil box with a sliding lid, a spice jar with a threaded lid, a screw tray with six compartments,
a pencil cup and a small sensor enclosure with a USB-C opening and an air vent
in the lid.

## Development

```bash
.venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest              # core tests
xvfb-run -a .venv/bin/python -m pytest  # also runs the GUI tests without a screen
```

If PrusaSlicer is installed (`sudo apt install prusa-slicer`), the tests also
slice every example to G-code to make sure the exported files work in a real
slicer.

The code is split so each part can be tested on its own:

| Module | Job |
| --- | --- |
| `threedn00b/model.py` | The editable design: shape, sizes, holes, lid, and the rules for where holes can go |
| `threedn00b/geometry.py` | Turns the design into solid parts (via [Manifold](https://github.com/elalish/manifold)) |
| `threedn00b/validation.py` | Plain-language checks and suggested fixes |
| `threedn00b/project_io.py` | Project files (versioned JSON) and STL export |
| `threedn00b/picking.py` | Works out which wall or hole is under the mouse, and where a dragged hole goes |
| `threedn00b/gui/` | The Qt (PySide6) window and the 3D preview (pyqtgraph) |

See [docs/PRODUCT.md](docs/PRODUCT.md) for the product scope, the decisions
behind it and what is planned next.

## License

GPL-3.0. See [LICENSE](LICENSE).
