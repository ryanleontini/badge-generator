"""Geometry tests: build real badges in Blender and inspect the exported STLs.

Skipped automatically when run outside Blender (no ``bpy``).
"""

import itertools
import math
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


if __name__ == "__main__":
    unittest.main()
