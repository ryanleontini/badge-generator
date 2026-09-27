# Parametric Car Badge Generator

A headless Blender tool that turns an SVG or a text string into a 3D-printable circular car badge. Every dimension comes from a TOML config, so one tool produces both the front (grille) and rear (trunk) badges.

> **Status:** Milestone 1 (skeleton) is done. Config loading, validation and the headless scene setup work. Geometry generation is still in progress.

## Requirements

- Blender 4.2 LTS or newer (developed on 5.2.2). No other dependencies: the tool runs on Blender's bundled Python.
- `make` (optional)

```bash
brew install --cask blender   # macOS
```

## Usage

```bash
blender -b -P badge_gen.py -- --config configs/front.toml
blender -b -P badge_gen.py -- --config configs/front.toml --check   # validate only
```

| Make target | What it does |
|---|---|
| `make front` / `make rear` / `make text` | Build a badge from the matching config |
| `make test` | Unit tests plus headless smoke runs of every config |
| `make clean` | Remove `out/` |

Exit codes: `0` success, `1` unexpected error, `2` invalid config. Validation reports every problem at once, before any geometry is built.

## Configuration

See [configs/front.toml](configs/front.toml) for every key. Keys left out of a config fall back to the defaults in [badge/config.py](badge/config.py). All dimensions are in millimeters. Relative paths (`svg_path`, `font_path`, `out_dir`) resolve against the repo root.
