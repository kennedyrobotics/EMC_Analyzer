# EMC Analyzer

Kennedy Robotics EMI/EMC design-assessment toolkit. It plays the same role as tools like *EMC Analysis Software (EAS) v3.3*, but it is open, scriptable and extensible.

1. **Load a design**: YAML/JSON project, Python model, MATLAB `.mat` / `.m`, or SPICE netlist.
2. **Pick standards** from a library of limit lines (CISPR 32, MIL-STD-461G, IEC 61000-4-x, and your own) and an RF environment.
3. **Assess** conducted and radiated emissions, enclosure shielding, cavity resonances, RF immunity of sensitive inputs, EED (squib) RF safety and filter power rating.
4. **Get mitigations**: ranked, sized fixes (for example "ferrite ≥ 450 Ω at 75 MHz", "LC corner ≤ 48 kHz", "split vent slots to ≤ 9 mm").
5. **Get a post-prototype plan**: what to measure on prototype A, how to correlate the model, how to trial fixes, then Rev B, pre-compliance and formal test.

> Results are first-order analytical estimates (Paul / Ott / Schelkunoff models). Use them to rank risks and size fixes early. They do **not** replace pre-compliance or accredited testing. Limit lines marked `verify: true` were entered from general knowledge. Check them against the edition of the standard you certify to.

---

## Quick start (Windows)

```bat
cd D:\KennedyRobotics\Research\EMC_Analyzer
setup_env.bat              :: creates .venv and installs requirements (one-off)
run_gui.bat                :: launches the GUI
run_example_report.bat     :: headless run -> reports\robot_controller.html
run_tests.bat
```

With Anaconda:

```bat
conda create -n emc python=3.11 -y
conda activate emc
pip install -r requirements.txt
python -m emc_analyzer gui examples\robot_controller.yaml
```

## Command line

```bat
python -m emc_analyzer standards                         :: list the standards library
python -m emc_analyzer environments                      :: list RF environments
python -m emc_analyzer analyze examples\robot_controller.yaml --report out.html --csv out.csv
python -m emc_analyzer analyze examples\buck_converter.cir -s CISPR32_B_CE_QP -s CISPR32_B_RE
python -m emc_analyzer analyze examples\eed_firing_circuit.yaml --coupling matched
python -m emc_analyzer analyze base.yaml extra_circuit.py   :: later files merge into the first
python -m emc_analyzer analyze design.yaml --fail-exit      :: exit 1 on FAIL (CI gate)
```

## GUI tour

| Left panel | Purpose |
|---|---|
| Description | Product, platform/vehicle, system, classification, measurement distance |
| Standards | Tick the standards/limit lines; choose an RF environment, EED coupling model, required SE |
| Design model | Tree of circuits, sources, loops, EEDs, victims, cables, filters, enclosure. Right-click to add, duplicate or delete; edit properties below (engineering units such as `4.7u` and `25MHz` are accepted) |
| YAML | The whole design as text; edit and apply |

| Right panel | Purpose |
|---|---|
| Summary | PASS / MARGINAL / FAIL table with margin and worst frequency. Double-click a row to open its graph |
| Graph | Emission vs limit, SE vs requirement, safe power density vs RF environment (EAS-style), with manual Y-axis range |
| Mitigations | Prioritised fixes with rationale, expected dB and effort |
| Next steps | Post-prototype iteration plan generated from the findings |

**File → Import into current design** merges a Python, MATLAB or SPICE file into the open project. For example, keep the enclosure in YAML and pull a new circuit from a netlist.

## Design inputs

### YAML project (native)
See `examples/robot_controller.yaml` (digital + SMPS + enclosure + cables + filter) and `examples/eed_firing_circuit.yaml` (EED/HERO, like the EAS "EED" circuit type).

Key objects:

* `circuits[]` has `sources[]` (clock / switching / pwm / sinusoid: frequency, amplitude, rise time, duty, current, spread-spectrum %), `loops[]` (area and the source driving it), `eeds[]`, `victims[]`, SMPS parameters (input cap, ESR/ESL, switch-node-to-chassis capacitance) and `pcb` practice flags (`layers`, `ground_plane`, `decoupling`, `stitching_vias`, `cm_coupling`).
* `cables[]`: length, shielded, termination (`360` / `pigtail` / `none`), transfer impedance, ferrite, filter, connected circuit, whether it exits the enclosure.
* `filters[]`: ladder of `L` / `C` / `R` / `FB` elements (series/shunt) with ESR, ESL and parasitic C; source/load impedance; DM/CM; power ratings.
* `enclosure`: material, thickness, dimensions, apertures (length, count, waveguide depth), seams (fastener pitch, gasket), conductive coating for plastics.
* `environment`: RF environment bands in W/m² or V/m.

