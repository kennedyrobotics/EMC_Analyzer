"""Rule-based mitigation advisor.

Each rule inspects the findings and the product model and returns
``Mitigation`` objects with a rationale and, where it can be computed, an
estimated improvement in dB sized to the exceedance.

Add rules (in a plugin or your own module) with::

    @register_rule
    def my_rule(product, findings):
        return [Mitigation(...)]
"""
from __future__ import annotations

import math
from typing import Callable, List

from ..analysis.filters import lc_corner_for_attenuation
from ..analysis.shielding import max_aperture_for_se, total_se
from ..core.models import Product
from ..core.results import FAIL, MARGINAL, Finding, Mitigation
from ..core.units import C0, fmt_freq

RULES: List[Callable[[Product, List[Finding]], List[Mitigation]]] = []


def register_rule(fn):
    RULES.append(fn)
    return fn


def _needs_work(findings, check):
    return [f for f in findings if f.check == check and f.status in (FAIL, MARGINAL)]


def _target(f: Finding, extra_margin=6.0):
    """dB improvement needed to reach the limit plus a design margin."""
    return max(0.0, -(f.margin_db or 0.0)) + extra_margin


def _fmt_eng(x, unit):
    for s, p in ((1e-12, "p"), (1e-9, "n"), (1e-6, "u"), (1e-3, "m"), (1, ""), (1e3, "k"), (1e6, "M")):
        if abs(x) < s * 1000:
            return f"{x / s:.3g} {p}{unit}"
    return f"{x:.3g} {unit}"


