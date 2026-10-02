"""Unit tests: physics sanity checks against textbook values + end-to-end runs.

Run:  python -m pytest tests     (or)    python -m unittest discover tests
"""
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from emc_analyzer import AnalysisEngine  # noqa: E402
from emc_analyzer.analysis.filters import insertion_loss_db  # noqa: E402
from emc_analyzer.analysis.shielding import aperture_se, solid_wall_se, total_se  # noqa: E402
from emc_analyzer.analysis.spectrum import trapezoid_harmonics  # noqa: E402
from emc_analyzer.core.models import (Aperture, Enclosure, Filter, FilterElement, NoiseSource,  # noqa: E402
                                      Product)
from emc_analyzer.core.units import parse_si  # noqa: E402
from emc_analyzer.importers import import_design  # noqa: E402
from emc_analyzer.report import export_csv, export_html  # noqa: E402
from emc_analyzer.standards import StandardsLibrary  # noqa: E402

EX = ROOT / "examples"


class Units(unittest.TestCase):
    def test_parse_si(self):
        self.assertAlmostEqual(parse_si("100k"), 1e5)
        self.assertAlmostEqual(parse_si("2.2u"), 2.2e-6)
        self.assertAlmostEqual(parse_si("10MHz"), 10e6)
        self.assertAlmostEqual(parse_si("3m"), 3e-3)
        self.assertAlmostEqual(parse_si("1.5G"), 1.5e9)
        self.assertAlmostEqual(parse_si(42), 42.0)


class Standards(unittest.TestCase):
    def setUp(self):
        self.lib = StandardsLibrary()

    def test_loaded(self):
        self.assertFalse(self.lib.errors, self.lib.errors)
        self.assertIn("CISPR32_B_RE", self.lib.standards)

    def test_log_interpolation(self):
        s = self.lib.get("CISPR32_B_CE_QP")
        lv = s.level([150e3, 500e3, 1e6, 10e6, 40e6])
        self.assertAlmostEqual(lv[0], 66)
        self.assertAlmostEqual(lv[1], 56)
        self.assertAlmostEqual(lv[2], 56)
        self.assertAlmostEqual(lv[3], 60)
        self.assertTrue(np.isnan(lv[4]))

    def test_distance_correction(self):
        s = self.lib.get("CISPR32_B_RE")      # 10 m limit
        self.assertAlmostEqual(float(s.level([100e6], distance_m=3)[0]), 30 + 20 * math.log10(10 / 3), 6)


class Physics(unittest.TestCase):
    def test_square_wave_fundamental(self):
        src = NoiseSource("c", "clock", 1e6, amplitude_v=1.0, rise_time=1e-12, duty=0.5)
        f, a = trapezoid_harmonics(src, 10e6)
        self.assertAlmostEqual(f[0], 1e6)
        self.assertAlmostEqual(a[0], 2 / math.pi, 3)     # 2A/pi
        self.assertLess(a[1], 1e-6)                       # even harmonics vanish at 50 % duty

    def test_aperture_half_wave_rule(self):
        enc = Enclosure(apertures=[Aperture("slot", 0.15)])
        se = aperture_se(enc, [100e6, 1e9])["aperture:slot"]
        self.assertAlmostEqual(se[0], 20.0, 1)            # lambda/2L = 10 -> 20 dB
        self.assertAlmostEqual(se[1], 0.0, 1)             # slot = lambda/2 -> no shielding

    def test_solid_aluminium_high_se(self):
        enc = Enclosure(material="aluminium", thickness_m=1e-3)
        self.assertGreater(float(solid_wall_se(enc, [1e6])[0]), 100)
        self.assertEqual(float(total_se(enc, [1e6])[0]), float(solid_wall_se(enc, [1e6])[0]))

    def test_shunt_capacitor_insertion_loss(self):
        flt = Filter("C", elements=[FilterElement("C", 1e-6, "shunt", esr=1e-9)], source_impedance=50,
                     load_impedance=50)
        il = float(insertion_loss_db(flt, [1e6])[0])
        expected = 20 * math.log10(abs(1 + 1j * 2 * math.pi * 1e6 * 1e-6 * 25))
        self.assertAlmostEqual(il, expected, 1)

    def test_dm_loop_formula(self):
        from emc_analyzer.core.models import Circuit, CurrentLoop
        from emc_analyzer.analysis.emissions import radiated_contributors
        src = NoiseSource("s", "sinusoid", 100e6, amplitude_v=2.0)
        p = Product(circuits=[Circuit("c", sources=[src],
                                      loops=[CurrentLoop("l", "s", area_m2=1e-4, current_a=2e-3)])])
        (_, _, f, e, _), = radiated_contributors(p, 1e9, 3.0)
        # sinusoid: p-p 2e-3 A -> 1e-3 A peak
        self.assertAlmostEqual(e[0], 1.316e-14 * 1e16 * 1e-4 * 1e-3 / 3, 12)


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = AnalysisEngine()

    def _run(self, name, **kw):
        prod = import_design(EX / name)
        return prod, self.engine.run(prod, **kw)

    def test_robot_controller(self):
        prod, rep = self._run("robot_controller.yaml")
        checks = {f.check for f in rep.findings}
        self.assertTrue({"radiated_emissions", "conducted_emissions", "enclosure_se", "victim_immunity"} <= checks)
        self.assertEqual(rep.overall, "FAIL")
        self.assertTrue(rep.mitigations)
        self.assertGreaterEqual(len(rep.next_steps), 4)
        self.assertFalse([n for n in rep.notes if "failed" in n], rep.notes)
        with tempfile.TemporaryDirectory() as d:
            h = export_html(rep, prod, Path(d) / "r.html")
            self.assertIn("Recommended mitigations", h.read_text(encoding="utf-8"))
            export_csv(rep, Path(d) / "r.csv")

    def test_eed(self):
        _, rep = self._run("eed_firing_circuit.yaml")
        eed = [f for f in rep.findings if f.check == "eed_safety"]
        self.assertEqual(len(eed), 1)
        self.assertIsNotNone(eed[0].margin_db)

    def test_mitigation_improves_eed(self):
        prod = import_design(EX / "eed_firing_circuit.yaml")
        base = self.engine.run(prod)
        m0 = next(f for f in base.findings if f.check == "eed_safety").margin_db
        cab = prod.cable("FIRE_LEADS")
        cab.shielded, cab.shield_termination = True, "360"
        prod.circuits[0].eeds[0].filter = "SQUIB_RF_FILTER"
        m1 = next(f for f in self.engine.run(prod).findings if f.check == "eed_safety").margin_db
        self.assertGreater(m1, m0 + 20)

    def test_importers(self):
        for name in ("python_model_sweep.py", "buck_converter.cir", "matlab_design.mat"):
            try:
                prod = import_design(EX / name)
            except ImportError as exc:      # scipy missing for .mat
                self.skipTest(str(exc))
            self.assertTrue(prod.circuits, name)
            rep = self.engine.run(prod, ["CISPR32_B_RE", "CISPR32_B_CE_QP"])
            self.assertTrue(rep.findings, name)

    def test_project_roundtrip(self):
        from emc_analyzer.importers.project import save_project
        prod = import_design(EX / "robot_controller.yaml")
        with tempfile.TemporaryDirectory() as d:
            p = save_project(prod, Path(d) / "x.yaml")
            again = import_design(p)
        self.assertEqual(prod.to_dict(), again.to_dict())


if __name__ == "__main__":
    unittest.main()
