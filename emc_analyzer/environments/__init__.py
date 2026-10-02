"""RF environment library (for EED / HERO and field-immunity assessments)."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List

from ..core.models import Environment
from ..standards import Standard, load_structured

BUILTIN_DIR = Path(__file__).parent
USER_DIR = Path.home() / ".emc_analyzer" / "environments"


class EnvironmentLibrary:
    def __init__(self, extra_dirs: Iterable[Path] = ()):
        self.dirs = [BUILTIN_DIR, USER_DIR, *[Path(p) for p in extra_dirs]]
        self.environments: Dict[str, Environment] = {}
        self.errors: List[str] = []
        self.reload()

    def reload(self):
        self.environments.clear()
        for d in self.dirs:
            if not d.is_dir():
                continue
            for p in sorted(d.iterdir()):
                if p.suffix.lower() in (".yaml", ".yml", ".json"):
                    try:
                        env = Environment.from_dict(load_structured(p))
                        self.environments[env.name] = env
                    except Exception as exc:
                        self.errors.append(f"{p.name}: {exc}")

    def names(self) -> List[str]:
        return sorted(self.environments)

    def get(self, name: str):
        return self.environments.get(name)


def environment_from_standard(std: Standard) -> Environment:
    """Turn a radiated-immunity standard (V/m) into an Environment."""
    return Environment(name=std.name, unit="V/m",
                       bands=[(s[0], s[1], max(s[2], s[3])) for s in std.segments],
                       source=f"Standard {std.id}")
