"""RF susceptibility: EED safe-power-density (HERO style), victim-circuit immunity,
and filter power rating - the three assessment types offered by tools like EAS.

EED coupling model
------------------
The EED leads are treated as a receiving dipole of length L.

* ``matched`` (worst case): delivered power P = S * Ae, Ae = G lambda^2 / 4 pi, G = 1.64.
* ``dipole`` (physical, default): open-circuit voltage V = E * h_eff with
  h_eff = L/2 (short) or lambda/pi (resonant), source impedance
  Z_a = R_rad + jX (short-dipole reactance); power into the bridgewire R:
  P = |V|^2 R / |Z_a + R|^2, never more than the matched case.

Safe power density S_safe(f) is the incident density that puts NFP / margin
into the bridgewire; the environment must sit below it everywhere.
"""
from __future__ import annotations

import math
from typing import List

import numpy as np

from ..core.models import EED, Cable, Environment, Product
from ..core.results import Finding, Trace, classify
from ..core.units import C0, ETA0, fmt_freq, log_grid
from . import AnalysisContext, register_analysis
from .emissions import cable_shield_factor, ferrite_factor
from .filters import element_dissipation, insertion_loss_db
from .shielding import total_se

AM_PEAK_FACTOR_DB = 20 * math.log10(1.8)   # 80 % AM


def env_power_density(env: Environment, f) -> np.ndarray:
    """Environment value at f converted to W/m^2 (NaN outside defined bands)."""
    f = np.asarray(f, dtype=float)
    out = np.full(f.shape, np.nan)
    for f0, f1, v in env.bands:
        m = (f >= f0) & (f <= f1)
        val = v if env.unit.lower().startswith("w") else v ** 2 / ETA0
        out[m] = np.fmax(out[m], val)
    return out


def env_step_points(env: Environment):
    """Step-plot points (W/m^2) for an environment definition."""
    fs, vs = [], []
    for f0, f1, v in sorted(env.bands):
        val = v if env.unit.lower().startswith("w") else v ** 2 / ETA0
        fs += [f0, f1]
        vs += [val, val]
    return np.array(fs, dtype=float), np.array(vs, dtype=float)


def coupling_aperture(f, length_m: float, r_load: float, model: str = "dipole", wire_radius=0.25e-3):
    """Effective aperture (m^2) such that P_delivered = S * Ae."""
    f = np.asarray(f, dtype=float)
    lam = C0 / f
    ae_matched = 1.64 * lam ** 2 / (4 * np.pi)
    if model == "matched":
        return ae_matched
    L = length_m
    kl = np.pi * L / lam
    short = L < lam / 2
    h_eff = np.where(short, L / 2, lam / np.pi)
    r_rad = np.where(short, 20 * np.pi ** 2 * (L / lam) ** 2, 73.0)
    x = np.where(short, -120 * (math.log(max(L / wire_radius, 2.0)) - 1) / np.tan(np.minimum(kl, 1.5)), 42.5)
    S_unit = 1.0
    E = math.sqrt(S_unit * ETA0)
    v = E * h_eff
    p = v ** 2 * r_load / ((r_rad + r_load) ** 2 + x ** 2)
    # convert amplitude-based power with RMS E (S = E_rms^2/eta) - p already per unit S
    return np.minimum(p / S_unit, ae_matched)


def path_attenuation_db(product: Product, cable: Cable, f, filt_name=None) -> np.ndarray:
    f = np.asarray(f, dtype=float)
    att = np.zeros_like(f)
    enc = product.enclosure
    if cable is not None:
        att += -20 * np.log10(cable_shield_factor(cable, f) * ferrite_factor(cable, f))
        if enc is not None and not cable.exits_enclosure:
            att += total_se(enc, f)
    elif enc is not None:
        att += total_se(enc, f)
    filt = product.filter(filt_name or (cable.filter if cable else None))
    if filt is not None:
        att += insertion_loss_db(filt, f)
    return att