# --------------------------------------------------------------------------- radiated
@register_rule
def radiated_rules(product: Product, findings: List[Finding]) -> List[Mitigation]:
    out = []
    for f in _needs_work(findings, "radiated_emissions"):
        need = _target(f)
        dom = f.data.get("dominant", {})
        kind = f.data.get("dominant_kind")
        fw = f.worst_freq_hz
        circ = product.circuit(dom.get("circuit"))
        src = circ.source(dom.get("source")) if circ else None
        if kind == "loop" and circ:
            loop = next((l for l in circ.loops if l.name == dom.get("loop")), None)
            if loop:
                a_new = loop.area_m2 / 10 ** (need / 20)
                out.append(Mitigation(
                    "Reduce differential-mode loop area",
                    (f"Loop '{loop.name}' ({loop.area_m2 * 1e4:.2g} cm2) dominates at {fmt_freq(fw)}. E-field "
                     f"scales with area: shrink to <= {a_new * 1e4:.2g} cm2 for {need:.0f} dB. Route the return "
                     f"directly beneath the signal on an unbroken ground plane, put the clock driver next to its load, "
                     f"and avoid crossing plane splits."),
                    f"{circ.name}/{loop.name}", "PCB layout", 1, f"{need:.0f} dB needed; 6 dB per halving of area",
                    "Medium", [f.title]))
            if src and src.kind != "sinusoid":
                knee = 1 / (math.pi * src.rise_time)
                if fw > knee:
                    tr_new = src.rise_time * 10 ** (min(need, 20) / 20)
                    out.append(Mitigation(
                        "Slow edge rates on the offending source",
                        (f"{fmt_freq(fw)} is above the edge knee of '{src.name}' ({fmt_freq(knee)}), where spectrum "
                         f"falls 40 dB/dec. Increasing rise time from {src.rise_time * 1e9:.2g} ns to "
                         f"~{tr_new * 1e9:.2g} ns (series 22-100 ohm resistor, slew-rate control, lower drive "
                         f"strength) gives ~{min(need, 20):.0f} dB. Check timing margins."),
                        f"{circ.name}/{src.name}", "Source", 1, "up to 20 dB per decade of tr above knee", "Low",
                        [f.title]))
                if not src.spread_spectrum_pct and src.kind in ("clock", "switching", "pwm"):
                    out.append(Mitigation(
                        "Enable spread-spectrum / frequency dithering",
                        (f"A 1-2 % down-spread on '{src.name}' typically lowers peak harmonics by 6-12 dB at "
                         f"{fmt_freq(fw)} (more at higher harmonics). Confirm interface jitter tolerance."),
                        f"{circ.name}/{src.name}", "Source", 2, "6-12 dB", "Low", [f.title]))
        if kind == "cable":
            cab = product.cable(dom.get("cable"))
            if cab:
                zf_needed = cab.cm_impedance_ohm * (10 ** (need / 20) - 1)
                if zf_needed <= 1500:
                    txt = (f"A ferrite or CM choke with >= {zf_needed:.0f} ohm at {fmt_freq(fw)} (vs "
                           f"{cab.cm_impedance_ohm:g} ohm CM loop) gives ~{need:.0f} dB. Place it at the enclosure exit.")
                    exp = f"{need:.0f} dB"
                else:
                    gain = 20 * math.log10((cab.cm_impedance_ohm + 1000) / cab.cm_impedance_ohm)
                    txt = (f"A ~1 kohm ferrite/CM choke gives only ~{gain:.0f} dB of the {need:.0f} dB needed at "
                           f"{fmt_freq(fw)} - combine it with source reduction (ground plane, CM filtering to "
                           f"chassis at the connector) or a shielded cable.")
                    exp = f"~{gain:.0f} dB of {need:.0f} dB"
                out.append(Mitigation(
                    "Add common-mode choke / ferrite on the cable",
                    f"Cable '{cab.name}' common-mode current dominates at {fmt_freq(fw)}. " + txt,
                    cab.name, "Cabling", 1, exp, "Low", [f.title]))
                if not cab.shielded or cab.shield_termination != "360":
                    out.append(Mitigation(
                        "Use shielded cable with 360-degree shield termination",
                        ("Terminate the braid circumferentially to a metal backshell/connector bonded to chassis. "
                         + ("Pigtails add ~1 nH/mm and destroy shield performance above ~10 MHz. "
                            if cab.shield_termination == "pigtail" else "")
                         + "Typical improvement 20-40 dB on CM radiation."),
                        cab.name, "Cabling", 1, "20-40 dB", "Medium", [f.title]))
                out.append(Mitigation(
                    "Filter the interface at the enclosure boundary",
                    ("Fit feed-through capacitors or a filtered connector (CM capacitors to chassis, 100 pF-1 nF for "
                     "signals) so noise currents return to chassis instead of flowing on the cable. Keep the "
                     "filter ground to chassis < 5 mm."),
                    cab.name, "Filtering", 2, "10-30 dB", "Medium", [f.title]))
                if circ and circ.pcb.get("ground_plane", True) is False:
                    out.append(Mitigation(
                        "Add a solid ground plane / reduce ground impedance",
                        ("Ground bounce between the PCB 0 V and the cable reference drives CM current. A continuous "
                         "plane (4-layer stack-up: SIG-GND-PWR-SIG) typically gives 20 dB."),
                        circ.name, "PCB layout", 1, "~20 dB", "High", [f.title]))
        # shielding check
        enc = product.enclosure
        if enc is not None and fw:
            se = float(total_se(enc, [fw])[0])
            if kind == "loop" and se < 40:
                out.append(Mitigation(
                    "Improve enclosure shielding at the worst frequency",
                    f"Enclosure SE is only {se:.0f} dB at {fmt_freq(fw)}; see the enclosure SE finding for "
                    f"the limiting aperture/seam.", enc.name, "Shielding", 2, f"{need:.0f} dB", "Medium", [f.title]))
        elif enc is None and kind == "loop":
            out.append(Mitigation(
                "Consider a conductive enclosure or board-level shield can",
                "No enclosure modelled; a board-level can over the clock/CPU area gives 20-40 dB above 100 MHz.",
                "product", "Shielding", 2, "20-40 dB", "Medium", [f.title]))
    return out


