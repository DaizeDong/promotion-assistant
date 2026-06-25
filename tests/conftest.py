"""Pytest path setup so `from scripts import ...` resolves the skill engine.

The engine lives at skills/promotion-assistant/scripts (a `scripts` package). Putting
skills/promotion-assistant on sys.path mirrors selftest.py's own bootstrap.
"""
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_PKG = _ROOT / "skills" / "promotion-assistant"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))