### Python model
Define `build_product()` (or `PRODUCT`), or partial builders `build_circuit()`, `build_enclosure()`, `build_cables()`, `build_filters()`. See `examples/python_model_sweep.py`; running it directly performs a parametric sweep.

### MATLAB
* `.mat`: save a struct named `product` (or `circuit` / `enclosure` to merge) whose field names match the YAML. Needs `scipy`.
* `.m`: a no-argument function returning that struct (`examples/matlab_design.m`). Needs MATLAB Engine for Python (`pip install matlabengine`, matching your MATLAB release).

### SPICE netlist
`PULSE()` and `SIN()` sources become noise sources, and R/L/C parts can be grouped into filters. `*EMC` comment lines add what EMC needs (loop areas, cables, CM capacitance). See `examples/buck_converter.cir`.

## Standards and environments
Each limit line is a small YAML file:

```yaml
id: MY_CUSTOMER_RE
name: Customer spec - radiated emissions @ 1 m
family: Customer
type: radiated_emission          # radiated_emission | conducted_emission | radiated_immunity | conducted_immunity
unit: dBuV/m
distance_m: 1
segments:                        # [f_start, f_stop, level_start, level_stop], log-frequency interpolation
  - [30e6, 230e6, 40, 40]
  - [230e6, 1e9, 47, 47]
verify: false
```

Drop files into `%USERPROFILE%\.emc_analyzer\standards\` (all projects) or a `standards\` folder next to your project file (that project only), then use **Standards → Reload**. RF environments work the same way in `environments\`.

Built-in: CISPR 32 Class A/B radiated (30 MHz–1 GHz and 1–6 GHz) and conducted (QP/AV), MIL-STD-461G CE102, RE102 (aircraft internal), RS103 (example level), IEC 61000-4-3 levels 1–4, IEC 61000-4-6 levels 1–3. Environments: the Category 1 example digitised from your EAS screen, and a generic industrial 10 V/m environment.

## Extending
* **New analysis**: write a function decorated with `@register_analysis(...)` in a `.py` file in `%USERPROFILE%\.emc_analyzer\plugins\` or `<project>\plugins\`. See `emc_analyzer/plugins/example_crosstalk_plugin.py`.
* **New mitigation rule**: decorate a function with `@register_rule` (`emc_analyzer.mitigation`).
* **New importer** (for example KiCad, Altium, STEP metadata): `@register_importer("name", [".ext"])`.

See `docs/ARCHITECTURE.md` and `docs/DESIGN_ITERATION_GUIDE.md`.

## Models used
| Check | Model |
|---|---|
| Source spectra | Trapezoidal pulse-train harmonics (duty, rise/fall), spread-spectrum reduction vs receiver RBW |
| Conducted emissions | DM: pulsed input current → input capacitor ‖ LISN through the input filter (ABCD). CM: switch-node dv/dt through parasitic C into the LISN |
| Radiated emissions | DM loop `E = 1.316e-14·f²·A·I/r`; CM cable `E = 1.257e-6·f·L·I_cm/r` (L capped at λ/2); enclosure SE; shield transfer impedance, pigtails, ferrites, filters |
| Shielding | Schelkunoff absorption, reflection and multiple reflections (plane-wave and magnetic near field); thin-film coating; apertures `20log(λ/2L)` with coherent-count and waveguide-below-cutoff terms; seams; power-summed leakage |
| Cavity | Rectangular-cavity TE/TM resonances vs source harmonics |
| EED safety | Lead dipole (short-dipole reactance, resonant λ/2) or matched-aperture coupling; safe power density = NFP / margin / coupling; compared with the RF environment (EAS-style plot) |
| Immunity | Field → cable pickup (effective height ≤ λ/π) or CDN EMF into the victim input impedance, with filters and shields; 80 % AM peak factor |
| Filter power | Ladder current/voltage walk to get per-element dissipation under the RF environment |