# --------------------------------------------------------------------------- conducted
@register_rule
def conducted_rules(product: Product, findings: List[Finding]) -> List[Mitigation]:
    out = []
    for f in _needs_work(findings, "conducted_emissions"):
        need = _target(f)
        circ = product.circuit(f.data.get("circuit"))
        fsw = circ.sources[0].frequency if circ and circ.sources else f.worst_freq_hz
        f_target = max(f.worst_freq_hz, fsw)
        if f.data.get("dominant") == "DM":
            fc = lc_corner_for_attenuation(need, f_target, 2)
            L = 10e-6
            C = 1 / ((2 * math.pi * fc) ** 2 * L)
            out.append(Mitigation(
                "Add / upsize differential-mode input filter",
                (f"DM noise dominates at {fmt_freq(f.worst_freq_hz)}. An LC stage with corner <= {fmt_freq(fc)} "
                 f"(e.g. L = 10 uH, C >= {_fmt_eng(C, 'F')}) gives ~{need:.0f} dB. Damp the filter "
                 f"(R-C across C or lossy L) to avoid resonance & converter instability "
                 f"(filter output impedance << converter input impedance)."),
                circ.name if circ else "power input", "Filtering", 1, f"{need:.0f} dB", "Medium", [f.title]))
            out.append(Mitigation(
                "Lower input-capacitor ESR/ESL",
                "Parallel low-ESR ceramics (X7R) close to the switch with minimal loop area to keep ripple current "
                "off the input lines.", circ.name if circ else "", "Source", 2, "3-10 dB", "Low", [f.title]))
        else:
            out.append(Mitigation(
                "Add common-mode choke and Y-capacitors",
                (f"CM noise dominates at {fmt_freq(f.worst_freq_hz)} - it is driven by switch-node dv/dt through "
                 f"parasitic capacitance to chassis ({_fmt_eng(circ.switch_node_to_chassis_f, 'F') if circ else '?'}). "
                 f"A CM choke (1-10 mH) plus Y-caps to chassis typically gives 20-40 dB. Respect touch-current "
                 f"limits on Y-capacitance for mains equipment."),
                circ.name if circ else "", "Filtering", 1, "20-40 dB", "Medium", [f.title]))
            out.append(Mitigation(
                "Reduce switch-node capacitance to chassis",
                ("Minimise switch-node copper area, avoid heatsinks tied to the switch node or use an insulating "
                 "pad with a grounded screen layer, and keep the node away from the enclosure wall."),
                circ.name if circ else "", "PCB layout", 2, "6 dB per halving of capacitance", "Medium", [f.title]))
            out.append(Mitigation(
                "Snubber / gate-resistor to slow dv/dt",
                "An RC snubber or larger gate resistance reduces high-frequency switch-node harmonics "
                "(trade-off: efficiency).", circ.name if circ else "", "Source", 2, "5-15 dB above 5 MHz", "Low",
                [f.title]))
        if circ and not any(s.spread_spectrum_pct for s in circ.sources):
            out.append(Mitigation(
                "Frequency dithering of the switching converter",
                "Spread-spectrum modulation of f_sw (+/- 5-10 %) lowers QP/AV readings, often 5-10 dB at 150 kHz-30 MHz.",
                circ.name if circ else "", "Source", 3, "5-10 dB", "Low", [f.title]))
    return out


