"""Phase H part B: the security suite (tests/security) runs as part of `python3 -m unittest discover -s tests`.

`discover -s tests` does not enter tests/security (it has no __init__.py, and its manifest tests name modules such as
test_threats). This module loads that folder with its own loader, so the modules keep their manifest names, and hands the
tests to the outer run. `python3 -m unittest discover -s tests/security` still works on its own.
"""
import sys
import unittest
from pathlib import Path

SECURITY = Path(__file__).resolve().parent / "security"


def load_tests(loader, tests, pattern):
    if str(SECURITY) not in sys.path:
        sys.path.insert(0, str(SECURITY))
    suite = unittest.TestSuite()
    suite.addTests(unittest.TestLoader().discover(str(SECURITY), top_level_dir=str(SECURITY)))
    return suite
