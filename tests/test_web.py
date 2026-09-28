"""Web UI server helpers. Pure Python: no Blender or network needed."""

import importlib.util
import tomllib
import unittest
from pathlib import Path

from badge.config import from_dict, load_config

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("web_server", ROOT / "web" / "server.py")
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


class WebServerTests(unittest.TestCase):
    def test_presets_include_defaults_and_shipped_configs(self):
        presets = server.presets()
        self.assertIn("defaults", presets)
        for path in (ROOT / "configs").glob("*.toml"):
            self.assertIn(path.stem, presets)

    def test_toml_round_trip(self):
        for name, sections in server.presets().items():
            with self.subTest(preset=name):
                text = server.to_toml(sections)
                self.assertEqual(tomllib.loads(text), _jsonish(sections))
                from_dict(tomllib.loads(text), ROOT)  # still a valid config

    def test_toml_escapes_strings(self):
        text = server.to_toml({"emblem": {"text": 'A "B"\nC\\D'}})
        self.assertEqual(tomllib.loads(text)["emblem"]["text"], 'A "B"\nC\\D')

    def test_validate_reports_config_errors(self):
        self.assertEqual(server.validate({}), [])
        errors = server.validate({"badge": {"diameter": 10.0}})
        self.assertTrue(any("does not fit" in e for e in errors))

    def test_upload_rejects_non_svg(self):
        with self.assertRaisesRegex(ValueError, "not an SVG"):
            server.save_upload({"name": "x.png", "data": "aGVsbG8="})


def _jsonish(sections: dict) -> dict:
    """Tuples become lists after a TOML round trip."""
    return {k: {kk: [list(p) for p in vv] if kk == "pin_positions" else vv
                for kk, vv in v.items()} for k, v in sections.items()}


if __name__ == "__main__":
    unittest.main()
