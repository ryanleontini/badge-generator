# Parametric Car Badge Generator (Blender + Python)

## Goal

Build a command-line tool that generates a 3D-printable, flat circular car badge in Blender from either an SVG file or a text string. Everything is parameter-driven so the same tool produces the front (grille) and rear (tailgate) badges for a 2012 VW Jetta SportWagen TDI, sized to replace OEM emblems (part numbers 5C6853601 front and 1K9853630A rear, rear measured at 75 mm; front ~130 mm per retailer listings, unverified).

The tool must run headless:

```
blender -b -P badge_gen.py -- --config configs/front.toml
```

Output: print-ready STL files (single body, or split bodies for two-color printing) plus a preview render.

## Context for Claude Code

- The user is an engineer building a portfolio. Code quality, a clear README, and reproducibility matter as much as the output.
- The user will supply their own SVG artwork or use text/monogram mode. Do not source, download, or recreate any third-party logos or trademarks. Test fixtures must be simple original shapes (circle, star, generic geometric emblem) generated or hand-written in the repo.
- Target Blender 4.2 LTS or newer. Detect the version at runtime and branch where APIs differ (e.g., STL export operator, boolean solver options).
- Work in millimeters: set scene unit system to METRIC with scale_length = 0.001 so 1 Blender unit = 1 mm.

## Repo Structure

```
badge-generator/
  badge_gen.py            # entry point: arg parsing, orchestration
  badge/
    __init__.py
    config.py             # load + validate TOML, defaults, dataclass
    scene.py              # reset scene, units, collections
    compat.py             # Blender version checks, STL exporter branch
    mesh.py               # bmesh helpers: revolve profile, extrude, object I/O
    base.py               # disc + edge + ring + recess as one lathe profile
    ring.py               # ring section of the base profile
    emblem.py             # SVG import / text mode -> fitted, extruded mesh
    mounting.py           # tape recess profile, pin geometry
    booleans.py           # union/difference helpers, cleanup, manifold check
    export.py             # STL export, preview render
    pipeline.py           # build orchestration + summary report
  configs/
    front.toml
    rear.toml
    example_text.toml
  tests/
    run_tests.py          # unittest runner inside Blender
    test_config.py        # pure-Python config tests
    test_geometry.py      # builds badges in Blender, inspects exported STLs
    stl_check.py          # independent binary-STL checker (watertight, size, volume)
    fixtures/
      star.svg              # original simple shape
      ring_with_hole.svg    # tests holes/counters in paths
      multi_path.svg        # tests multiple separate paths
  docs/images/            # README screenshots (make docs)
  out/                    # generated files (gitignored)
  README.md
  LICENSE                 # MIT
  Makefile                # make all / front / rear / text / test / check / docs
```

## Configuration (TOML)

All dimensions in mm. Provide sane defaults in `config.py`; configs override.

```toml
[badge]
name = "front"
diameter = 75.0
base_thickness = 3.0
edge_style = "chamfer"      # "flat" | "chamfer" | "dome"
edge_size = 0.8             # chamfer size or dome rise
segments = 256              # circle resolution

[ring]
enabled = true
width = 4.0
height = 1.2                # above base top face
inner_bevel = 0.4

[emblem]
mode = "svg"                # "svg" | "text"
svg_path = "art/my_emblem.svg"
text = "RB"
font_path = ""              # empty = Blender default font
relief = 1.2                # height above base top face
margin = 3.0                # clearance from ring inner edge
rotation_deg = 0.0
offset_x = 0.0
offset_y = 0.0

[mounting]
style = "tape"              # "tape" | "pins" | "none"
recess_depth = 0.6          # for tape: VHB 5952 is ~1.1 mm; recess partially
recess_margin = 2.0
pin_diameter = 3.0          # placeholders until OEM badge is measured
pin_length = 6.0
pin_positions = [[-20.0, 0.0], [20.0, 0.0]]

[export]
split_bodies = true         # base+ring and emblem as separate STLs
single_body = true          # also export merged STL
render_preview = true
out_dir = "out"
```

`config.py` validates: emblem fits inside ring (after margin), recess depth < base thickness, pins land inside the disc, relief > 0. Fail with clear messages.

## Pipeline

### 1. Scene setup (`scene.py`)
- Remove all objects, meshes, curves, materials (factory-fresh state).
- Set metric units, mm scale.
- Create collections: `Base`, `Emblem`, `Mounting`.

### 2. Base disc (`base.py`)
- Built as ONE revolved (r, z) profile with `segments` verts per ring, radius = diameter/2, bottom face at Z=0 (see `mesh.revolve`).
- Edge treatment:
  - `chamfer`: a 45° step in the profile at the rim's outer top edge.
  - `dome`: the field (inside the ring, or the whole top without a ring) rises as a paraboloid to `edge_size` at the center. The bottom stays perfectly flat.
- Prefer building geometry with bmesh over `bpy.ops` where practical (more reliable headless, no context issues).

