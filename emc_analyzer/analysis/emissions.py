"""Conducted and radiated emission estimates compared with limit lines.

Models (first-order, intended for design screening - not a substitute for test):

Conducted (LISN):
  DM: switching input-current harmonics split between the input capacitor and
      the LISN (2 x LISN in series), through the input filter (ABCD model).
  CM: switch-node voltage harmonics driven through the switch-node-to-chassis
      parasitic capacitance into the parallel LISNs (25 ohm).

Radiated (Paul, far field, includes ground-reflection factor of 2):
  DM loop:   |E| = 1.316e-14 * f^2 * A * I / r
  CM cable:  |E| = 1.257e-6 * f * L * I_cm / r          (L capped at lambda/2)
  Internal sources are reduced by enclosure SE; cables leaving the enclosure
  are reduced by shield transfer impedance, ferrites and filters only.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Tuple

import numpy as np

from ..core.models import Cable, Circuit, NoiseSource, Product
from ..core.results import FAIL, Finding, Trace, classify
from ..core.units import C0, db20, fmt_freq
from . import AnalysisContext, register_analysis
from .filters import insertion_loss_db
from .shielding import total_se
from .spectrum import spread_spectrum_reduction_db, trapezoid_harmonics

PK_TO_RMS_DB = -3.01   # EMI receivers report the RMS of a sinusoid


# --------------------------------------------------------------------------- helpers
def lisn_impedance(f, kind: str = "50uH"):
    w = 2 * np.pi * np.asarray(f, dtype=float)
    L = 5e-6 if str(kind).startswith("5uH") else 50e-6
    zl = 1j * w * L
    return zl * 50.0 / (zl + 50.0)


def cable_shield_factor(cable: Cable, f) -> np.ndarray:
    """Fraction (0..1) of CM current that escapes a shielded cable."""
    f = np.asarray(f, dtype=float)
    if not cable.shielded or cable.shield_termination == "none":
        return np.ones_like(f)
    w = 2 * np.pi * f
    zt = cable.transfer_impedance_mohm_per_m * 1e-3 * cable.length_m + 1j * w * 0.5e-9 * cable.length_m
    if cable.shield_termination == "pigtail":
        zt = zt + 1j * w * 1e-6 * cable.pigtail_length_m      # ~1 nH/mm
    return np.clip(np.abs(zt) / cable.cm_impedance_ohm, 1e-7, 1.0)


def ferrite_factor(cable: Cable, f) -> np.ndarray:
    f = np.asarray(f, dtype=float)
    if not cable.ferrite_impedance_ohm:
        return np.ones_like(f)
    # ferrite impedance rises roughly linearly up to ~100 MHz then flat
    zf = cable.ferrite_impedance_ohm * np.minimum(f / 100e6, 1.0)
    return cable.cm_impedance_ohm / np.abs(cable.cm_impedance_ohm + zf)


def source_current(circ: Circuit, src: NoiseSource) -> float:
    if src.current_a:
        return src.current_a
    # unknown current: assume source drives a 50-ohm-ish transmission line
    return src.amplitude_v / 50.0


def cm_coupling_ratio(circ: Circuit) -> float:
    """Fraction of a source voltage that appears as CM voltage driving attached cables."""
    if "cm_coupling" in circ.pcb:
        return float(circ.pcb["cm_coupling"])
    if circ.pcb.get("ground_plane", True) is False:
        return 0.05           # -26 dB : split / no ground plane
    return 0.005              # -46 dB : solid plane, good layout


def _sum_lines(lines: List[Tuple[np.ndarray, np.ndarray]], resolution_hz: float = 1e3):
    """Power-sum spectral lines that fall in the same frequency bin."""
    acc: Dict[int, float] = defaultdict(float)
    for f, a in lines:
        for fi, ai in zip(np.round(np.asarray(f) / resolution_hz).astype(np.int64), np.asarray(a)):
            acc[int(fi)] += float(ai) ** 2
    if not acc:
        return np.array([]), np.array([])
    keys = np.array(sorted(acc))
    return keys * resolution_hz, np.sqrt(np.array([acc[k] for k in keys]))


def _compare(f, level_db, std, distance=None):
    lim = std.level(f, distance)
    m = ~np.isnan(lim)
    if not m.any():
        return None, None, lim
    margins = lim[m] - level_db[m]
    i = int(np.argmin(margins))
    return float(margins[i]), float(f[m][i]), lim


# --------------------------------------------------------------------------- conducted
def conducted_spectrum(circ: Circuit, product: Product, lisn: str = "50uH", f_max: float = 30e6):
    """Return dict with DM, CM and total voltage (dBuV) lines at LISN."""
    srcs = [s for s in circ.sources if s.kind in ("switching", "pwm")] or \
           ([circ.sources[0]] if circ.sources and circ.type in ("smps", "motor_drive") else [])
    filt = product.filter(circ.input_filter)
    out = {"dm": [], "cm": []}
    for src in srcs:
        f, v_sw = trapezoid_harmonics(src, f_max)
        i_in = circ.input_current_a or src.current_a or 1.0
        i_peak = i_in / max(src.duty, 0.05)                       # pulsed input current
        _, i_n = trapezoid_harmonics(src, f_max, amplitude=i_peak)
        w = 2 * np.pi * f
        zc = circ.input_cap_esr + 1j * w * circ.input_cap_esl + 1 / (1j * w * circ.input_cap_f)
        zl_dm = 2 * lisn_impedance(f, lisn)
        v_th = i_n * zc                                           # Norton -> Thevenin
        v_load = np.abs(v_th * zl_dm / (zl_dm + zc))
        il = insertion_loss_db(filt, f, zs=zc, zl=zl_dm) if filt and filt.mode in ("DM", "both") else 0
        v_meas_dm = v_load / 2 * 10 ** (-np.asarray(il) / 20)
        # CM path
        zcp = 1 / (1j * w * circ.switch_node_to_chassis_f)
        zl_cm = lisn_impedance(f, lisn) / 2
        i_cm = np.abs(v_sw / (zcp + zl_cm))
        il_cm = insertion_loss_db(filt, f, zs=zcp, zl=zl_cm) if filt and filt.mode in ("CM", "both") else 0
        v_meas_cm = i_cm / 2 * 50.0 * 10 ** (-np.asarray(il_cm) / 20)
        ss = spread_spectrum_reduction_db(f, src.spread_spectrum_pct)
        out["dm"].append((f, v_meas_dm * 10 ** (-ss / 20)))
        out["cm"].append((f, v_meas_cm * 10 ** (-ss / 20)))
    fd, vd = _sum_lines(out["dm"])
    fc, vc = _sum_lines(out["cm"])
    ft, vt = _sum_lines(out["dm"] + out["cm"])
    to_db = lambda v: db20(v / 1e-6) + PK_TO_RMS_DB  # noqa: E731
    return {"dm": (fd, to_db(vd)), "cm": (fc, to_db(vc)), "total": (ft, to_db(vt))}


@register_analysis("conducted_emissions", "Conducted emissions (power port, LISN)",
                   applies_to=("conducted_emission",))
def conducted_emissions(ctx: AnalysisContext) -> List[Finding]:
    findings = []
    for std in ctx.standards_of("conducted_emission"):
        lisn = std.meta.get("lisn", "50uH")
        for circ in ctx.product.circuits:
            if circ.type not in ("smps", "motor_drive") and not any(
                    s.kind in ("switching", "pwm") for s in circ.sources):
                continue
            spec = conducted_spectrum(circ, ctx.product, lisn, f_max=std.f_max * 1.05)
            f, lvl = spec["total"]
            if f.size == 0:
                continue
            margin, fw, lim = _compare(f, lvl, std)
            if margin is None:
                continue
            fdm, ldm = spec["dm"]
            fcm, lcm = spec["cm"]
            idx = np.argmin(np.abs(fdm - fw)) if fdm.size else 0
            dm_at = float(ldm[idx]) if fdm.size else -999
            cm_at = float(lcm[np.argmin(np.abs(fcm - fw))]) if fcm.size else -999
            dominant = "DM" if dm_at >= cm_at else "CM"
            lf, ll = std.plot_points()
            findings.append(Finding(
                check="conducted_emissions", title=f"Conducted emissions - {circ.name}",
                status=classify(margin), margin_db=margin, worst_freq_hz=fw, standard=std.id,
                subject=circ.name,
                detail=(f"Worst case {margin:+.1f} dB at {fmt_freq(fw)} vs {std.name}; "
                        f"{dominant}-mode dominated (DM {dm_at:.1f} dBuV, CM {cm_at:.1f} dBuV)."),
                traces=[Trace("Estimated DM", fdm, ldm, "dBuV", "stem"),
                        Trace("Estimated CM", fcm, lcm, "dBuV", "stem"),
                        Trace(f"Limit {std.id}", lf, ll, "dBuV", "limit")],
                y_label="Voltage at LISN (dBuV)",
                data={"dominant": dominant, "dm_db": dm_at, "cm_db": cm_at,
                      "excess_db": max(0.0, -margin), "circuit": circ.name}))
    return findings


# --------------------------------------------------------------------------- radiated
def radiated_contributors(product: Product, f_max: float, distance: float):
    """List of (label, kind, freqs, E_V_per_m_peak) for every emitter."""
    enc = product.enclosure
    contribs = []
    for circ in product.circuits:
        for loop in circ.loops:
            src = circ.source(loop.source)
            if src is None:
                continue
            i_amp = loop.current_a or source_current(circ, src)
            f, i_n = trapezoid_harmonics(src, f_max, amplitude=i_amp)
            e = 1.316e-14 * f ** 2 * loop.area_m2 * i_n / distance
            if enc is not None and loop.inside_enclosure:
                e = e * 10 ** (-total_se(enc, f, "magnetic", min(enc.dimensions_m) / 2) / 20)
            e = e * 10 ** (-spread_spectrum_reduction_db(f, src.spread_spectrum_pct) / 20)
            contribs.append((f"{circ.name}/{loop.name}", "loop", f, e, {"circuit": circ.name, "loop": loop.name,
                                                                         "source": src.name}))
        # common-mode on attached cables
        cables = [c for c in product.cables if c.connected_circuit == circ.name or c.name == circ.power_cable]
        for cab in cables:
            for src in circ.sources:
                f, v_n = trapezoid_harmonics(src, f_max)
                if src.kind in ("switching", "pwm"):
                    w = 2 * np.pi * f
                    zcp = 1 / (1j * w * circ.switch_node_to_chassis_f)
                    i_cm = np.abs(v_n / (zcp + cab.cm_impedance_ohm))
                else:
                    i_cm = v_n * cm_coupling_ratio(circ) / cab.cm_impedance_ohm
                lam = C0 / f
                L_eff = np.minimum(cab.length_m, lam / 2)
                i_cm = i_cm * cable_shield_factor(cab, f) * ferrite_factor(cab, f)
                flt = product.filter(cab.filter)
                if flt is not None and flt.mode in ("CM", "both"):
                    i_cm = i_cm * 10 ** (-insertion_loss_db(flt, f) / 20)
                e = 1.257e-6 * f * L_eff * i_cm / distance
                if enc is not None and not cab.exits_enclosure:
                    e = e * 10 ** (-total_se(enc, f) / 20)
                e = e * 10 ** (-spread_spectrum_reduction_db(f, src.spread_spectrum_pct) / 20)
                contribs.append((f"{cab.name} (CM from {circ.name}/{src.name})", "cable", f, e,
                                 {"circuit": circ.name, "cable": cab.name, "source": src.name}))
    return contribs


@register_analysis("radiated_emissions", "Radiated emissions (DM loops + CM cables)",
                   applies_to=("radiated_emission",))
def radiated_emissions(ctx: AnalysisContext) -> List[Finding]:
    findings = []
    p = ctx.product
    for std in ctx.standards_of("radiated_emission"):
        d = std.distance_m or p.measurement_distance_m
        contribs = radiated_contributors(p, std.f_max * 1.05, d)
        if not contribs:
            continue
        f, e = _sum_lines([(c[2], c[3]) for c in contribs], resolution_hz=10e3)
        lvl = db20(e / 1e-6) + PK_TO_RMS_DB
        margin, fw, _ = _compare(f, lvl, std, d)
        if margin is None:
            continue
        # contributor at worst frequency
        best, best_val, best_meta = None, -1, None
        for label, kind, cf, ce, meta in contribs:
            j = np.argmin(np.abs(cf - fw))
            if abs(cf[j] - fw) < 10e3 and ce[j] > best_val:
                best, best_val, best_meta = (label, kind), ce[j], meta
        in_band = (f >= std.f_min) & (f <= std.f_max)
        traces = []
        for label, kind, cf, ce, _ in contribs:
            m = (cf >= std.f_min) & (cf <= std.f_max)
            if m.any():
                traces.append(Trace(label, cf[m], db20(ce[m] / 1e-6) + PK_TO_RMS_DB, "dBuV/m", "stem"))
        traces.sort(key=lambda t: -np.max(t.value))
        lf, ll = std.plot_points(d)
        traces = traces[:6] + [Trace(f"Limit {std.id} @ {d:g} m", lf, ll, "dBuV/m", "limit")]
        findings.append(Finding(
            check="radiated_emissions", title=f"Radiated emissions @ {d:g} m",
            status=classify(margin), margin_db=margin, worst_freq_hz=fw, standard=std.id,
            subject=best[0] if best else None,
            detail=(f"Worst case {margin:+.1f} dB at {fmt_freq(fw)} vs {std.name}. "
                    f"Dominant contributor: {best[0] if best else 'n/a'} ({best[1] if best else ''}). "
                    f"{int(in_band.sum())} spectral lines in band."),
            traces=traces, y_label="E-field (dBuV/m)",
            data={"dominant_kind": best[1] if best else None, "dominant": best_meta or {},
                  "excess_db": max(0.0, -margin), "distance_m": d,
                  "limit_at_worst": float(std.level([fw], d)[0])}))
    return findings
