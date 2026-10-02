"""Unit conversions and frequency-grid helpers used across the analysis engines."""
from __future__ import annotations

import math
import re

import numpy as np

C0 = 299_792_458.0          # speed of light, m/s
MU0 = 4e-7 * math.pi        # H/m
EPS0 = 8.854187817e-12      # F/m
ETA0 = 376.730313668        # free-space impedance, ohm

_SI = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3,
       "": 1.0, "k": 1e3, "K": 1e3, "meg": 1e6, "M": 1e6, "g": 1e9, "G": 1e9, "t": 1e12, "T": 1e12}


def parse_si(value) -> float:
    """Parse '100k', '2.2u', '1G', '10MHz', '4.7nF', 1e3 -> float.

    'M' is mega (engineering convention), 'm' is milli, 'meg' (SPICE) is mega.
    """
    if value is None:
        raise ValueError("None is not a number")
    if isinstance(value, (int, float, np.floating, np.integer)):
        return float(value)
    s = str(value).strip().replace(" ", "")
    m = re.fullmatch(r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)(meg|MEG|Meg|[fpnuµmkKMgGtT]?)([A-Za-zΩ/²]*)", s)
    if not m:
        raise ValueError(f"Cannot parse numeric value: {value!r}")
    num, prefix, _unit = m.groups()
    key = prefix.lower() if prefix.lower() == "meg" else prefix
    return float(num) * _SI[key]


def db20(x):
    return 20.0 * np.log10(np.maximum(np.abs(x), 1e-300))


def db10(x):
    return 10.0 * np.log10(np.maximum(np.abs(x), 1e-300))


def from_db20(x):
    return 10.0 ** (np.asarray(x) / 20.0)


def from_db10(x):
    return 10.0 ** (np.asarray(x) / 10.0)


def v_to_dbuv(v):
    return db20(np.asarray(v) / 1e-6)


def dbuv_to_v(dbuv):
    return 1e-6 * from_db20(dbuv)


def a_to_dbua(i):
    return db20(np.asarray(i) / 1e-6)


def wavelength(f):
    return C0 / np.asarray(f, dtype=float)


def power_density_from_field(e_vpm):
    """Far-field power density S (W/m^2) from E (V/m)."""
    return np.asarray(e_vpm) ** 2 / ETA0


def field_from_power_density(s_wpm2):
    return np.sqrt(np.asarray(s_wpm2) * ETA0)


def log_grid(f_start: float, f_stop: float, points_per_decade: int = 100) -> np.ndarray:
    decades = math.log10(f_stop / f_start)
    n = max(2, int(round(decades * points_per_decade)) + 1)
    return np.logspace(math.log10(f_start), math.log10(f_stop), n)


def fmt_freq(f: float) -> str:
    for scale, unit in ((1e9, "GHz"), (1e6, "MHz"), (1e3, "kHz")):
        if abs(f) >= scale:
            return f"{f / scale:.4g} {unit}"
    return f"{f:.4g} Hz"


def interp_loglin(f_points, values, f_query, left=np.nan, right=np.nan):
    """Interpolate values (dB-like, linear) against log-frequency."""
    fp = np.log10(np.asarray(f_points, dtype=float))
    return np.interp(np.log10(np.asarray(f_query, dtype=float)), fp, np.asarray(values, dtype=float),
                     left=left, right=right)