def _env_from_ctx(ctx: AnalysisContext):
    envs = []
    if ctx.environment is not None:
        envs.append((ctx.environment, 0.0))
    for std in ctx.standards_of("radiated_immunity"):
        am = AM_PEAK_FACTOR_DB if ctx.setting("include_am", True) else 0.0
        envs.append((Environment(name=std.name, unit="V/m",
                                 bands=[(s[0], s[1], max(s[2], s[3])) for s in std.segments]), am))
    return envs


@register_analysis("eed_safety", "EED RF safety (safe power density vs environment)",
                   applies_to=("radiated_immunity",), always=True)
def eed_safety(ctx: AnalysisContext) -> List[Finding]:
    findings = []
    p = ctx.product
    envs = _env_from_ctx(ctx)
    model = ctx.setting("eed_coupling_model", "dipole")
    for circ in p.circuits:
        for eed in circ.eeds:
            cable = p.cable(eed.cable)
            L = cable.length_m if cable else eed.extra.get("lead_length_m", 0.5)
            f = log_grid(100e3, 100e9, 60)
            ae = coupling_aperture(f, L, eed.bridgewire_resistance_ohm, model)
            att = path_attenuation_db(p, cable, f, eed.filter)
            p_allow = eed.nfp_w / 10 ** (eed.safety_margin_db / 10)
            s_safe = p_allow / (ae * 10 ** (-att / 10))
            traces = [Trace("Safe power density", f, s_safe, "W/m2", "line")]
            if not envs:
                findings.append(Finding("eed_safety", f"EED safe power density - {eed.name}", "INFO",
                                        subject=eed.name, standard=None,
                                        detail=f"No RF environment selected. Minimum safe density "
                                               f"{np.min(s_safe):.3g} W/m2 at {fmt_freq(f[np.argmin(s_safe)])}.",
                                        traces=traces, y_label="Power density (W/m2)", y_log=True))
                continue
            for env, am_db in envs:
                s_env = env_power_density(env, f) * 10 ** (am_db / 10)
                m = ~np.isnan(s_env)
                if not m.any():
                    continue
                margins = 10 * np.log10(s_safe[m] / s_env[m])
                i = int(np.nanargmin(margins))
                margin = float(margins[i])
                fw = float(f[m][i])
                ef, ev = env_step_points(env)
                findings.append(Finding(
                    check="eed_safety", title=f"EED RF safety - {eed.name}",
                    status=classify(margin, 3.0), margin_db=margin, worst_freq_hz=fw, standard=env.name,
                    subject=eed.name,
                    detail=(f"NFP {eed.nfp_w * 1e3:.1f} mW with {eed.safety_margin_db:g} dB safety margin; "
                            f"leads {L:g} m, coupling model '{model}'. Worst margin {margin:+.1f} dB at "
                            f"{fmt_freq(fw)} (safe {s_safe[m][i]:.3g} W/m2 vs environment {s_env[m][i]:.3g} W/m2)."),
                    traces=traces + [Trace(f"RF environment: {env.name}", ef, ev * 10 ** (am_db / 10), "W/m2", "limit")],
                    y_label="Safe power density (W/m2)", y_log=True,
                    data={"excess_db": max(0.0, -margin), "lead_length_m": L,
                          "shielded": bool(cable and cable.shielded), "has_filter": bool(eed.filter),
                          "cable": cable.name if cable else None, "circuit": circ.name}))
    return findings


@register_analysis("victim_immunity", "Radiated / conducted RF immunity of sensitive inputs",
                   applies_to=("radiated_immunity", "conducted_immunity"))
