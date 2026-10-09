"""Unit tests for layout/lvs_reference.py (issue #109).

Pins the scope-partition check, the m>1 rejection and the per-class card
rewrites. Stdlib only: no klayout, klt, PDK or ngspice. Fixtures are tiny
inline netlists / realization.json files written to a temp repo root and fed
through build(cell_dir, repo=...).

Run from the repo root:
    python3 -I -m unittest discover -s layout/tests -v
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lvs_reference  # noqa: E402

NETLIST = """\
* test netlist
XQ1 c b e s npn13G2 Nx=2
XM1 d g s bb sg13_hv_pmos w=1.005u l=0.45u ng=1 m=1
R1 a b 330 m=1
C1 a c 100p m=1
.end
"""

SPEC = {
    "XQ1": {"pcell": "npn13G2"},
    "XM1": {"pcell": "pmosHV"},
    "R1": {"pcell": "rppd", "params": {"l": "2u", "w": "0.5u"}},
    "C1": {"pcell": "cmim"},
}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        self.cell = self.repo / "cellx"
        self.cell.mkdir()

    def run_build(self, netlist=NETLIST, in_scope=None, out_of_scope=(), spec=None):
        (self.repo / "n.spice").write_text(netlist)
        names = list(SPEC) if in_scope is None else in_scope
        spec = spec or SPEC
        rz = {
            "top_cell": "top",
            "netlist": "n.spice",
            "in_scope": {k: spec[k] for k in names},
            "out_of_scope": list(out_of_scope),
        }
        (self.cell / "realization.json").write_text(json.dumps(rz))
        out = lvs_reference.build(self.cell, repo=self.repo)
        return out.read_text().splitlines()


class TestCards(Base):
    def test_minimal_cell_cards(self):
        lines = self.run_build()
        sha = hashlib.sha256(NETLIST.encode()).hexdigest()
        self.assertEqual(lines[1], f"* source: n.spice sha256:{sha}")
        self.assertEqual(
            lines[5:],
            [
                "QQ1 c b e s npn13G2 NE=2",
                "MM1 d g s bb pfet L=0.45U W=1.005U",
                "RR1 a b 330 rppd L=2U W=0.5U",
                "CC1 a c 100P cap_cmim",
                ".END",
            ],
        )

    def test_nmos_class_and_letter_prefix(self):
        nl = "XM2 d g s b sg13_hv_nmos w=2u l=0.5u m=1\nR1 a b 1k\n"
        lines = self.run_build(nl, ["XM2", "R1"], spec=SPEC | {"XM2": {"pcell": "nmosHV"}})
        self.assertEqual(lines[5], "MM2 d g s b nfet L=0.5U W=2U")
        self.assertTrue(lines[6].startswith("RR1 a b 1k rppd"))

    def test_nx_defaults_to_one(self):
        lines = self.run_build("XQ1 c b e s npn13G2\n", ["XQ1"])
        self.assertEqual(lines[5], "QQ1 c b e s npn13G2 NE=1")

    def test_non_u_length_rejected(self):
        nl = "XM1 d g s b sg13_hv_pmos w=1m l=0.45u\n"
        with self.assertRaises(SystemExit):
            self.run_build(nl, ["XM1"])

    def test_duplicate_instance_rejected(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_build(NETLIST + "R1 x y 1k\n")
        self.assertIn("duplicate", str(cm.exception))


class TestPartition(Base):
    def test_name_in_both_rejected(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_build(out_of_scope=["R1"])
        self.assertIn("in both=['R1']", str(cm.exception))

    def test_unassigned_instance_rejected(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_build(NETLIST + "R9 p q 1k\n")
        self.assertIn("unassigned=['R9']", str(cm.exception))

    def test_stale_name_rejected(self):
        spec = SPEC | {"R7": {"pcell": "rppd", "params": {"l": "1u", "w": "1u"}}}
        with self.assertRaises(SystemExit) as cm:
            self.run_build(in_scope=list(SPEC) + ["R7"], spec=spec)
        self.assertIn("not-in-netlist=['R7']", str(cm.exception))

    def test_stale_out_of_scope_rejected(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_build(out_of_scope=["Rgone"])
        self.assertIn("not-in-netlist=['Rgone']", str(cm.exception))

    def test_out_of_scope_instance_omitted(self):
        lines = self.run_build(in_scope=["XQ1", "XM1", "C1"], out_of_scope=["R1"])
        self.assertFalse(any(l.startswith("RR1") for l in lines))


class TestMos(Base):
    def test_m_gt_1_rejected(self):
        nl = "XM1 d g s b sg13_hv_pmos w=1u l=0.45u ng=1 m=2\n"
        with self.assertRaises(SystemExit) as cm:
            self.run_build(nl, ["XM1"])
        self.assertIn("m>1", str(cm.exception))


class TestOrdering(Base):
    def test_netlist_order_not_realization_order(self):
        lines = self.run_build(in_scope=list(reversed(list(SPEC))))
        names = [l.split()[0] for l in lines[5:-1]]
        self.assertEqual(names, ["QQ1", "MM1", "RR1", "CC1"])
        # (letter is prepended after the X is stripped: XQ1 -> QQ1, R1 -> RR1)
        # the scope header echoes realization order, proving the input was reversed
        self.assertIn("in_scope: C1, R1, XM1, XQ1", lines[2])


if __name__ == "__main__":
    unittest.main()
