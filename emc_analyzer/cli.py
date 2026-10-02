"""Command-line interface.

    python -m emc_analyzer gui [project]
    python -m emc_analyzer analyze examples/robot_controller.yaml --report out.html
    python -m emc_analyzer analyze design.mat -s CISPR32_A_RE -s CISPR32_A_CE_QP --csv out.csv
    python -m emc_analyzer standards            # list the library
    python -m emc_analyzer environments
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _engine(project_path=None):
    from .engine import AnalysisEngine
    extra = []
    if project_path:
        extra = [Path(project_path).parent]
    return AnalysisEngine(extra_standard_dirs=[d / "standards" for d in extra],
                          extra_env_dirs=[d / "environments" for d in extra],
                          plugin_dirs=[d / "plugins" for d in extra])


def cmd_analyze(a):
    from .importers import import_design
    from .report import export_csv, export_html, export_json
    product = None
    for p in a.design:
        product = import_design(p, product)
    eng = _engine(a.design[0])
    settings = {"eed_coupling_model": a.coupling}
    if a.required_se is not None:
        settings["required_se_db"] = a.required_se
    rep = eng.run(product, a.standard or None, a.environment, settings)
    print(f"\n{product.summary()}\nOverall: {rep.overall}  {rep.counts()}\n")
    for f in rep.findings:
        m = "" if f.margin_db is None else f"{f.margin_db:+6.1f} dB"
        print(f"  [{f.status:8}] {m:>10}  {f.title}  ({f.standard or ''})")
    print("\nTop mitigations:")
    for m in rep.mitigations[:10]:
        print(f"  P{m.priority} {m.title}  -> {m.applies_to}  [{m.expected_improvement_db or ''}]")
    if a.report:
        print("HTML report:", export_html(rep, product, a.report))
    if a.csv:
        print("CSV:", export_csv(rep, a.csv))
    if a.json:
        print("JSON:", export_json(rep, a.json))
    return 1 if rep.overall == "FAIL" and a.fail_exit else 0


def cmd_standards(a):
    eng = _engine()
    for s in eng.standards.list():
        flag = " (verify)" if s.verify else ""
        print(f"{s.id:28} {s.type:20} {s.name}{flag}")
    for e in eng.standards.errors:
        print("ERROR", e)


def cmd_envs(a):
    eng = _engine()
    for n in eng.environments.names():
        print(n)


def cmd_gui(a):
    from .gui.main_window import main
    return main(a.project)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="emc_analyzer", description="EMI/EMC design analysis")
    sub = ap.add_subparsers(dest="cmd")
    g = sub.add_parser("gui", help="launch the GUI")
    g.add_argument("project", nargs="?")
    g.set_defaults(fn=cmd_gui)
    an = sub.add_parser("analyze", help="run an assessment headless")
    an.add_argument("design", nargs="+", help="project/model files; later files merge into earlier ones")
    an.add_argument("-s", "--standard", action="append", help="standard id (repeatable); default from project")
    an.add_argument("-e", "--environment", help="RF environment name from the library")
    an.add_argument("--coupling", default="dipole", choices=["dipole", "matched"], help="EED coupling model")
    an.add_argument("--required-se", type=float, help="required enclosure SE in dB")
    an.add_argument("--report", help="write HTML report")
    an.add_argument("--csv")
    an.add_argument("--json")
    an.add_argument("--fail-exit", action="store_true", help="exit code 1 if any FAIL (for CI)")
    an.set_defaults(fn=cmd_analyze)
    sub.add_parser("standards", help="list standards").set_defaults(fn=cmd_standards)
    sub.add_parser("environments", help="list RF environments").set_defaults(fn=cmd_envs)
    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        a = ap.parse_args(["gui"])
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
