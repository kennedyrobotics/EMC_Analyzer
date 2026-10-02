"""Post-prototype design-iteration plan generated from the assessment results."""
from __future__ import annotations

from typing import Dict, List

from ..core.models import Product
from ..core.results import FAIL, MARGINAL, Finding
from ..core.units import C0, fmt_freq


def _cm_current_limit_ua(limit_dbuv_m: float, f: float, length_m: float, d: float) -> float:
    e = 10 ** (limit_dbuv_m / 20) * 1e-6 * 1.414          # rms -> peak
    L = min(length_m, C0 / f / 2)
    return e * d / (1.257e-6 * f * L) * 1e6


def build_next_steps(product: Product, findings: List[Finding]) -> List[Dict]:
    bad = [f for f in findings if f.status in (FAIL, MARGINAL)]
    checks = {f.check for f in bad}
    steps: List[Dict] = []

    def add(phase, title, actions):
        steps.append({"phase": phase, "title": title, "actions": actions})

    # Phase 1 - bring-up measurements on prototype A
    p1 = ["Build at least two prototype units; keep one as an unmodified 'golden' baseline for A/B comparisons.",
          "Fit the mitigation footprints now (0-ohm/DNP filters, ferrite pads, Y-cap pads, shield-can fences) so "
          "iterations are rework, not re-spins."]
    if "radiated_emissions" in checks or not bad:
        p1.append("Near-field probe scan (H-field loop + E-field stub) over the PCB and enclosure seams with a "
                  "spectrum analyser; map hot-spots against the predicted contributors below.")
        for f in bad:
            if f.check == "radiated_emissions" and f.data.get("dominant_kind") == "cable":
                cab = product.cable(f.data["dominant"].get("cable"))
                if cab and f.worst_freq_hz:
                    lim = _cm_current_limit_ua(f.data["limit_at_worst"], f.worst_freq_hz, cab.length_m,
                                               f.data.get("distance_m", 3))
                    p1.append(f"Measure CM current on '{cab.name}' with an RF current clamp at "
                              f"{fmt_freq(f.worst_freq_hz)}; to meet {f.standard} it must be below "
                              f"~{lim:.2g} uA (derived from the limit line).")
    if "conducted_emissions" in checks:
        p1.append("Conducted pre-scan with LISN + transient limiter + spectrum analyser (peak, then QP/AV on the "
                  "worst 6 frequencies). Separate DM and CM with a DM/CM rejection network to confirm the model's "
                  "dominant mode before choosing filter parts.")
    if checks & {"victim_immunity", "eed_safety", "filter_power"}:
        p1.append("RF immunity pre-test: BCI or CDN injection (150 kHz-400 MHz) on each cable while monitoring the "
                  "victim inputs; record the threshold of upset to calibrate the victim thresholds in the model.")
    if "eed_safety" in checks or any(c.eeds for c in product.circuits):
        p1.append("Instrument an inert EED (thermocouple or fibre-optic bridgewire sensor) and measure induced "
                  "bridgewire current in a reverberation chamber / TEM cell; compare with the predicted safe power "
                  "density curve.")
    add("1. Prototype A characterisation", "Measure what the model predicts", p1)

    # Phase 2 - correlate & update model
    add("2. Model correlation", "Feed measurements back into the design model", [
        "Update source parameters (measured rise times, CM capacitances, cable CM impedance) in the project file "
        "and re-run the analysis; aim for model-to-measurement agreement within ~6 dB at the worst frequencies.",
        "Store measured traces with the project (CSV) so each iteration is traceable.",
        "Re-rank the mitigation list using the correlated model before committing to hardware changes."])

    # Phase 3 - mitigation iteration
    p3 = ["Apply the Priority-1 mitigations one at a time on the bench (ferrites, filter values, gaskets, "
          "copper tape over seams) and log the dB improvement of each - avoid stacking untested fixes."]
    if "enclosure_se" in checks:
        p3.append("Verify enclosure SE with a comb generator inside the enclosure (or IEEE 299 style "
                  "measurement) before and after aperture / seam changes.")
    if any(f.check == "cavity_resonance" for f in findings):
        p3.append("Sweep with a comb generator to locate enclosure resonances; trial absorber placement.")
    p3.append("Freeze the effective changes into the Rev B schematic / layout / mechanical drawings.")
    add("3. Mitigation trials on prototype A", "Prove each fix and its value", p3)

    # Phase 4 - Rev B and pre-compliance
    add("4. Prototype B and pre-compliance", "Close the gaps with margin", [
        "Implement layout changes (ground plane continuity, loop areas, filter placement at connectors, "
        "stitching) and mechanical changes in Rev B.",
        "Full pre-compliance run against every selected standard; target >= 6 dB margin on emissions and "
        "performance criterion A at the specified immunity levels.",
        "Add ESD (IEC 61000-4-2), EFT (-4-4) and surge (-4-5) pre-tests if the product is mains/long-cable "
        "connected - these are not modelled here."])

    # Phase 5 - formal
    add("5. Formal qualification", "Plan the accredited test", [
        "Write the EMC test plan / EMCCP (configuration, cables, operating modes, monitoring, pass/fail "
        "criteria) referencing the standards selected in this assessment.",
        "Book an accredited lab; bring the mitigation kit (ferrites, copper tape, spare filters) for "
        "on-the-day fixes.",
        "Archive the final model, measurements and this report as part of the technical construction file."])
    return steps
