# Architecture

```
emc_analyzer/
├── core/
│   ├── models.py        Product → Circuit (sources, loops, EEDs, victims) / Cable / Filter / Enclosure / Environment
│   ├── results.py       Finding, Trace, Mitigation, Report, PASS/MARGINAL/FAIL classification
│   └── units.py         SI parsing ("4.7u", "25MHz"), dB helpers, frequency grids
├── standards/           StandardsLibrary + library/*.yaml limit lines
├── environments/        EnvironmentLibrary + RF environment *.yaml
├── analysis/            registry + engines
│   ├── spectrum.py      trapezoidal harmonics, spread spectrum
│   ├── filters.py       ABCD ladder model, insertion loss, element dissipation
│   ├── shielding.py     wall / aperture / seam SE, cavity resonances
│   ├── emissions.py     conducted_emissions, radiated_emissions        (registered analyses)
│   ├── susceptibility.py eed_safety, victim_immunity, filter_power      (registered analyses)
│   └── enclosure_checks.py enclosure_se, cavity_resonance               (registered analyses)
├── mitigation/
│   ├── advisor.py       rule set → sized Mitigation objects
│   └── next_steps.py    post-prototype iteration plan
├── importers/           project (yaml/json), python_model, matlab (.mat/.m), spice (.cir/.net/.sp)
├── report/              HTML (embedded plots) / CSV / JSON, shared matplotlib plotting
├── plugins/             plugin loader + example crosstalk plugin
├── gui/                 PySide6 main window, generic dataclass tree/property editor
├── engine.py            AnalysisEngine: load libraries & plugins → run analyses → advisor → next steps
└── cli.py               `python -m emc_analyzer ...`
```

## Data flow

```
 design files ──importers──▶ Product ──┐
 standards/*.yaml ──────────▶ Standard ├─▶ AnalysisContext ─▶ registered analyses ─▶ Findings
 environments/*.yaml ───────▶ Environment┘                                              │
                                                       MitigationAdvisor rules ◀────────┤
                                                       build_next_steps        ◀────────┘
                                                                  │
                                                     Report ─▶ GUI tables/plots, HTML/CSV/JSON
```

* An analysis runs when one of the selected standards has a type in its `applies_to` list, or when it is marked `always=True` and has the data it needs (enclosure, EEDs, filters with ratings).
* Each `Finding` carries plot traces and a `data` dict that the advisor reads. For example `dominant_kind = "cable"` plus the cable name leads the advisor to size a ferrite for that cable.
* The model is plain dataclasses, so the GUI editor, YAML/JSON and MATLAB structs all use the same field names.

## Extension points

| What | How |
|---|---|
| Analysis | `@register_analysis(id, title, applies_to=(...), always=False)` returning `list[Finding]` |
| Advisor rule | `@register_rule` returning `list[Mitigation]` |
| Importer | `@register_importer(name, [".ext"], description)` returning a `Product` |
| Standard | YAML file in a standards folder, or `StandardsLibrary.add(Standard(...))` |
| Environment | YAML file in an environments folder |

Plugins are discovered in `emc_analyzer/plugins/`, `~/.emc_analyzer/plugins/` and `<project>/plugins/`.

## Roadmap ideas
* KiCad / Altium importers: pull loop areas and trace lengths from the PCB, and the netlist from the schematic.
* Import measured scans (CSV from a spectrum analyser) and overlay them on predictions; auto-fit model parameters.
* Monte-Carlo / tolerance analysis of filter components; parametric sweep UI.
* Transient immunity (ESD, EFT, surge) energy-based screening.
* Lightning indirect effects (DO-160 section 22) and HIRF for aircraft.
* Hooks for full-wave solvers (openEMS) for enclosure and cable studies when first-order models are not enough.
