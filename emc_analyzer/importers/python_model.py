"""Python model importer.

A Python model file may define any of:

    def build_product() -> Product | dict        # complete product
    PRODUCT = Product(...) | {...}                # complete product
    def build_circuit() -> Circuit | dict | list  # merged into the current product
    def build_enclosure() -> Enclosure | dict     # replaces the current enclosure
    def build_cables() -> list[Cable | dict]
    def build_filters() -> list[Filter | dict]

This lets you generate designs parametrically (e.g. sweep loop area or filter
values in a loop, or compute parameters from your own design scripts / numpy /
scikit-rf models) and hand them to the analyser.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Optional

from ..core.models import Cable, Circuit, Enclosure, Filter, Product
from . import register_importer


def _as(cls, obj):
    return obj if isinstance(obj, cls) else cls.from_dict(obj)


def _listify(x):
    return x if isinstance(x, (list, tuple)) else [x]


@register_importer("python", [".py"], "Python model")
def load_python_model(path: Path, current: Optional[Product] = None) -> Product:
    spec = importlib.util.spec_from_file_location(f"emc_model_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    finally:
        sys.path.remove(str(path.parent))

    if hasattr(mod, "build_product"):
        return _as(Product, mod.build_product())
    for name in ("PRODUCT", "product"):
        if hasattr(mod, name):
            return _as(Product, getattr(mod, name))

    prod = current or Product(name=path.stem)
    found = False
    if hasattr(mod, "build_circuit"):
        for c in _listify(mod.build_circuit()):
            c = _as(Circuit, c)
            prod.circuits = [x for x in prod.circuits if x.name != c.name] + [c]
        found = True
    if hasattr(mod, "build_enclosure"):
        prod.enclosure = _as(Enclosure, mod.build_enclosure())
        found = True
    if hasattr(mod, "build_cables"):
        for c in _listify(mod.build_cables()):
            c = _as(Cable, c)
            prod.cables = [x for x in prod.cables if x.name != c.name] + [c]
        found = True
    if hasattr(mod, "build_filters"):
        for f in _listify(mod.build_filters()):
            f = _as(Filter, f)
            prod.filters = [x for x in prod.filters if x.name != f.name] + [f]
        found = True
    if not found:
        raise ValueError(f"{path.name} defines none of build_product/PRODUCT/build_circuit/build_enclosure/"
                         f"build_cables/build_filters")
    return prod
