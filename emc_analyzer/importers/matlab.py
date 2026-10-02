"""MATLAB importers.

.mat files (needs scipy)
    Save a struct called ``product`` (or put product fields at top level) with the
    same field names as the YAML project format, e.g. in MATLAB::

        product.name = 'Motor controller';
        product.enclosure.material = 'aluminium';
        product.enclosure.thickness_m = 1.5e-3;
        product.circuits(1).name = 'Buck';
        product.circuits(1).type = 'smps';
        product.circuits(1).sources(1).name = 'SW';
        product.circuits(1).sources(1).kind = 'switching';
        product.circuits(1).sources(1).frequency = 400e3;
        save('design.mat', 'product');

    A struct called ``circuit`` / ``enclosure`` merges into the current product.

.m files (needs MATLAB Engine for Python: ``pip install matlabengine`` matching
your MATLAB release)
    The file must be a function with no inputs returning such a struct::

        function product = my_design()
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ..core.models import Circuit, Enclosure, Product
from . import register_importer


def _mat_to_py(obj: Any) -> Any:
    """Convert scipy.io.loadmat output (squeeze_me, struct_as_record=False) to dict/list."""
    import numpy as np
    if hasattr(obj, "_fieldnames"):
        return {k: _mat_to_py(getattr(obj, k)) for k in obj._fieldnames}
    if isinstance(obj, np.ndarray):
        if obj.dtype == object or obj.dtype.names:
            return [_mat_to_py(x) for x in obj.ravel()]
        if obj.size == 1:
            return obj.item()
        return obj.tolist()
    if isinstance(obj, (np.generic,)):
        return obj.item()
    return obj


def _engine_to_py(obj: Any) -> Any:
    """Convert MATLAB Engine return values to dict/list."""
    if isinstance(obj, dict):
        return {k: _engine_to_py(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_engine_to_py(v) for v in obj]
    try:  # matlab.double etc.
        import matlab  # type: ignore
        if isinstance(obj, matlab.double):
            vals = [x for row in obj for x in row]
            return vals[0] if len(vals) == 1 else vals
    except ImportError:
        pass
    return obj


def _ensure_list(d: dict, *keys):
    for k in keys:
        if k in d and isinstance(d[k], dict):
            d[k] = [d[k]]
    return d


def _normalise(data: dict) -> dict:
    _ensure_list(data, "circuits", "cables", "filters", "standards")
    for c in data.get("circuits", []):
        _ensure_list(c, "sources", "loops", "eeds", "victims")
    for f in data.get("filters", []):
        _ensure_list(f, "elements")
    enc = data.get("enclosure")
    if isinstance(enc, dict):
        _ensure_list(enc, "apertures", "seams")
    if isinstance(data.get("standards"), str):
        data["standards"] = [data["standards"]]
    return data


def _from_struct(data: dict, current: Optional[Product], stem: str) -> Product:
    if "product" in data:
        return Product.from_dict(_normalise(data["product"]))
    if "circuit" in data or "enclosure" in data:
        prod = current or Product(name=stem)
        if "circuit" in data:
            circs = data["circuit"] if isinstance(data["circuit"], list) else [data["circuit"]]
            for c in circs:
                c = Circuit.from_dict(_normalise({"circuits": [c]})["circuits"][0])
                prod.circuits = [x for x in prod.circuits if x.name != c.name] + [c]
        if "enclosure" in data:
            prod.enclosure = Enclosure.from_dict(_normalise({"enclosure": data["enclosure"]})["enclosure"])
        return prod
    return Product.from_dict(_normalise(data))


@register_importer("matlab_mat", [".mat"], "MATLAB data file")
def load_mat(path: Path, current: Optional[Product] = None) -> Product:
    try:
        from scipy.io import loadmat
    except ImportError as exc:
        raise ImportError("Reading .mat files needs scipy: pip install scipy") from exc
    raw = loadmat(str(path), squeeze_me=True, struct_as_record=False)
    data = {k: _mat_to_py(v) for k, v in raw.items() if not k.startswith("__")}
    return _from_struct(data, current, path.stem)


@register_importer("matlab_m", [".m"], "MATLAB function (MATLAB Engine)")
def load_m(path: Path, current: Optional[Product] = None) -> Product:
    try:
        import matlab.engine  # type: ignore
    except ImportError as exc:
        raise ImportError("Running .m files needs MATLAB Engine for Python (pip install matlabengine), "
                          "or save your struct to a .mat file instead.") from exc
    eng = matlab.engine.start_matlab()
    try:
        eng.addpath(str(path.parent), nargout=0)
        result = getattr(eng, path.stem)(nargout=1)
    finally:
        eng.quit()
    data = _engine_to_py(result)
    if isinstance(data, dict) and not {"product", "circuit", "enclosure"} & set(data):
        data = {"product": data}
    return _from_struct(data, current, path.stem)
