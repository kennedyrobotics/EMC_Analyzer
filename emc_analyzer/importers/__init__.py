"""Design importers.

Every importer has the signature ``fn(path: Path, current: Product | None) -> Product``.
Importers that only bring in part of a design (e.g. one circuit from a SPICE
netlist) merge it into ``current`` and return it.

Built-in:
  .yaml/.yml/.json   native project file
  .py                Python model (build_product() / PRODUCT / build_circuit() / build_enclosure())
  .mat               MATLAB struct file (scipy)
  .m                 MATLAB function via MATLAB Engine for Python (optional)
  .cir/.net/.sp/.spice  SPICE netlist with *EMC annotations
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..core.models import Product


@dataclass
class ImporterSpec:
    name: str
    extensions: List[str]
    fn: Callable[[Path, Optional[Product]], Product]
    description: str = ""


IMPORTERS: Dict[str, ImporterSpec] = {}


def register_importer(name: str, extensions, description: str = ""):
    def deco(fn):
        IMPORTERS[name] = ImporterSpec(name, [e.lower() for e in extensions], fn, description)
        return fn
    return deco


def importer_for(path) -> ImporterSpec:
    ext = Path(path).suffix.lower()
    for spec in IMPORTERS.values():
        if ext in spec.extensions:
            return spec
    raise ValueError(f"No importer for '{ext}'. Known: " +
                     ", ".join(e for s in IMPORTERS.values() for e in s.extensions))


def import_design(path, current: Optional[Product] = None) -> Product:
    return importer_for(path).fn(Path(path), current)


def file_filter() -> str:
    """Qt file-dialog filter string."""
    parts = [f"{s.description or s.name} ({' '.join('*' + e for e in s.extensions)})" for s in IMPORTERS.values()]
    every = " ".join("*" + e for s in IMPORTERS.values() for e in s.extensions)
    return ";;".join([f"All supported ({every})", *parts, "All files (*)"])


from . import project, python_model, matlab, spice  # noqa: E402,F401
