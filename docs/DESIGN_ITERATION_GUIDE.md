# Design iteration guide: from model to compliant product

The analyser works alongside a design loop:

```
   Concept ─▶ Model & assess ─▶ Mitigate in design ─▶ Prototype A ─▶ Measure & correlate
      ▲                                                                     │
      └───── Formal test ◀── Pre-compliance ◀── Prototype B ◀── Trial fixes ┘
```

## 1. Before layout (cheapest place to fix EMC)
* Enter clocks and switchers with realistic rise times, plus intended cable lengths, in the project.
* Run all target standards and treat every FAIL or MARGINAL result as a design requirement:
  * Choose stack-up, ground strategy and connector filtering now.
  * Reserve **footprints for every candidate mitigation**: CM chokes, Y-caps, ferrite pads, RC filters at inputs, shield-can fences, series-termination resistors. Fit them as DNP or 0 Ω so prototype fixes become rework, not a re-spin.
* Enclosure: set `required_se_db` from the radiated-emission shortfall of internal sources. Size apertures and seams with the advisor's numbers.

## 2. Prototype A: measure what the model predicts
| Measurement | Kit | Compare with |
|---|---|---|
| Near-field scan | H/E probes + spectrum analyser | Loop contributors in the RE plot |
| CM current on each cable | RF current clamp | The advisor's derived µA limit per cable |
| Conducted emissions | LISN + limiter + SA (DM/CM splitter if available) | CE plot (DM vs CM dominance) |
| Shielding | Comb generator inside the enclosure, receive antenna outside | Enclosure SE plot, cavity resonances |
| RF immunity | BCI / CDN injection while monitoring victims | Victim thresholds in the model |
| EED | Inert EED with thermocouple / fibre-optic sensor | Safe power density curve |

Rules of thumb for converting measurements:
* CM current to field (3 m, cable shorter than λ/2): `E [V/m] ≈ 1.257e-6 · f · L · I / 3`. For CISPR 32 Class B at 100 MHz with a 1 m cable, the limit is only a few µA (about 4 µA).
* A near-field probe reading is relative. Use it for before/after deltas, not absolute pass/fail.

## 3. Correlate the model
Update the project with measured rise times, CM capacitances, cable CM impedance and victim thresholds. Re-run the analysis. When the predicted and measured worst frequencies agree within about 6 dB, the advisor's sizing can be trusted for the next iteration.

## 4. Trial fixes, one at a time
Apply the advisor's Priority-1 items individually and log the dB change of each. Typical rework kit: snap-on ferrites, copper tape (to prove a seam or aperture), spare filter capacitors and inductors, gasket strip, braid, and 0 Ω/R swaps for edge-rate control.

## 5. Prototype B and pre-compliance
Fold the proven fixes into the layout and mechanical design. Aim for at least 6 dB emission margin and criterion A immunity at the specified levels. Add transient tests (ESD, EFT, surge) here; they are not modelled.

## 6. Formal test
Write the test plan or EMC control plan (configuration, cabling, operating modes, monitoring, pass criteria). Bring the rework kit. Archive the final model, measurements and report.

## Mitigation hierarchy (most effective and cheapest first)
1. **Source**: lower edge rates, spread spectrum, smaller hot loops, slower dv/dt, snubbers.
2. **Layout**: solid reference plane, return paths under signals, clocks away from connectors and board edges, stitching, decoupling.
3. **Interface**: filter or ground all cable conductors to chassis at the enclosure boundary (filtered connectors, CM chokes, Y-caps, feed-throughs).
4. **Cable**: shielded cable with 360° terminations, twisted pairs, ferrites.
5. **Enclosure**: reduce aperture and seam lengths, gaskets, honeycomb vents, conductive coatings, absorber for cavity resonances.
6. **Procedural** (EED/HERO): shorting plugs, emitter exclusion zones, handling restrictions.
