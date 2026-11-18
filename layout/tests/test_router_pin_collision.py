"""Router pin-collision guard (issue #406). Stdlib only; no PDK, no KLayout.

Run from the repo root:
    python3 -I -m unittest layout.tests.test_router_pin_collision -v
or: python3 -I -m unittest discover -s layout/tests -p 'test_router_pin_collision.py'
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

LAYOUT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAYOUT))
_spec = importlib.util.spec_from_file_location(
    "lna_core_generate_router_test", LAYOUT / "lna_core" / "generate.py"
)
generate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate)


class _Canvas:
    """Records draw calls so a test can assert nothing was drawn."""

    def __init__(self):
        self.calls = 0

    def box(self, *a, **k):
        self.calls += 1

    def pcell(self, *a, **k):
        self.calls += 1


def _router(pins):
    cv = _Canvas()
    rt = generate.Router(cv, -10.0)
    for net, x in pins:
        rt.pin(net, x, 0.0)
    return cv, rt


class RouterPinCollision(unittest.TestCase):
    def test_different_nets_colliding_raise_before_drawing(self):
        cv, rt = _router([("a", 1.0), ("a", 5.0), ("b", 1.3), ("b", 6.0)])
        with self.assertRaises(SystemExit) as cm:
            rt.route()
        msg = str(cm.exception)
        self.assertIn("a", msg)
        self.assertIn("b", msg)
        self.assertIn("1", msg)
        self.assertEqual(cv.calls, 0)

    def test_exactly_touching_pitch_is_rejected(self):
        # 0.4 um: stub boxes share an edge; klt extract merges them (#412).
        _, rt = _router([("a", 1.0), ("a", 5.0), ("b", 1.4), ("b", 6.0)])
        with self.assertRaises(SystemExit):
            rt.check_pin_collisions()

    def test_below_metal2_space_margin_raises(self):
        _, rt = _router([("a", 1.0), ("a", 5.0), ("b", 1.6), ("b", 6.0)])  # 0.6 < 0.61
        with self.assertRaises(SystemExit):
            rt.check_pin_collisions()

    def test_at_metal2_space_margin_is_legal(self):
        _, rt = _router([("a", 1.0), ("a", 5.0), ("b", 1.62), ("b", 6.0)])
        rt.check_pin_collisions()

    def test_just_inside_pitch_raises(self):
        _, rt = _router([("a", 1.0), ("a", 5.0), ("b", 1.39), ("b", 6.0)])
        with self.assertRaises(SystemExit):
            rt.check_pin_collisions()

    def test_same_net_shared_x_is_legal(self):
        _, rt = _router([("a", 1.0), ("a", 1.0), ("b", 3.0), ("b", 4.0)])
        rt.route()

    def test_same_net_pin_between_does_not_mask_collision(self):
        _, rt = _router([("a", 1.0), ("a", 1.1), ("b", 1.2), ("b", 9.0)])
        with self.assertRaises(SystemExit):
            rt.check_pin_collisions()

    def test_single_pin_net_still_rejected(self):
        _, rt = _router([("a", 1.0)])
        with self.assertRaises(SystemExit) as cm:
            rt.route()
        self.assertIn("single pin", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
