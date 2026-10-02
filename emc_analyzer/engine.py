"""Top-level analysis orchestration."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Union

from .analysis import REGISTRY, AnalysisContext
from .core.models import Environment, Product
from .core.results import Finding, Report
from .environments import EnvironmentLibrary
from .mitigation import MitigationAdvisor, build_next_steps
from .plugins import load_plugins
from .standards import StandardsLibrary

DISCLAIMER = ("Results are first-order engineering estimates (analytical models after Paul, Ott and Schelkunoff) "
              "intended to rank risks and guide design. They do not replace pre-compliance or accredited testing. "
              "Limit lines flagged 'verify' must be checked against the current edition of each standard.")


class AnalysisEngine:
    def __init__(self, extra_standard_dirs: Iterable[Path] = (), extra_env_dirs: Iterable[Path] = (),
                 plugin_dirs: Iterable[Path] = ()):
        self.plugin_messages = load_plugins(plugin_dirs)
        self.standards = StandardsLibrary(extra_standard_dirs)
        self.environments = EnvironmentLibrary(extra_env_dirs)
        self.advisor = MitigationAdvisor()

    def analyses(self):
        return dict(REGISTRY)

    def run(self, product: Product, standard_ids: Optional[Sequence[str]] = None,
            environment: Union[None, str, Environment] = None, settings: Optional[Dict] = None,
            analyses: Optional[Sequence[str]] = None) -> Report:
        ids = list(standard_ids if standard_ids is not None else product.standards)
        stds = [self.standards.get(s) for s in ids]
        env = environment
        if isinstance(env, str):
            env = self.environments.get(env)
        if env is None:
            env = product.environment
        ctx = AnalysisContext(product, stds, env, dict(settings or {}))
        types = {s.type for s in stds}
        findings: List[Finding] = []
        notes = [DISCLAIMER]
        for spec in REGISTRY.values():
            if analyses is not None and spec.id not in analyses:
                continue
            if not (spec.always or types.intersection(spec.applies_to)):
                continue
            try:
                findings.extend(spec.fn(ctx) or [])
            except Exception as exc:
                notes.append(f"Analysis '{spec.id}' failed: {exc!r}")
        unverified = [s.id for s in stds if s.verify]
        if unverified:
            notes.append("Verify limit values for: " + ", ".join(unverified))
        notes.extend(self.plugin_messages)
        order = {"FAIL": 0, "MARGINAL": 1, "PASS": 2, "INFO": 3}
        findings.sort(key=lambda f: (order.get(f.status, 9), f.margin_db if f.margin_db is not None else 1e9))
        report = Report(product.name, findings, standards=ids, notes=notes)
        report.mitigations = self.advisor.advise(product, findings)
        report.next_steps = build_next_steps(product, findings)
        return report


def run_analysis(product: Product, standard_ids=None, environment=None, settings=None) -> Report:
    return AnalysisEngine().run(product, standard_ids, environment, settings)
