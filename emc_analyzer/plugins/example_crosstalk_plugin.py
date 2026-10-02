"""Example plugin: PCB trace-to-trace crosstalk screening.

Shows how to add a new analysis without touching the core. Circuits opt in by
adding an entry under ``pcb.crosstalk`` in the project file::

    pcb:
      crosstalk:
        - {aggressor: CLK, victim_threshold_v: 0.2, parallel_length_m: 0.05,
           spacing_m: 0.2e-3, height_m: 0.1e-3}

Model: near-end crosstalk coefficient for microstrip over a plane,
    K ~ 1 / (1 + (s/h)^2), scaled by coupled length vs rise-time length.
"""
from emc_analyzer.analysis import register_analysis
from emc_analyzer.core.results import Finding, classify

V_PROP = 1.5e8  # m/s, FR-4 microstrip approx


@register_analysis("pcb_crosstalk", "PCB crosstalk screening (plugin example)", always=True)
def pcb_crosstalk(ctx):
    out = []
    for circ in ctx.product.circuits:
        for xt in circ.pcb.get("crosstalk", []) or []:
            src = circ.source(xt["aggressor"])
            if src is None:
                continue
            s, h = float(xt["spacing_m"]), float(xt["height_m"])
            k = 1.0 / (1.0 + (s / h) ** 2)
            l_rise = src.rise_time * V_PROP
            sat = min(1.0, 2 * float(xt["parallel_length_m"]) / max(l_rise, 1e-6))
            v_x = 0.25 * k * sat * src.amplitude_v
            import math
            margin = 20 * math.log10(float(xt["victim_threshold_v"]) / max(v_x, 1e-12))
            out.append(Finding("pcb_crosstalk", f"Crosstalk {src.name} -> victim ({circ.name})",
                               classify(margin), margin_db=margin, subject=circ.name,
                               detail=f"Estimated NEXT {v_x * 1e3:.1f} mV vs threshold "
                                      f"{float(xt['victim_threshold_v']) * 1e3:.0f} mV (s/h = {s / h:.1f})."))
    return out
