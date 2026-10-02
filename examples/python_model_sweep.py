"""Example Python model: build the design in code.

Load it from the GUI (File > Open) or the CLI:
    python -m emc_analyzer analyze examples/python_model_sweep.py --report out.html

Because it is plain Python you can compute parameters from your own design
scripts, datasheets, scikit-rf / numpy models, or optimisation loops. See
sweep_loop_area() for a parametric study driven from Python.
"""
from emc_analyzer.core.models import (Aperture, Cable, Circuit, CurrentLoop, Enclosure, Filter, FilterElement,
                                      NoiseSource, Product, Seam)

CLOCK_HZ = 48e6
LOOP_AREA_M2 = 2e-4


def build_product(loop_area=LOOP_AREA_M2, ferrite_ohm=0.0) -> Product:
    mcu = Circuit(
        name="SensorHub", type="digital", supply_voltage=3.3,
        pcb={"layers": 4, "ground_plane": True, "decoupling": True},
        sources=[NoiseSource("USB_CLK", "clock", CLOCK_HZ, 3.3, rise_time=1e-9, current_a=0.01)],
        loops=[CurrentLoop("CLK_ROUTE", "USB_CLK", area_m2=loop_area)],
    )
    usb = Cable("USB", length_m=1.0, shielded=True, shield_termination="pigtail", pigtail_length_m=0.02,
                connected_circuit="SensorHub", ferrite_impedance_ohm=ferrite_ohm)
    enc = Enclosure("ABS housing", material="plastic", coating_surface_resistance_ohm_sq=0.5,
                    thickness_m=2e-3, dimensions_m=(0.12, 0.08, 0.03),
                    apertures=[Aperture("USB port", 0.012)], seams=[Seam("Clam-shell", 0.4, 0.03)])
    return Product(name="Sensor hub (Python model)", circuits=[mcu], cables=[usb], enclosure=enc,
                   filters=[Filter("USB_CM", "CM choke", [FilterElement("L", 90e-6, "series")], mode="CM")],
                   standards=["CISPR32_B_RE", "CISPR32_B_RE_1G"])


def sweep_loop_area():
    """Parametric study: how does worst-case RE margin change with loop area and a ferrite?"""
    from emc_analyzer import AnalysisEngine
    eng = AnalysisEngine()
    for ferrite in (0, 300):
        for area_cm2 in (0.5, 1, 2, 4, 8):
            rep = eng.run(build_product(area_cm2 * 1e-4, ferrite), ["CISPR32_B_RE"])
            f = next(x for x in rep.findings if x.check == "radiated_emissions")
            print(f"ferrite {ferrite:4} ohm  loop {area_cm2:4} cm2 -> margin {f.margin_db:+6.1f} dB "
                  f"({f.subject})")


if __name__ == "__main__":
    sweep_loop_area()
