"""Top-level-assembly invariants (issue #228). Stdlib only; no PDK, no
KLayout -- generate.py and item2_envelope.py import clean without pya.

Run from the repo root:
    python3 -I -m unittest layout.tests.test_assembly -v

Covers the three things the assembly could get silently wrong:

* the port list: realization.json's ``ports.list`` must be exactly the
  netlist's ``*.iopin`` ports, so a renamed or added port fails here (and
  generate.py itself fails the same way at draw time);
* the partition: every netlist instance in exactly one of in_scope /
  modeled_in_device / out_of_scope, and out_of_scope empty (full scope --
  the precondition for the item-2 citation);
* the channel geometry: TopMetal2 spine spacing (2*stub_half + 2.0 um) and
  the landing-guard window covering the measured via-stack pads.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

LAYOUT = Path(__file__).resolve().parent.parent
REPO = LAYOUT.parent
sys.path.insert(0, str(LAYOUT))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


generate = _load("lna_core_generate_assembly_test", LAYOUT / "lna_core" / "generate.py")
item2 = _load("lna_core_item2_envelope_test", LAYOUT / "item2_envelope.py")


def _rz() -> dict:
    return json.loads((LAYOUT / "lna_core" / "realization.json").read_text())


class _Canvas:
    def __init__(self):
        self.calls = 0

    def box(self, *a, **k):
        self.calls += 1

    def pcell(self, *a, **k):
        self.calls += 1


class Ports(unittest.TestCase):
    def test_realization_ports_are_the_netlist_iopins(self):
        netlist = REPO / _rz()["netlist"]
        self.assertEqual(
            generate._netlist_ports(netlist), ["vdd", "vss", "rfin", "rfout"]
        )
        self.assertEqual(_rz()["ports"]["list"], ["vdd", "vss", "rfin", "rfout"])


class Partition(unittest.TestCase):
    def test_partition_is_exact_and_scope_is_full(self):
        rz = _rz()
        cards = generate.parse_netlist(REPO / rz["netlist"])
        ins, mod, outs = (
            set(rz["in_scope"]),
            set(rz.get("modeled_in_device", {})),
            set(rz["out_of_scope"]),
        )
        self.assertEqual(ins & mod, set())
        self.assertEqual(ins & outs, set())
        self.assertEqual(mod & outs, set())
        self.assertEqual(set(cards) - ins - mod - outs, set())
        self.assertEqual((ins | mod | outs) - set(cards), set())
        # full scope: the item-2 / item-3 / item-4 scope guard's precondition
        self.assertEqual(outs, set())

    def test_modeled_entries_name_their_device_and_reason(self):
        for name, entry in _rz()["modeled_in_device"].items():
            self.assertIn(entry["of"], _rz()["in_scope"], f"{name}: loss of an undrawn device")
            self.assertIn(entry["topology"], ("series", "parallel"))
            self.assertTrue(entry["reason"].strip(), f"{name}: no reason recorded")


class AssemblyChannel(unittest.TestCase):
    """The Router instance draw_assembly builds (TopMetal2 spines over
    TopMetal1 trunks), on a recording canvas like the bias-channel tests."""

    def _router(self, pins):
        cv = _Canvas()
        rt = generate.Router(
            cv,
            -440.0,
            pitch=8.0,
            stub_ld=generate.TOPMETAL2,
            trunk_ld=generate.TOPMETAL1,
            stub_half=2.0,
            trunk_half=2.0,
            min_space=generate.TOPMETAL2_MIN_SPACE,
        )
        for net, x in pins:
            rt.pin(net, x, 0.0)
        return cv, rt

    def test_spines_closer_than_topmetal2_pitch_raise(self):
        cv, rt = self._router([("a", 0.0), ("a", 50.0), ("b", 5.9), ("b", 60.0)])
        with self.assertRaises(SystemExit) as cm:
            rt.route()
        self.assertEqual(cv.calls, 0)
        self.assertIn("collide", str(cm.exception))

    def test_spines_at_topmetal2_pitch_are_legal(self):
        _, rt = self._router([("a", 0.0), ("a", 50.0), ("b", 6.0), ("b", 60.0)])
        rt.route()

    def test_same_net_spines_may_share_x(self):
        _, rt = self._router([("a", 1.0), ("a", 1.0), ("b", 40.0), ("b", 60.0)])
        rt.route()

    def test_two_terminal_net_is_routed_not_rejected(self):
        _, rt = self._router([("a", 0.0), ("a", 50.0)])
        rt.route()

    def test_single_pin_net_still_rejected(self):
        _, rt = self._router([("a", 0.0)])
        with self.assertRaises(SystemExit):
            rt.route()

    def test_landing_guard_window_covers_measured_via_pads(self):
        # 2x2 via_stack pads measured +-1.93 um on TopMetal1/TopMetal2
        self.assertGreaterEqual(generate._LANDING_HALF, 1.93)
        # every assembly landing bottom layer sits below TopMetal2 in the chain
        chain = generate._STACK_CHAIN
        self.assertEqual(chain[0], "Metal1")
        self.assertEqual(chain[-1], "TopMetal2")
        for ld in ("Metal1", "Metal2", "Metal3", "Metal5", "TopMetal1"):
            self.assertLess(chain.index(ld), chain.index("TopMetal2"))


class Item2Envelope(unittest.TestCase):
    """item2_envelope.py derives its pass from the committed bytes."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        cell = self.tmp / "layout" / "lna_core"
        cell.mkdir(parents=True)
        for name in ("lna_core.gds", "lna_core.provenance.json", "realization.json"):
            shutil.copy(LAYOUT / "lna_core" / name, cell / name)
        self.cell = cell

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_envelope_pins_the_committed_gds(self):
        self.assertEqual(item2.main(["item2_envelope.py", str(self.tmp)]), 0)
        env = json.loads((self.cell / "item2.envelope.json").read_text())
        gds_sha = hashlib.sha256((self.cell / "lna_core.gds").read_bytes()).hexdigest()
        self.assertEqual(env["kind"], "generic")
        self.assertEqual(env["t1_item"], 2)
        self.assertEqual(env["status"], "pass")
        self.assertEqual(env["provenance"]["input"]["role"], "layout")
        self.assertEqual(env["provenance"]["input"]["content_hash"], f"sha256:{gds_sha}")
        self.assertEqual(
            env["provenance"]["regeneration"]["regenerated_hash"], f"sha256:{gds_sha}"
        )

    def test_stale_provenance_refuses_and_writes_nothing(self):
        prov = json.loads((self.cell / "lna_core.provenance.json").read_text())
        prov["gds_sha256"] = "0" * 64
        (self.cell / "lna_core.provenance.json").write_text(json.dumps(prov))
        self.assertEqual(item2.main(["item2_envelope.py", str(self.tmp)]), 1)
        self.assertFalse((self.cell / "item2.envelope.json").exists())

    def test_partial_scope_refuses_and_writes_nothing(self):
        rz = json.loads((self.cell / "realization.json").read_text())
        rz["out_of_scope"] = {"XSomething": {"reason": "test"}}
        (self.cell / "realization.json").write_text(json.dumps(rz))
        self.assertEqual(item2.main(["item2_envelope.py", str(self.tmp)]), 1)
        self.assertFalse((self.cell / "item2.envelope.json").exists())


if __name__ == "__main__":
    unittest.main()
