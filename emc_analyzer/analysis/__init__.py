"""Analysis registry.

An analysis is a function ``fn(ctx: AnalysisContext) -> list[Finding]``.
Register new analyses (including from plugin files) with::

    from emc_analyzer.analysis import register_analysis

    @register_analysis("my_check", "My custom check", applies_to=("radiated_emission",))
    def my_check(ctx):
        ...
        return [Finding(...)]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from ..core.models import Environment, Product
from ..core.results import Finding


@dataclass
class AnalysisContext:
    product: Product
    standards: list                       # list[Standard]
    environment: Optional[Environment] = None
    settings: Dict = field(default_factory=dict)

    def setting(self, key, default=None):
        return self.settings.get(key, default)

    def standards_of(self, *types: str):
        return [s for s in self.standards if s.type in types]


@dataclass
class AnalysisSpec:
    id: str
    title: str
    fn: Callable[[AnalysisContext], List[Finding]]
    applies_to: Sequence[str] = ()       # standard types that trigger it ('' = always)
    always: bool = False
    description: str = ""


REGISTRY: Dict[str, AnalysisSpec] = {}


def register_analysis(id: str, title: str, applies_to: Sequence[str] = (), always: bool = False,
                      description: str = ""):
    def deco(fn):
        REGISTRY[id] = AnalysisSpec(id, title, fn, tuple(applies_to), always, description or (fn.__doc__ or ""))
        return fn
    return deco


def _load_builtin():
    from . import emissions, susceptibility, enclosure_checks  # noqa: F401


_load_builtin()
