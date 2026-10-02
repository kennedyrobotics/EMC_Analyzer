"""Plugin loader.

Any ``*.py`` file in these folders is imported at start-up:
  * emc_analyzer/plugins/            (built-in examples, files not starting with '_')
  * ~/.emc_analyzer/plugins/
  * folders passed by the caller (the GUI adds <project folder>/plugins)

A plugin can:
  * register analyses   -> ``from emc_analyzer.analysis import register_analysis``
  * register advisor rules -> ``from emc_analyzer.mitigation import register_rule``
  * register importers  -> ``from emc_analyzer.importers import register_importer``
  * add standards programmatically via ``emc_analyzer.standards.Standard``
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Iterable, List

BUILTIN_DIR = Path(__file__).parent
USER_DIR = Path.home() / ".emc_analyzer" / "plugins"
_LOADED = set()


def load_plugins(extra_dirs: Iterable[Path] = ()) -> List[str]:
    messages = []
    for d in [BUILTIN_DIR, USER_DIR, *map(Path, extra_dirs)]:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.py")):
            if p.name.startswith("_") or str(p.resolve()) in _LOADED:
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"emc_plugin_{p.stem}", p)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
                _LOADED.add(str(p.resolve()))
                messages.append(f"Loaded plugin {p.name}")
            except Exception as exc:
                messages.append(f"Plugin {p.name} failed to load: {exc!r}")
    return messages
