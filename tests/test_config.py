"""Config loading and validation. Pure Python: no Blender needed."""

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from badge.config import ConfigError, from_dict, load_config

ROOT = Path(__file__).resolve().parent.parent


def errors_for(data: dict) -> list[str]:
    try:
        from_dict(data, ROOT)
    except ConfigError as exc:
        return exc.errors
    return []


class ConfigTests(unittest.TestCase):
    def assertError(self, data: dict, fragment: str) -> None:
        errors = errors_for(data)
        self.assertTrue(any(fragment in e for e in errors),
                        f"expected an error containing {fragment!r}, got {errors}")

    def test_defaults_are_valid(self):
        cfg = load_config(None, ROOT)
        self.assertEqual(cfg.badge.diameter, 75.0)
        self.assertAlmostEqual(cfg.ring_inner_radius, 33.5)
        self.assertAlmostEqual(cfg.rim_height, 4.2)

    def test_shipped_configs_load(self):
        for path in sorted((ROOT / "configs").glob("*.toml")):
            with self.subTest(config=path.name):
                cfg = load_config(path, ROOT)
                self.assertEqual(cfg.source, path.resolve())

    def test_ints_accepted_for_floats(self):
        cfg = from_dict({"badge": {"diameter": 80}}, ROOT)
        self.assertIsInstance(cfg.badge.diameter, float)

    def test_diameter_change_rescales_derived_dimensions(self):
        cfg = from_dict({"badge": {"diameter": 100.0}}, ROOT)
        self.assertAlmostEqual(cfg.ring_inner_radius, 50 - 4.0)
        self.assertAlmostEqual(cfg.emblem_max_radius, 50 - 4.0 - 3.0)

    def test_unknown_key_suggests_fix(self):
        self.assertError({"badge": {"diamter": 75.0}}, "did you mean 'diameter'")
        self.assertError({"rings": {}}, "did you mean 'ring'")

    def test_wrong_type(self):
        self.assertError({"badge": {"diameter": "75"}}, "badge.diameter: expected a number")
        self.assertError({"ring": {"enabled": 1}}, "ring.enabled: expected true or false")

    def test_emblem_margin_too_large(self):
        self.assertError({"emblem": {"margin": 32.0}}, "emblem does not fit")

    def test_emblem_offset_pushes_outside_ring(self):
        self.assertError({"emblem": {"offset_x": 30.0}}, "emblem does not fit")

    def test_recess_deeper_than_base(self):
        self.assertError({"mounting": {"recess_depth": 3.0}}, "recess_depth")

    def test_pin_outside_disc(self):
        self.assertError({"mounting": {"style": "pins", "pin_positions": [[37.0, 0.0]]}},
                         "outside the disc")

    def test_pins_ignored_for_tape(self):
        self.assertEqual(errors_for({"mounting": {"pin_positions": [[99.0, 0.0]]}}), [])

    def test_malformed_pin_positions(self):
        self.assertError({"mounting": {"pin_positions": [[1.0]]}}, "[x, y] pairs")

    def test_missing_svg(self):
        self.assertError({"emblem": {"mode": "svg", "svg_path": "nope.svg"}}, "not found")
        self.assertError({"emblem": {"mode": "svg"}}, "svg_path is required")

    def test_ring_wider_than_disc(self):
        self.assertError({"ring": {"width": 40.0}}, "no inner opening")

    def test_chamfer_taller_than_rim(self):
        self.assertError({"badge": {"edge_size": 4.5}}, "rim height")
        self.assertError({"badge": {"edge_size": 3.5}, "ring": {"enabled": False}}, "rim height")

    def test_chamfer_and_bevel_must_leave_ring_top(self):
        self.assertError({"badge": {"edge_size": 3.8}}, "flat ring top")

    def test_all_errors_reported_together(self):
        errors = errors_for({"badge": {"diameter": -1.0}, "emblem": {"relief": 0.0}})
        self.assertGreaterEqual(len(errors), 2)

    def test_missing_and_invalid_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.toml"
            bad.write_text("[badge\n")
            for path, fragment in ((bad, "invalid TOML"), (Path(tmp) / "x.toml", "not found")):
                with self.subTest(path=path.name), self.assertRaises(ConfigError) as ctx:
                    load_config(path, ROOT)
                self.assertIn(fragment, str(ctx.exception))

    def test_fixtures_are_wellformed_svg(self):
        for path in sorted((ROOT / "tests" / "fixtures").glob("*.svg")):
            with self.subTest(fixture=path.name):
                self.assertTrue(ET.parse(path).getroot().tag.endswith("svg"))


if __name__ == "__main__":
    unittest.main()
