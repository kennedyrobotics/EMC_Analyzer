"""Matplotlib rendering of findings - shared by the GUI and the HTML report."""
from __future__ import annotations

import numpy as np

from ..core.results import Finding

PALETTE = ["#1f5fbf", "#e07b00", "#2a9d5c", "#8e44ad", "#c0392b", "#16a2b8", "#7f8c8d"]
LIMIT_COLOR = "#d62728"


def _hz_formatter(x, _pos=None):
    for s, u in ((1e9, "G"), (1e6, "M"), (1e3, "K")):
        if x >= s:
            v = x / s
            return f"{v:g}{u}"
    return f"{x:g}"


def plot_finding(ax, finding: Finding, title: str = None):
    from matplotlib.ticker import FuncFormatter

    ax.clear()
    ci = 0
    for tr in finding.traces:
        f = np.asarray(tr.freq, dtype=float)
        v = np.asarray(tr.value, dtype=float)
        if tr.style == "limit":
            ax.plot(f, v, color=LIMIT_COLOR, lw=2.0, label=tr.label, drawstyle="default")
        elif tr.style == "stem":
            c = PALETTE[ci % len(PALETTE)]
            ci += 1
            if f.size > 250:   # dense harmonic comb -> draw its peak envelope per log bin
                bins = np.logspace(np.log10(f.min()), np.log10(f.max()), 200)
                idx = np.digitize(f, bins)
                ef, ev = [], []
                for b in np.unique(idx):
                    m = idx == b
                    j = np.argmax(v[m])
                    ef.append(f[m][j]); ev.append(v[m][j])
                ax.plot(ef, ev, color=c, lw=1.2, label=tr.label + " (envelope)")
            else:
                floor = np.nanmin(v) - 10 if v.size else 0
                ax.vlines(f, floor, v, color=c, lw=0.8, alpha=0.8)
                ax.plot(f, v, "o", ms=2, color=c, label=tr.label)
        else:
            c = PALETTE[ci % len(PALETTE)]
            ci += 1
            ax.plot(f, v, color=c, lw=1.6, label=tr.label)
    ax.set_xscale("log")
    if finding.y_log:
        ax.set_yscale("log")
    else:
        vals = np.concatenate([np.asarray(t.value, float)[np.isfinite(np.asarray(t.value, float))]
                               for t in finding.traces] or [np.array([0.0])])
        if vals.size:
            lo = max(np.nanmin(vals), np.nanmax(vals) - 120)
            ax.set_ylim(lo - 5, np.nanmax(vals) + 10)
    if finding.worst_freq_hz:
        ax.axvline(finding.worst_freq_hz, color="#555", ls=":", lw=1)
    ax.xaxis.set_major_formatter(FuncFormatter(_hz_formatter))
    ax.grid(True, which="major", color="#bbb", lw=0.8)
    ax.grid(True, which="minor", color="#e3e3e3", lw=0.5)
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel(finding.y_label)
    ax.set_title(title or f"{finding.title}  [{finding.status}"
                 + (f", {finding.margin_db:+.1f} dB]" if finding.margin_db is not None else "]"), fontsize=10)
    if finding.traces:
        ax.legend(fontsize=7, loc="best")


def finding_png(finding: Finding, width=8, height=4.2, dpi=110) -> bytes:
    import io

    import matplotlib
    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    plot_finding(ax, finding)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
