"""Run the unit tests inside Blender's Python: blender -b -P tests/run_tests.py"""

import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent))

result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(TESTS)))
sys.exit(0 if result.wasSuccessful() else 1)
