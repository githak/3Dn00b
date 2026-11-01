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
- Stacked boards (0.6.1), requested by the project owner: boards may overlap
  when one sits higher. Each board has a "Parts on top" height (preset default,
  editable); the board above needs that much room plus 1 mm. Flat boards
  (Pi Zero family, Pico) with enough room are approved; boards with tall
  sockets (Pi 3/4/5, 3 A+, Arduino Uno, custom) get a reminder to check, since
  their parts vary. Too little room, or a post that would have to pass through
  the lower board, is an error.
- Screwed-down lid (0.7): a lid type next to the push-on lid. Flat lid, no lip,
  clearance holes in the corners; the box gets a full-height column in each
  corner (tangent to the walls or the rounded corner; four columns spaced around
  a round container) with a pilot hole the screw cuts its own thread into,
  16 mm deep at most and never into the floor. Wall holes, floor holes, lid
  holes and circuit boards are kept clear of the columns, with fixes where
  possible.
- Snap-on and sliding lids (0.8). Snap-on: the push-on lid plus 0.5 mm ridges
  on the middle third of each side of the lip, clicking into matching grooves
  in the walls; works for boxes and round containers; checks lip depth and
  wall thickness. Sliding (boxes only): a flat panel in grooves in the left,
  right and back walls, entering from the front where the wall is lowered; the
  back of the groove follows rounded corners so it never breaks through. The
  panel sits inside the walls. Tests slide it all the way out to prove the path
  is clear.
- Threaded lid (0.9), round containers only: the container's top becomes a neck
  with a rounded, right-hand thread (4 mm per turn, 1.2 mm deep, so the flanks
  stay under 45° and print without supports); inside, the wall narrows to the
  neck at 45°. The lid is a flush cap with the matching thread, its clearance
  set by the usual fit. Tests unscrew the lid through two turns for several
  sizes and fits and check it never collides, and that pulling straight up or
  turning the wrong way is blocked. Holes are kept off the neck.
- 3MF export (0.10): next to STL, a "File type" choice exports all parts into
  one 3MF file, laid out side by side 10 mm apart and centred, with millimetres
  stated in the file. Tests read the file back and compare every vertex and
  triangle with the built parts; PrusaSlicer opens and slices every example.
- Debian package (0.11): `packaging/build_deb.py` builds one amd64 .deb for
  Debian 12/13, Ubuntu 22.04+ and derivatives. It bundles the libraries Debian
  lacks for Python 3.10–3.14 (shared parts stored once, unused Qt parts left
  out), declares Qt's system libraries as dependencies, adds a menu entry, icon
  and .3dn00b file type, and pre-compiles Python files on install. CI installs
  it on clean Debian 12/13 and Ubuntu 22.04/24.04/26.04 and runs the app's
  `--smoke-test` (window, 3D view, geometry, STL/3MF export).
- Custom boards with 1 or 2 holes (0.12), requested by the project owner (for
  example a DRV8833 motor driver with two holes, or fastening something with a
  single screw). The 2-hole board has its holes in a line by default; a depth
  spacing makes them diagonal (negative flips the diagonal). The 1-hole board's
  hole can sit anywhere on the board. Both keep the board outline checks.
- Inside corners (0.13), suggested by the project owner for strength: sharp,
  rounded (fillet) or angled (45° chamfer) with a size, where the walls meet the
  floor (boxes and round containers, including threaded jars) and in the inside
  vertical corners of boxes. Sharp stays the default so existing designs don't
  change. Lips, screw columns and dividers follow the rounder corners; holes and
  posts keep off the sloped area. Outside corners were already adjustable.
