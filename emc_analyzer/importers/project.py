"""Native project files (YAML / JSON)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..core.models import Product
from ..standards import load_structured
from . import register_importer


@register_importer("project", [".yaml", ".yml", ".json"], "EMC project file")
def load_project(path: Path, current: Optional[Product] = None) -> Product:
    data = load_structured(path)
    if "product" in data and isinstance(data["product"], dict):
        data = data["product"]
    return Product.from_dict(data)


def save_project(product: Product, path) -> Path:
    path = Path(path)
    data = product.to_dict()
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(data, indent=2, default=float), encoding="utf-8")
    else:
        import yaml  # type: ignore
        path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=None), encoding="utf-8")
    return path