### 3. Ring (`ring.py`)
- Decided: the ring is flush with the disc's outer edge (matches OEM: flat back, no lip wrapping the edge, ring at the rim). The edge chamfer/dome runs from the outer wall up to the ring top as one continuous bevel, so there is no overhang or gap under the ring.
- When the ring is enabled, build base + ring as ONE lathe/spin of a 2D profile: flat bottom -> outer wall -> edge chamfer -> ring top -> inner bevel -> base top face -> axis. Manifold by construction, no base/ring boolean. Inner radius = disc radius minus width.
- When the ring is disabled, the edge treatment sits on the base's top outer edge as in step 2.

### 4. Emblem (`emblem.py`)
SVG mode:
- Ensure the SVG importer add-on is enabled (use `addon_utils.enable("io_curve_svg")`; handle it already being enabled or being unavailable, with a clear error).
- Record existing objects, run `bpy.ops.import_curve.svg(filepath=...)`, diff to find new curve objects.
- Join all imported curves into one curve object.
- Set `curve.dimensions = '2D'`, `fill_mode = 'BOTH'` so holes (counters) are respected.
- Tessellate the filled curve to a flat mesh (via depsgraph), then normalize: center the bounding box at the origin and uniformly scale so the farthest vertex lies on a circle of radius `ring_inner_radius - margin - |offset|` (bounding circle, not box, so rotation can never hit the ring). SVG import units are unreliable (DPI assumptions), so never trust raw scale.
- Apply rotation and offsets.
- Extrude with bmesh from 0.05 mm below the base top face to `relief` above the field's highest point.

Text mode:
- Create a text object with the given string/font, same fit-to-circle logic, extrude, convert to mesh.

### 5. Mounting (`mounting.py`)
- `tape`: a step in the base's lathe profile (no boolean), radius = disc radius - recess_margin, depth = recess_depth.
- `pins`: union small cylinders on the bottom at `pin_positions`, optional small chamfer at tips.
- `none`: skip.

### 6. Booleans and cleanup (`booleans.py`)
- Union pins into the base/ring body.
- Full body = base UNION emblem. Split emblem = emblem DIFFERENCE base, so split parts touch without overlapping.
- Modifiers are applied via `bpy.data.meshes.new_from_object(evaluated)` rather than `bpy.ops`, avoiding context issues headless.
- Solver: use `MANIFOLD` if available (Blender 4.5+), otherwise `EXACT`. Detect via enum items on the modifier.
- Apply modifiers, then cleanup: merge by distance (0.001 mm), recalc normals outward, delete loose geometry.
- Manifold check: use bmesh to count non-manifold edges; log the result and fail the run (non-zero exit) if any exist.

### 7. Export (`export.py`)
- Blender 4.1+: `bpy.ops.wm.stl_export` with `export_selected_objects=True`, `apply_modifiers=True`, `global_scale` so output is mm. Older: fall back to `bpy.ops.export_mesh.stl`.
- Outputs:
  - `out/<name>_full.stl` (merged)
  - `out/<name>_base.stl`, `out/<name>_emblem.stl` (split, positioned in the same coordinate frame so they align in a slicer)
  - `out/<name>_preview.png`: Workbench or EEVEE render, orthographic top-down plus an angled 3/4 view.
- Print a summary: dimensions, triangle counts, manifold status, output paths.

## Milestones

Each milestone should end with something runnable and committed.

1. **Skeleton.** Repo structure, config loading with defaults and validation, headless run that clears the scene and exits cleanly. `make test` runs Blender headless with a default config.
2. **Base + ring.** Disc with chamfer/dome and raised ring, exported as STL. Verify dimensions in a slicer (user will do a cheap test print for fit here).
3. **Emblem from SVG.** Import, fit-to-circle, extrude, union. Must pass on all three test fixtures, including the one with holes.
4. **Text mode.** Monogram/text emblems through the same fit logic.
5. **Mounting.** Tape recess and pin options. Pin values stay as placeholders until the user measures the OEM badges.
6. **Split export + previews.** Two-color-ready split STLs and preview renders.
7. **Polish.** README with install/usage/screenshots, parameter reference table, known limitations. Makefile targets for front and rear.

## Acceptance Criteria

- `blender -b -P badge_gen.py -- --config configs/front.toml` produces all outputs with exit code 0 and no Python tracebacks.
- Exported STLs are manifold (zero non-manifold edges) and open cleanly in PrusaSlicer/OrcaSlicer/Bambu Studio.
- Measured diameter in the slicer matches config within 0.05 mm.
- Emblem never intersects the ring; validation errors trigger before geometry is built.
- Changing only `diameter` in the config regenerates a correctly proportioned badge.

## Open Items for the User

- Measure both OEM badges with calipers: outer diameter, total thickness, face curvature, mounting method (clips/pins vs. adhesive), and pin/clip positions if present.
- Check whether either badge on this trim covers a camera or sensor.
- Provide the final emblem artwork as an SVG with closed paths (or use text mode).
- Material plan: ASA print, filler primer, paint, 2K clear, 3M VHB 5952 for adhesive mounting.