# --------------------------------------------------------------------------- enclosure
@register_rule
def enclosure_rules(product: Product, findings: List[Finding]) -> List[Mitigation]:
    out = []
    enc = product.enclosure
    for f in _needs_work(findings, "enclosure_se"):
        req = f.data.get("required_se_db", 40) + 6
        weakest = f.data.get("weakest_path", "")
        fw = f.worst_freq_hz
        if weakest.startswith("aperture:"):
            ap = next(a for a in enc.apertures if f"aperture:{a.name}" == weakest)
            L_max = max_aperture_for_se(req + 10 * math.log10(max(ap.count, 1)), fw)
            out.append(Mitigation(
                f"Reduce aperture '{ap.name}' size",
                (f"{ap.length_m * 1e3:.0f} mm aperture limits SE at {fmt_freq(fw)}. Split it into slots/holes "
                 f"<= {L_max * 1e3:.1f} mm long, or use honeycomb (waveguide-below-cutoff, depth >= 3x cell size), "
                 f"conductive mesh / ITO window for displays, or EMI-gasketed covers."),
                enc.name, "Shielding", 1, f"to reach {req:.0f} dB", "Medium", [f.title]))
        elif weakest.startswith("seam:"):
            sm = next(s for s in enc.seams if f"seam:{s.name}" == weakest)
            pitch = max_aperture_for_se(req, fw)
            out.append(Mitigation(
                f"Tighten seam '{sm.name}'",
                (f"Fastener pitch {sm.fastener_pitch_m * 1e3:.0f} mm leaks at {fmt_freq(fw)}. Reduce pitch to "
                 f"<= {pitch * 1e3:.0f} mm, or fit conductive gasket (finger stock, conductive elastomer, "
                 f"wire mesh). Ensure mating surfaces are conductive (chromate/alodine, not anodised/painted)."),
                enc.name, "Shielding", 1, f"to reach {req:.0f} dB", "Medium", [f.title]))
        else:
            out.append(Mitigation(
                "Increase wall shielding",
                ("Solid-wall SE is limiting: increase thickness, use a higher-conductivity material, or - for "
                 "plastic housings - add conductive coating (Ni/Cu paint, vacuum metallisation, < 1 ohm/sq)."),
                enc.name, "Shielding", 1, None, "High", [f.title]))
    for f in findings:
        if f.check == "cavity_resonance":
            modes = f.data.get("modes", [])
            sources_near = []
            for c in product.circuits:
                for s in c.sources:
                    for m in modes:
                        n = round(m / s.frequency)
                        if n >= 1 and abs(n * s.frequency - m) / m < 0.02:
                            sources_near.append(f"{c.name}/{s.name} harmonic {n} ~ {fmt_freq(m)}")
            if sources_near:
                out.append(Mitigation(
                    "Damp enclosure cavity resonance",
                    ("Source harmonics fall on enclosure resonances: " + "; ".join(sources_near[:4])
                     + ". Add RF absorber sheet on the lid, sub-divide the cavity with a partition, or shift the "
                       "clock frequency."),
                    enc.name if enc else "enclosure", "Shielding", 2, "10-20 dB near resonance", "Low", [f.title]))
    return out


# --------------------------------------------------------------------------- susceptibility
@register_rule
def eed_rules(product: Product, findings: List[Finding]) -> List[Mitigation]:
    out = []
    for f in _needs_work(findings, "eed_safety"):
        need = _target(f, 0)
        L = f.data.get("lead_length_m", 0.5)
        if not f.data.get("shielded"):
            out.append(Mitigation(
                "Shield EED firing leads (twisted pair + 360-degree overall shield)",
                ("Use a twisted pair inside an overall braid terminated 360 degrees at both the firing unit and "
                 "the EED connector/backshell; this converts most induced energy to CM which the bridgewire "
                 "does not see. Typical 30-60 dB."),
                f.subject, "Cabling", 1, "30-60 dB", "Medium", [f.title]))
        if not f.data.get("has_filter"):
            out.append(Mitigation(
                "Add RF filter / ferrite at the EED",
                ("Fit a ferrite-bead or RF attenuator (lossy line, feedthrough C to case) at the initiator, "
                 f"sized for >= {need:.0f} dB at {fmt_freq(f.worst_freq_hz)}. Verify the filter's own power "
                 "rating (Filter Power Rating assessment) and that it does not affect firing pulse."),
                f.subject, "Filtering", 1, f"{need:.0f} dB", "Medium", [f.title]))
        out.append(Mitigation(
            "Reduce lead length / exposed loop",
            (f"Current lead length {L:g} m. Coupling peaks where the leads approach lambda/2 "
             f"({fmt_freq(C0 / (2 * L))}); shorter leads move resonance above the worst environment band and "
             "reduce received power."),
            f.subject, "Cabling", 2, None, "Low", [f.title]))
        out.append(Mitigation(
            "Procedural controls (HERO)",
            ("Keep shorting plugs / Faraday caps fitted until final arming, define emitter exclusion zones and "
             "restrict transmissions during handling; document in the HERO safety assessment."),
            f.subject, "Process", 2, None, "Low", [f.title]))
    return out


