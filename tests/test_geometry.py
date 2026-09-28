"""Geometry tests: build real badges in Blender and inspect the exported STLs.

Skipped automatically when run outside Blender (no ``bpy``).
"""

import itertools
import math
import struct
import tempfile
import unittest
from pathlib import Path

try:
    import bpy  # noqa: F401
except ImportError:
    bpy = None

from badge.config import from_dict
from tests.stl_check import read_stl

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
TOL = 0.05  # mm, acceptance tolerance for slicer-measured dimensions


@unittest.skipIf(bpy is None, "requires Blender (run via tests/run_tests.py)")
class GeometryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def build(self, **sections):
        """Build and export a badge; return (cfg, build)."""
        from badge import pipeline
        sections.setdefault("export", {})
        sections["export"] = {"out_dir": str(self.out), "render_preview": False,
                              **sections["export"]}
        cfg = from_dict(sections, ROOT)
        build = pipeline.build_geometry(cfg)
        pipeline.export_outputs(cfg, build)
        return cfg, build

    def assertPrintable(self, path: Path):
        info = read_stl(path)
        self.assertTrue(info.watertight, f"{path.name}: {info}")
        return info

    def assertDiameter(self, info, diameter: float):
        for axis in (0, 1):
            self.assertAlmostEqual(info.size[axis], diameter, delta=TOL)

    def test_edge_styles_with_and_without_ring(self):
        for style, ring in itertools.product(("flat", "chamfer", "dome"), (True, False)):
            with self.subTest(edge_style=style, ring=ring):
                cfg, build = self.build(badge={"edge_style": style},
                                        ring={"enabled": ring},
                                        emblem={"mode": "text"}, mounting={"style": "none"})
                info = self.assertPrintable(build.outputs["base"])
                self.assertDiameter(info, cfg.badge.diameter)
                self.assertAlmostEqual(info.min[2], 0.0, delta=1e-4)  # flat bottom on Z=0

    def test_diameter_change_rescales(self):
        for diameter in (60.0, 75.0, 130.0):
            with self.subTest(diameter=diameter):
                cfg, build = self.build(badge={"diameter": diameter}, mounting={"style": "none"})
                self.assertDiameter(self.assertPrintable(build.outputs["base"]), diameter)

    def test_base_volume_matches_profile(self):
        # Flat disc + rectangular ring: volume is easy to compute by hand.
        cfg, build = self.build(badge={"edge_style": "flat", "segments": 1024},
                                ring={"inner_bevel": 0.0}, mounting={"style": "none"})
        r, ri, t, h = cfg.radius, cfg.ring_inner_radius, 3.0, 1.2
        expected = math.pi * r * r * t + math.pi * (r * r - ri * ri) * h
        info = read_stl(build.outputs["base"])
        self.assertAlmostEqual(info.volume, expected, delta=expected * 0.001)

    # --- Milestone 3: SVG emblems -------------------------------------------

    def svg(self, name: str, **emblem):
        return self.build(emblem={"mode": "svg", "svg_path": str(FIXTURES / name), **emblem},
                          mounting={"style": "none"})

    def test_all_fixtures_build_printable_bodies(self):
        for name in ("star.svg", "ring_with_hole.svg", "multi_path.svg"):
            with self.subTest(fixture=name):
                cfg, build = self.svg(name)
                for label in ("full", "base", "emblem"):
                    self.assertPrintable(build.outputs[label])
                self.assertDiameter(read_stl(build.outputs["full"]), cfg.badge.diameter)

    def test_emblem_fits_inside_ring_at_any_rotation(self):
        for rotation, offset in ((0.0, 0.0), (45.0, 0.0), (17.0, 4.0)):
            with self.subTest(rotation=rotation, offset=offset):
                cfg, build = self.svg("multi_path.svg", rotation_deg=rotation, offset_x=offset)
                limit = cfg.ring_inner_radius - cfg.emblem.margin
                self.assertLessEqual(build.emblem_extent, limit + 1e-3)
                self.assertGreater(build.emblem_extent, limit - offset - 1e-3)

    def test_hole_is_respected(self):
        # Annulus fixture: outer r=45, inner r=25 in SVG units, so the fitted
        # emblem's area is pi * (R^2 - (R * 25/45)^2) and volume = area * relief.
        cfg, build = self.svg("ring_with_hole.svg")
        outer = cfg.emblem_max_radius
        area = math.pi * (outer ** 2 - (outer * 25 / 45) ** 2)
        info = read_stl(build.outputs["emblem"])
        self.assertAlmostEqual(info.volume, area * cfg.emblem.relief, delta=area * 0.01)

    def test_separate_paths_stay_separate(self):
        _, build = self.svg("multi_path.svg")
        self.assertEqual(islands(build.emblem), 3)

    def test_split_bodies_touch_but_do_not_overlap(self):
        _, build = self.svg("star.svg")
        vols = {k: read_stl(v).volume for k, v in build.outputs.items()}
        self.assertAlmostEqual(vols["base"] + vols["emblem"], vols["full"],
                               delta=vols["full"] * 1e-4)
        self.assertAlmostEqual(read_stl(build.outputs["emblem"]).min[2], 3.0, delta=1e-4)

    def test_svg_without_closed_paths_fails_clearly(self):
        from badge.emblem import EmblemError
        path = self.out / "open.svg"
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                        '<path d="M 1 1 L 9 9" stroke="#000" fill="none"/></svg>')
        with self.assertRaisesRegex(EmblemError, "closed"):
            self.build(emblem={"mode": "svg", "svg_path": str(path)})

    # --- Milestone 4: text emblems ------------------------------------------

    def text(self, text: str, **emblem):
        return self.build(emblem={"mode": "text", "text": text, **emblem},
                          mounting={"style": "none"})

    def test_text_builds_with_counters(self):
        # "R" has one enclosed counter and "B" two: 2 solids with 3 through-holes.
        cfg, build = self.text("RB")
        for label in ("full", "base", "emblem"):
            self.assertPrintable(build.outputs[label])
        self.assertEqual(islands(build.emblem), 2)
        self.assertEqual(genus(build.emblem), 3)
        self.assertLessEqual(build.emblem_extent, cfg.emblem_max_radius + 1e-3)

    def test_text_with_custom_font(self):
        font = Path(bpy.utils.system_resource("DATAFILES", path="fonts")) / "DejaVuSansMono.woff2"
        if not font.is_file():
            self.skipTest("bundled DejaVuSansMono font not found")
        _, default = self.text("A8")
        default_volume = read_stl(default.outputs["emblem"]).volume
        _, custom = self.text("A8", font_path=str(font))
        info = self.assertPrintable(custom.outputs["emblem"])
        self.assertEqual(genus(custom.emblem), 3)  # A: 1 counter, 8: 2 counters
        self.assertNotAlmostEqual(info.volume, default_volume, delta=1.0)

    def test_shapes_touching_at_a_point(self):
        # Regression: glyphs/shapes meeting at one corner used to extrude into a
        # non-manifold edge. "VW" over "TDI" touches in the built-in font.
        _, build = self.text("VW\nTDI")
        self.assertPrintable(build.outputs["full"])
        self.assertPrintable(build.outputs["emblem"])
        corner = self.out / "corner.svg"
        corner.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
                          '<rect x="0" y="0" width="10" height="10"/>'
                          '<rect x="10" y="10" width="10" height="10"/></svg>')
        _, build = self.build(emblem={"mode": "svg", "svg_path": str(corner)},
                              mounting={"style": "none"})
        self.assertPrintable(build.outputs["full"])
        self.assertEqual(islands(build.emblem), 2)

    def test_multiline_text(self):
        cfg, build = self.text("R\nB")
        self.assertPrintable(build.outputs["emblem"])
        self.assertLessEqual(build.emblem_extent, cfg.emblem_max_radius + 1e-3)

    # --- Milestone 5: mounting ----------------------------------------------

    def test_tape_recess(self):
        _, flat = self.build(mounting={"style": "none"})
        flat_volume = read_stl(flat.outputs["full"]).volume  # read before it's overwritten
        cfg, taped = self.build(mounting={"style": "tape", "recess_depth": 0.6,
                                          "recess_margin": 2.0})
        info = self.assertPrintable(taped.outputs["full"])
        self.assertAlmostEqual(info.min[2], 0.0, delta=1e-4)  # outer rim still sits on Z=0
        recess_r = cfg.radius - 2.0
        removed = flat_volume - info.volume
        expected = math.pi * recess_r ** 2 * 0.6
        self.assertAlmostEqual(removed, expected, delta=expected * 0.002)

    def test_pins(self):
        positions = [[-20.0, 0.0], [20.0, 0.0], [0.0, 30.0]]
        cfg, build = self.build(mounting={"style": "pins", "pin_diameter": 3.0,
                                          "pin_length": 6.0, "pin_positions": positions})
        for label in ("full", "base"):
            info = self.assertPrintable(build.outputs[label])
            self.assertAlmostEqual(info.min[2], -6.0, delta=1e-4)
            self.assertDiameter(info, cfg.badge.diameter)
        self.assertEqual(islands(build.base), 1)  # pins fused to the base
        self.assertEqual(len(bpy.data.objects), 3)  # pin cutters cleaned up

    def test_pin_at_disc_edge(self):
        cfg, build = self.build(mounting={"style": "pins", "pin_positions": [[36.0, 0.0]]})
        self.assertDiameter(self.assertPrintable(build.outputs["full"]), cfg.badge.diameter)

    # --- Milestone 6: split export + preview --------------------------------

    def test_output_selection(self):
        _, only_full = self.build(export={"split_bodies": False, "single_body": True})
        self.assertEqual(set(only_full.outputs), {"full"})
        _, only_split = self.build(export={"split_bodies": True, "single_body": False})
        self.assertEqual(set(only_split.outputs), {"base", "emblem"})

    def test_preview_is_two_views_side_by_side(self):
        from badge.export import PREVIEW_SIZE
        _, build = self.build(export={"render_preview": True})
        png = build.outputs["preview"].read_bytes()
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", png[16:24])
        self.assertEqual((width, height), (2 * PREVIEW_SIZE, PREVIEW_SIZE))
        self.assertEqual(sorted(p.name for p in self.out.glob("*.png")), ["badge_preview.png"])


def genus(obj) -> int:
    """Total number of through-holes across all closed components (Euler characteristic)."""
    mesh = obj.data
    chi = len(mesh.vertices) - len(mesh.edges) + len(mesh.polygons)
    return (2 * islands(obj) - chi) // 2


def islands(obj) -> int:
    """Number of connected mesh components."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    seen, count = set(), 0
    for start in bm.verts:
        if start.index in seen:
            continue
        count += 1
        stack = [start]
        while stack:
            v = stack.pop()
            if v.index in seen:
                continue
            seen.add(v.index)
            stack.extend(e.other_vert(v) for e in v.link_edges)
    bm.free()
    return count


if __name__ == "__main__":
    unittest.main()
