"""Standards library: limit lines / test levels stored as YAML or JSON files.

Search path (later entries override earlier ones with the same id):
  1. built-in   emc_analyzer/standards/library/
  2. user       ~/.emc_analyzer/standards/
  3. extra      any directories passed to StandardsLibrary(extra_dirs=[...])
                (the GUI adds  <project>/standards  automatically)

File format (YAML):
    id: CISPR32_B_RE
    name: CISPR 32 Class B - Radiated emissions
    type: radiated_emission | conducted_emission | radiated_immunity | conducted_immunity
    unit: dBuV/m | dBuV | V/m | V
    distance_m: 10            # radiated emission limits only
    segments:                 # [f_start, f_stop, level_start, level_stop], log-f interpolation
      - [30e6, 230e6, 30, 30]
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np

from ..core.units import parse_si

BUILTIN_DIR = Path(__file__).parent / "library"
USER_DIR = Path.home() / ".emc_analyzer" / "standards"

EMISSION_TYPES = ("radiated_emission", "conducted_emission")
IMMUNITY_TYPES = ("radiated_immunity", "conducted_immunity")


def load_structured(path: Path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix.lower() == ".json":
        return json.loads(text)
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ImportError("PyYAML is required for .yaml files: pip install pyyaml") from exc
    return yaml.safe_load(text)


@dataclass
class Standard:
    id: str
    name: str
    type: str
    unit: str
    segments: List[List[float]]
    family: str = ""
    detector: str = ""
    distance_m: Optional[float] = None
    notes: str = ""
    verify: bool = True
    source_file: str = ""
    meta: Dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict, source_file: str = "") -> "Standard":
        known = {"id", "name", "type", "unit", "segments", "family", "detector", "distance_m", "notes", "verify"}
        segs = [[parse_si(x) for x in s] for s in d["segments"]]
        return cls(id=str(d["id"]), name=d.get("name", d["id"]), type=d["type"], unit=d.get("unit", ""),
                   segments=segs, family=d.get("family", ""), detector=d.get("detector", ""),
                   distance_m=parse_si(d["distance_m"]) if d.get("distance_m") is not None else None,
                   notes=d.get("notes", ""), verify=bool(d.get("verify", True)), source_file=source_file,
                   meta={k: v for k, v in d.items() if k not in known})

    def to_dict(self) -> dict:
        d = {"id": self.id, "name": self.name, "family": self.family, "type": self.type, "unit": self.unit,
             "detector": self.detector, "segments": self.segments, "notes": self.notes, "verify": self.verify}
        if self.distance_m is not None:
            d["distance_m"] = self.distance_m
        d.update(self.meta)
        return d

    # ------------------------------------------------------------------
    @property
    def f_min(self) -> float:
        return min(s[0] for s in self.segments)

    @property
    def f_max(self) -> float:
        return max(s[1] for s in self.segments)

    @property
    def is_emission(self) -> bool:
        return self.type in EMISSION_TYPES

    @property
    def is_immunity(self) -> bool:
        return self.type in IMMUNITY_TYPES

    def level(self, f, distance_m: Optional[float] = None) -> np.ndarray:
        """Limit at frequencies f (NaN outside the standard's range).

        For radiated emission limits a 20log(d_std/d) distance correction is
        applied when ``distance_m`` differs from the standard's distance.
        """
        f = np.atleast_1d(np.asarray(f, dtype=float))
        out = np.full(f.shape, np.nan)
        for f0, f1, l0, l1 in self.segments:
            m = (f >= f0 * (1 - 1e-9)) & (f <= f1 * (1 + 1e-9)) & np.isnan(out)
            if not m.any():
                continue
            if f1 == f0:
                out[m] = l0
            else:
                t = (np.log10(f[m]) - math.log10(f0)) / (math.log10(f1) - math.log10(f0))
                out[m] = l0 + t * (l1 - l0)
        if distance_m and self.distance_m and self.type == "radiated_emission":
            out = out + 20 * math.log10(self.distance_m / distance_m)
        return out

    def plot_points(self, distance_m: Optional[float] = None):
        """Points for drawing the limit line, with NaN breaks between segments."""
        corr = 0.0
        if distance_m and self.distance_m and self.type == "radiated_emission":
            corr = 20 * math.log10(self.distance_m / distance_m)
        fs, ls = [], []
        for f0, f1, l0, l1 in self.segments:
            seg_f = np.logspace(math.log10(f0), math.log10(f1), 30)
            t = (np.log10(seg_f) - math.log10(f0)) / max(1e-12, math.log10(f1) - math.log10(f0))
            fs.extend(seg_f.tolist() + [np.nan])
            ls.extend((l0 + t * (l1 - l0) + corr).tolist() + [np.nan])
        return np.array(fs), np.array(ls)


class StandardsLibrary:
    def __init__(self, extra_dirs: Iterable[Path] = ()):
        self.dirs = [BUILTIN_DIR, USER_DIR, *[Path(p) for p in extra_dirs]]
        self.standards: Dict[str, Standard] = {}
        self.errors: List[str] = []
        self.reload()

    def reload(self):
        self.standards.clear()
        self.errors.clear()
        for d in self.dirs:
            if not d.is_dir():
                continue
            for p in sorted(d.iterdir()):
                if p.suffix.lower() not in (".yaml", ".yml", ".json"):
                    continue
                try:
                    data = load_structured(p)
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        s = Standard.from_dict(item, str(p))
                        self.standards[s.id] = s
                except Exception as exc:  # keep loading the rest
                    self.errors.append(f"{p.name}: {exc}")

    def add(self, std: Standard):
        self.standards[std.id] = std

    def get(self, sid: str) -> Standard:
        try:
            return self.standards[sid]
        except KeyError:
            raise KeyError(f"Unknown standard '{sid}'. Available: {', '.join(sorted(self.standards))}") from None

    def list(self, type_: Optional[str] = None) -> List[Standard]:
        return sorted((s for s in self.standards.values() if type_ is None or s.type == type_),
                      key=lambda s: (s.family, s.id))

    def families(self) -> List[str]:
        return sorted({s.family for s in self.standards.values()})

    def save_user_standard(self, std: Standard) -> Path:
        import yaml  # type: ignore
        USER_DIR.mkdir(parents=True, exist_ok=True)
        path = USER_DIR / f"{std.id}.yaml"
        path.write_text(yaml.safe_dump(std.to_dict(), sort_keys=False), encoding="utf-8")
        self.add(std)
        return path
