"""EMI filter modelling with ABCD (chain) matrices, including component parasitics."""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from ..core.models import Filter, FilterElement


def element_impedance(el: FilterElement, f) -> np.ndarray:
    w = 2 * np.pi * np.asarray(f, dtype=float)
    k = el.kind.upper()
    if k == "L":
        z = el.esr + 1j * w * el.value
        if el.parasitic_c:
            z = 1.0 / (1.0 / z + 1j * w * el.parasitic_c)
        return z
    if k == "C":
        esr = el.esr if el.esr > 0 else 5e-3      # real capacitors always have some ESR
        return esr + 1j * w * el.esl + 1.0 / (1j * w * el.value)
    if k == "R":
        return np.full_like(w, el.value, dtype=complex)
    if k in ("FB", "FERRITE"):  # ferrite bead: value = impedance at 100 MHz, modelled as lossy L
        l_eq = el.value / (2 * np.pi * 100e6)
        return (0.7 * el.value) * np.minimum(w / (2 * np.pi * 100e6), 1.0) + 1j * w * l_eq * 0.7
    raise ValueError(f"Unknown filter element kind {el.kind!r}")


def abcd(filt: Filter, f) -> np.ndarray:
    """Return ABCD matrices shape (N, 2, 2) for frequency array f."""
    f = np.atleast_1d(np.asarray(f, dtype=float))
    M = np.tile(np.eye(2, dtype=complex), (f.size, 1, 1))
    for el in filt.elements:
        z = element_impedance(el, f)
        E = np.tile(np.eye(2, dtype=complex), (f.size, 1, 1))
        if el.position.lower().startswith("ser"):
            E[:, 0, 1] = z
        else:
            E[:, 1, 0] = 1.0 / z
        M = M @ E
    return M


def load_voltage_ratio(M: np.ndarray, zs, zl) -> np.ndarray:
    """V_load / V_source for a two-port M between source zs and load zl."""
    A, B, C, D = M[:, 0, 0], M[:, 0, 1], M[:, 1, 0], M[:, 1, 1]
    return zl / (A * zl + B + C * zs * zl + D * zs)


def insertion_loss_db(filt: Optional[Filter], f, zs=None, zl=None) -> np.ndarray:
    """Insertion loss (dB, positive = attenuation) of the filter between zs and zl."""
    f = np.atleast_1d(np.asarray(f, dtype=float))
    if filt is None or not filt.elements:
        return np.zeros_like(f)
    zs = filt.source_impedance if zs is None else zs
    zl = filt.load_impedance if zl is None else zl
    zs = np.broadcast_to(np.asarray(zs, dtype=complex), f.shape)
    zl = np.broadcast_to(np.asarray(zl, dtype=complex), f.shape)
    with_f = load_voltage_ratio(abcd(filt, f), zs, zl)
    without = zl / (zs + zl)
    return 20 * np.log10(np.abs(without) / np.maximum(np.abs(with_f), 1e-300))


def element_dissipation(filt: Filter, f: float, v_source_peak: float, zs=None, zl=None) -> List[Dict]:
    """Power (W) dissipated in each element for a sinusoidal source of peak voltage v_source_peak."""
    zs = filt.source_impedance if zs is None else zs
    zl = filt.load_impedance if zl is None else zl
    # walk backwards from the load with V_L = 1 V
    v, i = 1.0 + 0j, 1.0 / zl
    powers = []
    for el in reversed(filt.elements):
        z = complex(element_impedance(el, np.array([f]))[0])
        if el.position.lower().startswith("ser"):
            p = 0.5 * abs(i) ** 2 * z.real
            v = v + i * z
        else:
            ish = v / z
            p = 0.5 * abs(ish) ** 2 * z.real
            i = i + ish
        powers.append((el, p))
    v_needed = v + i * zs
    scale = abs(v_source_peak / v_needed) ** 2
    out = []
    for el, p in reversed(powers):
        out.append({"element": el.name or f"{el.kind}{el.position[:3]}", "power_w": p * scale,
                    "rated_power_w": el.rated_power_w})
    out.append({"element": "load", "power_w": 0.5 * abs(1.0 / zl) ** 2 * np.real(zl) * scale, "rated_power_w": None})
    return out


def lc_corner_for_attenuation(atten_db: float, f_target: float, order: int = 2) -> float:
    """Corner frequency an `order`-pole filter needs to give atten_db at f_target."""
    return f_target / (10 ** (atten_db / (20.0 * order)))
