"""Enclosure shielding effectiveness (SE).

* Solid wall: Schelkunoff absorption + reflection + multiple-reflection terms,
  for plane-wave (far field) and magnetic near-field sources.
* Thin conductive coating on plastic: SE = 20 log10(1 + eta0 / (2 Rs)).
* Apertures:  SE = 20 log10(lambda / 2L) - 10 log10(n) + 27.3 d / L  (below cutoff).
* Seams: treated as slots of length = fastener pitch, gasket sets a floor.
Leakage paths are power-summed: SE_tot = -10 log10( sum 10^(-SE_i/10) ).
"""
from __future__ import annotations

import math
from typing import Dict

import numpy as np

from ..core.models import Enclosure
from ..core.units import C0, ETA0, MU0

SE_CAP_DB = 140.0


def skin_depth(f, sigma, mu_r):
    return 1.0 / np.sqrt(np.pi * np.asarray(f, dtype=float) * MU0 * mu_r * sigma)


def solid_wall_se(enc: Enclosure, f, source: str = "plane", r_m: float = None) -> np.ndarray:
    f = np.asarray(f, dtype=float)
    sigma, mu_r, t = enc.sigma, enc.mu_r, enc.thickness_m
    if sigma <= 0:
        rs = enc.coating_surface_resistance_ohm_sq
        if rs:
            return np.full_like(f, 20 * math.log10(1 + ETA0 / (2 * rs)))
        return np.zeros_like(f)
    w = 2 * np.pi * f
    delta = skin_depth(f, sigma, mu_r)
    absorption = 8.686 * t / delta
    eta_s = np.sqrt(w * MU0 * mu_r / sigma)        # |intrinsic impedance of metal|
    lam = C0 / f
    if source == "magnetic":
        r = r_m if r_m else 0.05
        zw = np.where(r < lam / (2 * np.pi), ETA0 * 2 * np.pi * r / lam, ETA0)
    elif source == "electric":
        r = r_m if r_m else 0.05
        zw = np.where(r < lam / (2 * np.pi), ETA0 * lam / (2 * np.pi * r), ETA0)
    else:
        zw = ETA0
    reflection = 20 * np.log10(np.maximum(zw / (4 * eta_s), 1.0))
    g = (1 + 1j) / delta
    multi = 20 * np.log10(np.abs(1 - np.exp(-2 * g * t)))
    multi = np.where(absorption < 15, multi, 0.0)
    return np.clip(absorption + reflection + multi, 0, SE_CAP_DB)


def _n_eff(n: int, size: float, lam):
    """Number of apertures that add coherently: those within ~lambda/2 of each other (Ott)."""
    return np.clip(lam / 2 / max(size, 1e-6), 1.0, max(n, 1))


def aperture_se(enc: Enclosure, f) -> Dict[str, np.ndarray]:
    f = np.asarray(f, dtype=float)
    lam = C0 / f
    out = {}
    for ap in enc.apertures:
        L = ap.length_m
        se = 20 * np.log10(np.maximum(lam / (2 * L), 1.0))
        se = se - 10 * np.log10(_n_eff(ap.count, L, lam))
        if ap.depth_m > 0:
            fc = C0 / (2 * L)
            se = se + np.where(f < fc, 27.3 * ap.depth_m / L * np.sqrt(np.maximum(1 - (f / fc) ** 2, 0)), 0)
        out[f"aperture:{ap.name}"] = np.clip(se, 0, SE_CAP_DB)
    for sm in enc.seams:
        n = max(1, int(math.ceil(sm.length_m / sm.fastener_pitch_m)))
        se = 20 * np.log10(np.maximum(lam / (2 * sm.fastener_pitch_m), 1.0)) \
            - 10 * np.log10(_n_eff(n, sm.fastener_pitch_m, lam))
        if sm.gasket:
            se = np.maximum(se, sm.gasket_se_db)
        out[f"seam:{sm.name}"] = np.clip(se, 0, SE_CAP_DB)
    return out


def total_se(enc: Enclosure, f, source: str = "plane", r_m: float = None, breakdown: bool = False):
    f = np.asarray(f, dtype=float)
    paths = {"wall": solid_wall_se(enc, f, source, r_m)}
    paths.update(aperture_se(enc, f))
    leak = sum(10 ** (-se / 10) for se in paths.values())
    tot = np.clip(-10 * np.log10(leak), 0, SE_CAP_DB)
    if breakdown:
        return tot, paths
    return tot


def cavity_resonances(enc: Enclosure, n_modes: int = 5):
    """Lowest TE/TM resonant frequencies of a rectangular enclosure (Hz)."""
    a, b, d = sorted(enc.dimensions_m, reverse=True)
    freqs = []
    for m in range(0, 4):
        for n in range(0, 4):
            for p in range(0, 4):
                if [m, n, p].count(0) > 1:
                    continue
                fr = C0 / 2 * math.sqrt((m / a) ** 2 + (n / b) ** 2 + (p / d) ** 2)
                freqs.append((fr, f"TE/TM{m}{n}{p}"))
    freqs = sorted(set(freqs))
    return freqs[:n_modes]


def max_aperture_for_se(se_db: float, f: float) -> float:
    """Largest slot length (m) that still gives se_db at frequency f."""
    return (C0 / f) / 2 / (10 ** (se_db / 20))