def victim_immunity(ctx: AnalysisContext) -> List[Finding]:
    findings = []
    p = ctx.product
    am = AM_PEAK_FACTOR_DB if ctx.setting("include_am", True) else 0.0
    for circ in p.circuits:
        for vic in circ.victims:
            cable = p.cable(vic.cable)
            for std in ctx.standards_of("radiated_immunity", "conducted_immunity"):
                f0, f1 = max(std.f_min, vic.f_min), min(std.f_max, vic.f_max)
                if f0 >= f1:
                    continue
                f = log_grid(f0, f1, 80)
                lvl = std.level(f)
                zsrc = cable.cm_impedance_ohm if cable else 150.0
                if std.type == "radiated_immunity":
                    lam = C0 / f
                    L = cable.length_m if cable else 0.05      # PCB trace pickup if no cable
                    h_eff = np.minimum(L, lam / np.pi)
                    v_oc = lvl * h_eff * math.sqrt(2) * 10 ** (am / 20)
                else:
                    zsrc = 150.0
                    v_oc = lvl * math.sqrt(2) * 10 ** (am / 20)
                v_in = v_oc * vic.input_impedance_ohm / (vic.input_impedance_ohm + zsrc)
                att = path_attenuation_db(p, cable, f, vic.filter)
                if std.type == "conducted_immunity" and cable is not None:
                    # enclosure does not protect against conducted injection
                    att = att - (total_se(p.enclosure, f) if (p.enclosure and not cable.exits_enclosure) else 0)
                v_vic = v_in * 10 ** (-att / 20)
                margins = 20 * np.log10(vic.threshold_v / v_vic)
                if np.all(np.isnan(margins)):
                    continue
                i = int(np.nanargmin(margins))
                margin = float(margins[i])
                findings.append(Finding(
                    check="victim_immunity", title=f"Immunity - {circ.name}/{vic.name}",
                    status=classify(margin, vic.margin_db), margin_db=margin, worst_freq_hz=float(f[i]),
                    standard=std.id, subject=vic.name,
                    detail=(f"Induced {v_vic[i] * 1e3:.3g} mV peak vs threshold {vic.threshold_v * 1e3:.3g} mV "
                            f"at {fmt_freq(f[i])} ({std.name})."),
                    traces=[Trace("Induced voltage at input", f, 20 * np.log10(v_vic / 1e-6), "dBuV"),
                            Trace("Susceptibility threshold", np.array([f0, f1]),
                                  np.full(2, 20 * math.log10(vic.threshold_v / 1e-6)), "dBuV", "limit")],
                    y_label="Voltage at input (dBuV)",
                    data={"excess_db": max(0.0, -margin), "type": std.type, "cable": vic.cable,
                          "has_filter": bool(vic.filter), "circuit": circ.name}))
    return findings


@register_analysis("filter_power", "Filter power rating under RF environment", always=True)
def filter_power(ctx: AnalysisContext) -> List[Finding]:
    """Power dissipated in each filter element when the attached cable is illuminated."""
    findings = []
    p = ctx.product
    envs = _env_from_ctx(ctx)
    if not envs:
        return findings
    for filt in p.filters:
        rated = filt.rated_power_w
        if rated is None and not any(e.rated_power_w for e in filt.elements):
            continue
        cable = next((c for c in p.cables if c.filter == filt.name), None)
        L = cable.length_m if cable else 1.0
        model = ctx.setting("eed_coupling_model", "dipole")
        f = log_grid(100e3, 18e9, 40)
        worst = (0.0, None, None)
        for env, am_db in envs:
            s = env_power_density(env, f) * 10 ** (am_db / 10)
            for fi, si in zip(f, s):
                if np.isnan(si):
                    continue
                pa = si * coupling_aperture(np.array([fi]), L, filt.source_impedance, model)[0]
                pa *= 10 ** (-path_attenuation_db(p, cable, np.array([fi]), "__none__")[0] / 10)
                v_src = math.sqrt(8 * pa * filt.source_impedance)   # available power -> peak emf
                for row in element_dissipation(filt, fi, v_src):
                    lim = row["rated_power_w"]
                    if row["element"] == "load":
                        continue
                    if lim is None and rated is not None:
                        lim = rated
                    if lim and row["power_w"] / lim > worst[0]:
                        worst = (row["power_w"] / lim, fi, row)
        if worst[1] is None:
            continue
        margin = -10 * math.log10(max(worst[0], 1e-12))
        findings.append(Finding(
            check="filter_power", title=f"Filter power rating - {filt.name}", status=classify(margin, 3.0),
            margin_db=margin, worst_freq_hz=worst[1], subject=filt.name, standard="RF environment",
            detail=(f"Element '{worst[2]['element']}' dissipates {worst[2]['power_w']:.3g} W "
                    f"({worst[0] * 100:.1f}% of rating) at {fmt_freq(worst[1])}."),
            data={"excess_db": max(0.0, -margin)}))
    return findings