- Stronger joints and hole edges (0.14), suggested by the project owner:
  - Dividers get the same rounded or angled joints as the inside corners, where
    they meet the floor, the walls and each other, with no extra setting. Very
    low dividers (lower than the corner size) keep sharp joints, with a note.
  - Rectangular holes and vent slots have a corner rounding (new ones 1 mm; the
    common sizes set their own, such as 3 mm for USB-C). Chamfering a hole's
    edge was considered and left out: it removes material, so it makes the edge
    weaker, not stronger.
  - Wall holes can get a frame on the inside: a 2 mm flat band around the
    opening, standing out by the wall thickness (1.2 to 3 mm), with 45° sides
    so it prints without support. On for new rectangles (where plugs go), off
    for round holes and vents. Frames stay out of the lid's way; a board that
    would hit one is an error.
- Compartments of different sizes (0.15), requested by the project owner (for
  example screws of different lengths): per direction, a "Set each width/depth"
  switch shows one size per compartment except the last, which gets the rest of
  the room. Resizing the box therefore only changes the last compartment, and
  changing the number of compartments keeps the sizes already set. Sizes that
  don't fit, or a compartment under 3 mm, are errors. The tabs now scroll, so
  many compartments fit on small screens.
- Easy opening (0.16), requested by the project owner because tight push-on and
  snap-on lids are hard to get off: an "Easy opening" choice adds a tab to the
  front of the lid (20 mm wide, sticking out 5 mm, as thick as the lid and flush
  with its top, so it prints flat; rounded where it joins the lid so it doesn't
  crack), a finger notch in the top of the front wall (16 mm wide, 3 mm deep and
  never deeper than the lip, rounded at the bottom), or both. Neither weakens the
  lid's hold, and both are better than prying with a fingernail or a tool. Off
  by default so existing designs don't change. A looser fit remains the other
  answer for a lid that is simply too tight.
- Lid sides (0.21), requested by the project owner: a sliding lid can slide in
  from the front, back, left or right, and the tab and notch can be on any of
  those sides. Both are made as if at the front and then turned, so the groove,
  the lowered wall and the panel always match; tests slide the lid out each way
  and check it's held in every other direction.
- Dark, modern interface (0.22), requested by the project owner. One colour scheme
  defined in `gui/theme.py` (cool dark greys, one blue accent, green / amber / red
  only for status) and line icons drawn from SVG. The layout follows the work:
  a rail of steps on the left (Shape, Holes, Posts, Lid, Export, with Ctrl+1 to 5),
  the settings of the current step grouped in cards, and the 3D view with floating
  camera buttons (3D, Front, Top, Side) and the lid toggle. The header holds the
  file actions, Undo / Redo, the design's name and one accent button: Export. A
  status chip in the corner and the Export step's icon show the result of the
  checks at all times. Problems for a selected hole or board appear at the top of
  its card, and its list row gets a red or amber sign.
- Welcome tour (0.24), requested by the project owner: shown on the first start,
  then only from Help (the ? button, or F1) unless the user ticks "Show this
  welcome when 3Dn00b starts". The first page says what the app is and isn't
  and how it works in three steps; seven short pages then explain the steps,
  templates, holes, posts, lids, the 3D view and checking/export. Their
  screenshots are taken live from a hidden example window (a Raspberry Pi case),
  so they always match the app; everything but the part being explained is
  darkened, and that part is outlined in the accent colour, together with the
  step's button in the rail (0.24.1) so it's clear which step is open.
