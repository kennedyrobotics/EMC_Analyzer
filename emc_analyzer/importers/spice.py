"""SPICE netlist importer (LTspice / ngspice / PSpice style).

Extracts noise sources from independent V/I sources:
    Vclk clk 0 PULSE(0 3.3 0 1n 1n 9n 20n)   -> clock, 50 MHz, tr 1 ns
    Vosc rf 0 SIN(0 1 433.92Meg)             -> sinusoid
and passive components (R/L/C) for filters.

EMC annotations in comment lines add what a netlist cannot express:
    *EMC circuit name=Clock_Tree type=digital supply=3.3
    *EMC loop name=CLK_LOOP source=Vclk area=2e-4 current=0.02
    *EMC filter name=EMI_IN elements=L1,C1,C2 source_z=50 load_z=50 mode=DM
    *EMC source Vsw kind=switching current=2 spread=5
    *EMC cable name=PWR length=1.5 shielded=no connected=Clock_Tree
Elements listed in a filter become 'shunt' if one node is ground (0/gnd), otherwise 'series'.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Dict, List, Optional

from ..core.models import Cable, Circuit, CurrentLoop, Filter, FilterElement, NoiseSource, Product
from ..core.units import parse_si
from . import register_importer

GROUND = {"0", "gnd", "GND", "agnd", "pgnd"}


def _kv(tokens: List[str]) -> Dict[str, str]:
    out = {}
    for t in tokens:
        if "=" in t:
            k, v = t.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _num(s: str) -> float:
    s = s.strip()
    m = re.match(r"^([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)(meg|[fpnumkgt]?)", s, re.I)
    if not m:
        raise ValueError(f"bad number {s!r}")
    num, pre = m.groups()
    pre_l = pre.lower()
    scale = {"": 1, "f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "meg": 1e6,
             "g": 1e9, "t": 1e12}[pre_l]           # SPICE: m = milli, meg = mega
    return float(num) * scale


def parse_netlist(text: str, default_name: str = "netlist"):
    lines, buf = [], ""
    for raw in text.splitlines():
        if raw.startswith("+"):
            buf += " " + raw[1:]
            continue
        if buf:
            lines.append(buf)
        buf = raw.strip()
    if buf:
        lines.append(buf)

    comps: Dict[str, dict] = {}
    sources: Dict[str, NoiseSource] = {}
    annotations: List[List[str]] = []
    for ln in lines:
        if not ln:
            continue
        if ln.upper().startswith("*EMC"):
            annotations.append(shlex.split(ln[4:].strip()))
            continue
        if ln[0] in "*;." or ln.startswith("//"):
            continue
        toks = ln.split()
        name = toks[0]
        kind = name[0].upper()
        if kind in "RLC" and len(toks) >= 4:
            try:
                comps[name] = {"kind": kind, "n1": toks[1], "n2": toks[2], "value": _num(toks[3])}
            except ValueError:
                pass
        elif kind in "VI":
            rest = " ".join(toks[3:])
            m = re.search(r"PULSE\s*\(([^)]*)\)", rest, re.I)
            if m:
                a = [_num(x) for x in m.group(1).replace(",", " ").split()]
                a += [0.0] * (7 - len(a))
                v1, v2, _td, tr, tf, pw, per = a[:7]
                if per > 0:
                    sources[name] = NoiseSource(name=name, kind="clock", frequency=1 / per,
                                                amplitude_v=abs(v2 - v1), rise_time=tr or 1e-9,
                                                fall_time=tf or None, duty=min(max((pw + 0.5 * (tr + tf)) / per, 0.01), 0.99))
                continue
            m = re.search(r"SIN\s*\(([^)]*)\)", rest, re.I)
            if m:
                a = [_num(x) for x in m.group(1).replace(",", " ").split()]
                if len(a) >= 3:
                    sources[name] = NoiseSource(name=name, kind="sinusoid", frequency=a[2], amplitude_v=2 * a[1])
    return comps, sources, annotations


@register_importer("spice", [".cir", ".net", ".sp", ".spice", ".ckt"], "SPICE netlist")
def load_spice(path: Path, current: Optional[Product] = None) -> Product:
    comps, sources, annotations = parse_netlist(path.read_text(encoding="utf-8", errors="replace"), path.stem)
    prod = current or Product(name=path.stem)
    circ = Circuit(name=path.stem, type="digital")
    for ann in annotations:
        if not ann:
            continue
        what, kv = ann[0].lower(), _kv(ann[1:])
        if what == "circuit":
            circ.name = kv.get("name", circ.name)
            circ.type = kv.get("type", circ.type)
            if "supply" in kv:
                circ.supply_voltage = parse_si(kv["supply"])
            for k in ("input_cap_f", "switch_node_to_chassis_f", "input_current_a"):
                if k in kv:
                    setattr(circ, k, parse_si(kv[k]))
            if "filter" in kv:
                circ.input_filter = kv["filter"]
            if "power_cable" in kv:
                circ.power_cable = kv["power_cable"]
        elif what == "source" and len(ann) > 1 and ann[1] in sources:
            s = sources[ann[1]]
            s.kind = kv.get("kind", s.kind)
            if "current" in kv:
                s.current_a = parse_si(kv["current"])
            if "spread" in kv:
                s.spread_spectrum_pct = parse_si(kv["spread"])
        elif what == "loop":
            circ.loops.append(CurrentLoop(name=kv.get("name", f"loop{len(circ.loops) + 1}"),
                                          source=kv["source"], area_m2=parse_si(kv.get("area", "1e-4")),
                                          current_a=parse_si(kv["current"]) if "current" in kv else None))
        elif what == "filter":
            els = []
            for en in kv.get("elements", "").split(","):
                c = comps.get(en.strip())
                if not c:
                    continue
                shunt = c["n1"] in GROUND or c["n2"] in GROUND
                els.append(FilterElement(kind=c["kind"], value=c["value"], name=en.strip(),
                                         position="shunt" if shunt else "series"))
            flt = Filter(name=kv.get("name", "filter"), elements=els,
                         source_impedance=parse_si(kv.get("source_z", 50)),
                         load_impedance=parse_si(kv.get("load_z", 50)), mode=kv.get("mode", "DM"))
            prod.filters = [f for f in prod.filters if f.name != flt.name] + [flt]
        elif what == "cable":
            cab = Cable(name=kv.get("name", "cable"), length_m=parse_si(kv.get("length", 1)),
                        shielded=kv.get("shielded", "no").lower() in ("yes", "true", "1"),
                        shield_termination=kv.get("termination", "none"),
                        connected_circuit=kv.get("connected", circ.name))
            prod.cables = [c for c in prod.cables if c.name != cab.name] + [cab]
    circ.sources = list(sources.values())
    if circ.type == "digital" and any(s.kind in ("switching", "pwm") for s in circ.sources):
        circ.type = "smps"
    circ.extra["netlist_components"] = {k: v for k, v in comps.items()}
    prod.circuits = [c for c in prod.circuits if c.name != circ.name] + [circ]
    return prod