@register_rule
def immunity_rules(product: Product, findings: List[Finding]) -> List[Mitigation]:
    out = []
    for f in _needs_work(findings, "victim_immunity"):
        need = _target(f, 0)
        fw = f.worst_freq_hz or 1e8
        fc = lc_corner_for_attenuation(need, fw, 1)
        R = 100.0
        C = 1 / (2 * math.pi * fc * R)
        out.append(Mitigation(
            "Add input RC / ferrite filter at the victim",
            (f"Needs {need:.0f} dB at {fmt_freq(fw)}: an RC with fc <= {fmt_freq(fc)} (e.g. R = 100 ohm, "
             f"C >= {_fmt_eng(C, 'F')}) at the connector, or a ferrite + capacitor pi. Check signal bandwidth."),
            f.subject, "Filtering", 1, f"{need:.0f} dB", "Low", [f.title]))
        out.append(Mitigation(
            "Use differential / balanced signalling or shielded twisted pair",
            "Balanced inputs reject CM pickup (CMRR 30-60 dB at RF is common with a CM choke).",
            f.subject, "Cabling", 2, "20-40 dB", "Medium", [f.title]))
        out.append(Mitigation(
            "Firmware robustness",
            "Average / median filter ADC readings, add plausibility checks, watchdog and brown-out handling so "
            "residual disturbance does not cause a functional failure (performance criterion A/B).",
            f.subject, "Source", 3, None, "Low", [f.title]))
    for f in _needs_work(findings, "filter_power"):
        out.append(Mitigation(
            "Up-rate filter components",
            ("Element dissipation exceeds rating under the RF environment. Use higher power-rated resistive / "
             "ferrite elements, distribute dissipation across stages, or add upstream shielding."),
            f.subject, "Filtering", 1, None, "Low", [f.title]))
    return out


# --------------------------------------------------------------------------- good practice
@register_rule
def design_practice_rules(product: Product, findings: List[Finding]) -> List[Mitigation]:
    out = []
    for c in product.circuits:
        pcb = c.pcb
        if pcb.get("layers") and int(pcb["layers"]) < 4 and any(s.frequency > 20e6 for s in c.sources):
            out.append(Mitigation(
                "Move to a 4+ layer stack-up", f"{c.name} has {pcb['layers']} layers with >20 MHz clocks; a "
                "dedicated ground plane adjacent to signal layers is the single most effective EMC layout measure.",
                c.name, "PCB layout", 2, "10-20 dB", "High"))
        if pcb.get("decoupling") is False:
            out.append(Mitigation("Review decoupling", "Place 100 nF + 1 nF per IC power pin with via-in-pad to "
                                  "plane; keep loop < 2 mm.", c.name, "PCB layout", 2, None, "Low"))
        if pcb.get("stitching_vias") is False:
            out.append(Mitigation("Add ground stitching vias", "Stitch ground pours at <= lambda/20 of the highest "
                                  "harmonic of concern (e.g. <= 15 mm for 1 GHz) and along board edges.",
                                  c.name, "PCB layout", 3, None, "Low"))
    for cab in product.cables:
        if cab.exits_enclosure and not cab.filter and not cab.shielded and not cab.ferrite_impedance_ohm:
            out.append(Mitigation(
                f"Provide interface protection for '{cab.name}'",
                "Unfiltered, unshielded cable crossing the enclosure boundary: it is both an emission antenna and "
                "an immunity entry point (ESD, EFT, surge, RF). Plan filter + TVS footprints at the connector.",
                cab.name, "Filtering", 3, None, "Low"))
    return out


class MitigationAdvisor:
    def __init__(self, rules=None):
        self.rules = rules if rules is not None else RULES

    def advise(self, product: Product, findings: List[Finding]) -> List[Mitigation]:
        out: List[Mitigation] = []
        for rule in self.rules:
            try:
                out.extend(rule(product, findings) or [])
            except Exception as exc:  # a bad plugin rule should not break the report
                out.append(Mitigation(f"Rule {getattr(rule, '__name__', rule)} failed", str(exc), "advisor",
                                      "Process", 9, effort="-"))
        # de-duplicate by (title, applies_to)
        seen, uniq = set(), []
        for m in sorted(out, key=lambda m: (m.priority, m.category, m.title)):
            key = (m.title, m.applies_to)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(m)
        return uniq