- See-through view (0.26), requested by the project owner: a toggle next to Lid in
  the 3D view (Ctrl+T; Lid got Ctrl+L). The box and lid are drawn faint (blended,
  without hiding what's behind them) and the outlines of holes, boards and posts
  are drawn on top of everything, in a light colour, so their places against the
  walls are easy to check, also from straight above with Top. The welcome tour
  has a page about it.
- Templates (0.17), requested by the project owner so beginners don't size a
  case by trial and error: a template list in the Shape tab, right under the Box
  and Round container buttons, so a template is the third way to start.
  Board cases are built from the board catalogue, so the box fits the board with
  1.5 to 2.5 mm of room (more where a socket sticks out, such as the Arduino's
  USB socket), the posts match the holes, and openings sit in front of the
  sockets, made larger than the plugs. One Raspberry Pi 3 / 4 / 5 case works for
  all three: their power and HDMI sockets share one opening along the front, and
  USB and network one on the right. The stacked Zero 2 W template crosses the
  boards like a +, so the upper board's posts miss the lower board; its sockets
  face the middle, so cables reach them through openings in the walls. Picking a
  template is one undo step.
  From 0.23 a design remembers which template it came from. Choosing Box or Round
  container then starts over with a plain one (the template's holes, posts and
  lid rarely fit another shape); for the user's own designs those buttons keep
  reshaping the design. A note under the template list says so, and Undo brings
  the template back. The field is optional, so older versions still open the file.
  Checked in 0.25 against NopSCADlib and @jwc/jscad-raspberrypi, and in 0.25.1
  against the official drawings themselves (Raspberry Pi 3 B+, 3 A+, 4, 5 and Zero 2 W
  mechanical drawings, the Pico datasheet, the Arduino Uno and Mega datasheets),
  which confirmed every socket position and the Mega's six holes, and showed a few
  sockets sticking out further than modelled (the Pi audio jack 2.6 mm, the Pi 3 A+'s
  USB 2.5 mm, the Zero's micro USB 1.35 mm). Every board case leaves room for the
  sockets that stick out past the board (up to 3 mm for the Pi 4/5's USB and
  network, 2.6 mm for the audio jack, 2.5 mm for the SD card, 6.4 mm for the
  Arduino's USB B) so the board drops in, and every opening sits in front of its socket and is big enough for
  the moulded part of a normal plug. The Pi case got an opening for the Pi 5's
  power button and its fan sits over the Pi 5's processor; the Zero cases' two
  micro USB sockets share one opening (12.6 mm apart is too close for two). The
  stacked Zero template now puts the upper board's sockets right behind the right
  wall and the lower board's about 10 mm from the front wall (the closest the
  upper board's posts allow); before, the lower board's sockets were 20 mm in.
  A test checks every socket of every board template and example this way.
  Added in 0.18: a Pi 5 case with a 30 mm fan in the lid (26 mm opening and four
  M3 holes 24 mm apart, over the processor and clear of the tall sockets), a Pi
  Pico case (8 mm posts leave room for pin headers underneath), and an ESP32
  DevKit case. ESP32 boards differ between makers and many have no mounting
  holes, so that template uses the custom 4-hole board with a common 30-pin
  board's size, which the user adjusts after measuring.
  Added in 0.19, grouped under headings in the list (Cases for boards, Storage,
  Around the house): Pi 3 A+ and Arduino Mega 2560 cases (the Mega joins the
  board catalogue, with its six holes), a project box for the user's own board,
  a weekly pill box, business card box, dice box, money box (coin slot in a
  screwed-down lid), desk organiser, charging box and a plant pot with drainage
  holes.
  Added in 0.20: a Pi 3 / 4 / 5 case with a ribbon-cable slot in the lid (as close
  to the GPIO header as the lid's lip allows), a half-size breadboard box, a 4 × 4
  parts box, 3 × 3 craft box, guitar pick box, small screw-top tin, soap dish,
  key tray, toothbrush cup, tea bag box and remote control holder (35 templates).
- Printer, plastic, fit test and text (0.27), the first group of additions the
  project owner picked from a list of suggestions:
  - Your printer and filament: a card in the Export step (saved for all designs,
    not in the project file) with printer presets from the makers' build volumes,
    or a typed build size; nozzle 0.2 to 0.8 mm; PLA, PETG, ABS, ASA or TPU; and
    the spool price in the system's currency. With a printer set, the checks say
    when a part doesn't fit on the plate (turned either way, 2 mm from the edges),
    when box and lid only fit one after the other, and when walls or dividers
    aren't a whole number of nozzle lines (fewer than two lines is a warning;
    between two whole numbers is a tip), with a one-click fix. The generic
    "larger than most printers" warning is then replaced by the real check.
  - Plastic estimate: grams per part (solid volume × density, close for thin
    walls) and the cost, in the summary at the top of the Export step. No print
    time: that depends on the slicer settings, which the app can't know.
  - Fit test print: the top of the box with the lid ring (the lid without its
    middle: what has to fit stays), and the walls with the openings. With screw
    posts that piece starts at the floor, which is opened up but keeps a rim, the
    floor under the posts and dividers, and a bar from each post to the nearest
    wall, so the board can be screwed on and the plugs tried. Pieces close
    together become one. The card shows the grams compared with the whole thing.
    To keep the pieces whole, the lid's screw columns were filled out towards
    their corner; before, they touched the walls only along a line.
  - Text: raised or engraved, on a wall, the bottom or the lid, with letter height
    (capital letters) and depth, positioned like holes and dragged in the 3D view.
    On a round container the text wraps around the wall. The font is DejaVu Sans
    Bold, cut down to the letters of European languages (22 KB), read by a small
    TrueType reader in `text.py` so no extra library is needed. Raised text on the
    lid or the bottom gets a warning (the lid prints upside down, the box stands on
    its bottom: it would need supports) with a fix that engraves it; the bottom's
    text reads correctly when the box is tipped towards you. Checks: text off the
    surface (with a fix), letters under 5 mm, engraving that leaves under 0.8 mm,
    text running into holes or other text. Text is its own step, between Lid and
    Export, and the welcome tour has a page about it. Project format 15.
- Files, own templates and measurements (0.28), the second group the project owner
  picked:
  - Recent designs: the arrow next to Open lists the last 8 opened or saved
    designs (files that are gone are dropped), with "Clear the list".
  - Automatic backup and recovery: 3 seconds after a change, unsaved designs are
    written to ~/.local/share/3dn00b/autosave; saving or closing normally removes
    the copy. Each window holds a lock on its backup (Qt's QLockFile; a lock whose
    program has died counts as gone), so only backups of a 3Dn00b that crashed are
    offered at the next start, newest first: Recover (it stays unsaved, with its
    file name if the file still exists) or Throw away. Older ones wait for the next
    start; damaged ones are never deleted unasked.
  - Own templates: "Save as my template…" under the template list saves the design
    as a project file in ~/.local/share/3dn00b/templates; they appear first in the
    list under "My templates", with "Rename or remove my templates…". A design
    started from one remembers it, so Box and Round container start over as with
    the built-in templates.
  - Measurements: a Sizes toggle in the 3D view (Ctrl+M, on by default, remembered):
    the outside width, depth (or diameter) and height, with the height with the lid
    on, as lines with labels on small dark tags; and for the selected hole, how far
    its middle is from the left edge and the bottom of its wall (from the left and
    the front on the bottom and the lid), in the selection colour. The numbers are
    drawn with QPainter, which QWidget.grab() leaves out, so the welcome tour's
    screenshots put the 3D view's own picture in.
- Follow-ups asked for after trying 0.28 (0.28.1): the size lines go along the sides
  that face the camera (front or back, left or right, worked out from the view's
  azimuth) and move when the view turns past a side; the height stands at the far
  end of the width line, beside the object. And a third text style, cut through:
  the letters go right through the surface (its thickness plus 0.1 mm, so nothing
  behind it is touched), with stencil bridges (1.2 mm, or a tenth of the letter
  height) up and down through every closed middle so O, A, B, 8, ø … keep it.
  Project format 16.
- More boards (0.29), the third group, each checked against the maker's own drawing:
  the Pico 2 and Pico 2 W datasheets show the Pico's board and holes, so the Pico board
  and template now name them (with a note about the W's antenna). The Uno R4 Minima and
  R4 WiFi datasheets show the Uno R3's holes; the R4's USB-C sits at 37.7 mm (the R3's
  USB B at 37.8) but lower, so the Uno case's USB opening now reaches 2 mm below the top
  of the board, and its jack at 7.8 mm is within the jack opening. The Giga R1 WiFi has
  the Mega's six holes (its sockets differ, so the Mega case says so). New: the Arduino
  Nano board (Nano, Nano Every and Nano ESP32 datasheets: 43.18 x 17.78 mm, holes 1.65 to
  1.8 mm, 40.64 x 15.24 apart) with M1.6 screws (new size; not offered for lids) and an
  Arduino Nano case (10 mm posts clear the header pins, 8.2 mm on the Nano drawing; the
  USB end has room for the mini USB's 1.9 mm). And a Raspberry Pi 5 case for the M.2 HAT+
  or AI HAT+ (product briefs: 16 mm spacers, the flat cable loops 5 mm past the SD card
  edge, at 21 to 39 mm, around the Pi 5's PCIe socket at 25 to 35 mm): 6 mm of room on
  that side, 38 mm tall inside, and an air vent over the HAT.
  Not done: the Raspberry Pi 500 is a keyboard computer, so it doesn't go in a box; the
  CM5 IO Board is a large development board with many sockets, not a beginner's board.
  The ESP32-S3 DevKit and the Orange Pi Zero need Espressif's and Orange Pi's drawings,
  whose websites this environment can't reach yet.
- Cable notches, fixing and heat-set inserts (0.30), the fourth group:
  - Cable notch: a new kind of opening on a wall (its width and depth), always at the
    top: its position is kept there after any change (and on loading), dragging only
    slides it along the wall, and its outline is open at the top and round at the
    bottom. A push-on or snap-on lid's lip gets the same notch (cut below the lid's
    flat top only), so the cable fits with the lid on; with a screwed-down lid the
    lid simply covers the notch. Sliding and screw-on lids refuse notches (they need
    the top of the wall), and the checks warn about a notch less deep than wide (a
    round cable would stick out) or running into the finger notch.
  - Fix it in place: screw tabs (two flat tabs at the left and right, at least 3 mm
    thick, 4 × the screw size wide, with the hole 6 mm out from the wall so a
    screwdriver fits past it) and keyhole slots in the back (a hole for the screw head,
    twice the screw size, and a slot above it, as far apart as fits or as asked; on a
    round container within 20° of the back, measured straight across like the screws
    in the wall). The checks say how far apart to put the screws, and warn about
    keyholes behind a divider or in thin walls. Screws: 3, 3.5, 4 or 5 mm.
  - Heat-set inserts: a switch per board and for screwed-down lids. Holes as the
    insert makers recommend (M2 3.2 × 4, M2.5 3.6 × 5, M3 4.0 × 6, M4 5.6 × 8.5 mm),
    in posts and columns made wide enough to leave 1.6 mm around the insert, with the
    screw's own hole continuing below for its tip. None for M1 and M1.6. The checks
    warn when posts or columns are too short, and give the screw length to use.
  Project format 17.
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

Picked by the project owner, in this order (each group once the one before works):

1. The ESP32-S3 DevKit and Orange Pi Zero 3, checked against Espressif's and Orange
   Pi's drawings (once their websites can be reached).
2. Packages for other systems (arm64 such as the Raspberry Pi, Flatpak or
   AppImage, Fedora).

Each addition must pass the brief's test: does it make a common beginner task
much easier, without CAD vocabulary, and without making the interface busier?

## Technical approach

| Area | Choice | Why |
| --- | --- | --- |
| Language | Python 3.10+ | Easy to read and to contribute to |
| GUI | PySide6 (Qt 6), LGPL | Native-looking Linux desktop app, installs from pip |
| 3D preview | pyqtgraph `GLViewWidget` with a custom soft-lit shader | Small, pure Python, works on integrated graphics (OpenGL 2-era shaders) |
| Geometry | **Manifold** (`manifold3d`), Apache-2.0 | Fast, robust Boolean operations whose results are **always watertight**. That is exactly what an STL needs. It is a small pip wheel with no system dependencies |
| Project files | Versioned JSON (`"format": "3dn00b-project", "version": 13`) | Human-readable, diffable, forward-compatible |

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
