"""Enclosure shielding-effectiveness assessment and cavity-resonance screening."""
from __future__ import annotations

from typing import List

import numpy as np

from ..core.results import INFO, Finding, Trace, classify
from ..core.units import fmt_freq, log_grid
from . import AnalysisContext, register_analysis
from .shielding import cavity_resonances, total_se


@register_analysis("enclosure_se", "Enclosure shielding effectiveness", always=True)
def enclosure_se(ctx: AnalysisContext) -> List[Finding]:
    enc = ctx.product.enclosure
    if enc is None:
        return []
    f = log_grid(10e3, 18e9, 60)
    tot, paths = total_se(enc, f, breakdown=True)
    required = float(ctx.setting("required_se_db", enc.extra.get("required_se_db", 40.0)))
    band = (f >= 30e6) & (f <= 6e9)
    i = int(np.argmin(tot[band]))
    f_w = float(f[band][i])
    margin = float(tot[band][i] - required)
    # weakest leakage path at the worst frequency
    weakest = min(paths, key=lambda k: paths[k][band][i])
    traces = [Trace("Total SE", f, tot, "dB")]
    traces += [Trace(k, f, v, "dB") for k, v in paths.items()]
    traces.append(Trace(f"Required SE ({required:g} dB)", np.array([f[0], f[-1]]), np.full(2, required), "dB", "limit"))
    findings = [Finding(
        check="enclosure_se", title=f"Enclosure SE - {enc.name}", status=classify(margin, 6.0),
        margin_db=margin, worst_freq_hz=f_w, subject=enc.name, standard=f"Required SE {required:g} dB",
        detail=(f"{enc.material}, {enc.thickness_m * 1e3:.2g} mm wall. Minimum SE (30 MHz-6 GHz) "
                f"{tot[band][i]:.1f} dB at {fmt_freq(f_w)}; limiting path: {weakest}."),
        traces=traces, y_label="Shielding effectiveness (dB)",
        data={"weakest_path": weakest, "required_se_db": required, "min_se_db": float(tot[band][i]),
              "excess_db": max(0.0, -margin)})]

    modes = cavity_resonances(enc, 3)
    if modes:
        txt = ", ".join(f"{fmt_freq(fr)} ({name})" for fr, name in modes)
        findings.append(Finding(
            check="cavity_resonance", title=f"Cavity resonances - {enc.name}", status=INFO,
            worst_freq_hz=modes[0][0], subject=enc.name,
            detail=(f"Lowest enclosure resonances: {txt}. Shielding can collapse and internal coupling "
                    f"rise sharply near these frequencies; check clock harmonics against them."),
            data={"modes": [m[0] for m in modes]}))
    return findings
