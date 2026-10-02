"""Trapezoidal-waveform spectra (clocks, PWM, switch nodes).

One-sided harmonic amplitude of a trapezoidal pulse train (Paul, "Introduction to
Electromagnetic Compatibility", ch. 3):

    c_n = 2 A d |sinc(n pi d)| |sinc(n pi tr / T)|       (tr = tf)

where A is the peak-to-peak amplitude, d the duty cycle and T the period.
"""
from __future__ import annotations

import math
from typing import Tuple

import numpy as np

from ..core.models import NoiseSource


def _sinc(x):
    x = np.asarray(x, dtype=float)
    out = np.ones_like(x)
    nz = x != 0
    out[nz] = np.sin(x[nz]) / x[nz]
    return out


def rbw_for(f):
    """CISPR receiver resolution bandwidth for frequency f (Hz)."""
    f = np.asarray(f, dtype=float)
    return np.where(f < 150e3, 200.0, np.where(f < 30e6, 9e3, np.where(f < 1e9, 120e3, 1e6)))


def spread_spectrum_reduction_db(f, spread_pct: float):
    """Approximate peak reduction from spread-spectrum clocking.

    The harmonic energy is spread over n*delta_f; a receiver with bandwidth RBW
    sees roughly RBW / (n*delta_f) of it.  Reduction is limited to 0 dB minimum.
    """
    if not spread_pct:
        return np.zeros_like(np.asarray(f, dtype=float))
    f = np.asarray(f, dtype=float)
    spread_hz = f * spread_pct / 100.0
    red = 10 * np.log10(np.maximum(spread_hz / rbw_for(f), 1.0))
    return np.minimum(red, 20.0)  # practical ceiling


def trapezoid_harmonics(src: NoiseSource, f_max: float, amplitude: float = None,
                        max_harmonics: int = 20000) -> Tuple[np.ndarray, np.ndarray]:
    """Return (frequencies Hz, peak amplitudes) of harmonics up to f_max.

    ``amplitude`` overrides the source voltage (use for currents).
    Sinusoidal sources return the fundamental only.
    """
    A = src.amplitude_v if amplitude is None else amplitude
    f0 = src.frequency
    if src.kind == "sinusoid":
        return np.array([f0]), np.array([A / 2.0])  # p-p -> peak
    n_max = int(min(max_harmonics, max(1, math.floor(f_max / f0))))
    n = np.arange(1, n_max + 1)
    T = 1.0 / f0
    tr = src.rise_time
    tf = src.fall_time or tr
    t_edge = 0.5 * (tr + tf)
    d = min(max(src.duty, 1e-4), 1 - 1e-4)
    c = 2 * A * d * np.abs(_sinc(n * np.pi * d)) * np.abs(_sinc(n * np.pi * t_edge / T))
    if tf != tr:  # unequal edges: use the faster edge for a conservative envelope above its knee
        c_fast = 2 * A * d * np.abs(_sinc(n * np.pi * d)) * np.abs(_sinc(n * np.pi * min(tr, tf) / T))
        c = np.maximum(c, c_fast)
    f = n * f0
    keep = c > 0
    return f[keep], c[keep]


def envelope(src: NoiseSource, f: np.ndarray, amplitude: float = None) -> np.ndarray:
    """Bode-style upper bound of the spectrum (flat / -20 dB/dec / -40 dB/dec)."""
    A = src.amplitude_v if amplitude is None else amplitude
    T = 1.0 / src.frequency
    tau = src.duty * T
    tr = src.rise_time
    f = np.asarray(f, dtype=float)
    f1 = 1.0 / (math.pi * tau)
    f2 = 1.0 / (math.pi * tr)
    env = 2 * A * src.duty * np.ones_like(f)
    env = np.where(f > f1, env * f1 / f, env)
    env = np.where(f > f2, env * f2 / f, env)
    return env


def knee_frequencies(src: NoiseSource) -> Tuple[float, float]:
    T = 1.0 / src.frequency
    return 1.0 / (math.pi * src.duty * T), 1.0 / (math.pi * src.rise_time)
