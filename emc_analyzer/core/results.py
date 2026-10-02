"""Result containers shared by the analysis engines, advisor, GUI and reports."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

PASS, MARGINAL, FAIL, INFO = "PASS", "MARGINAL", "FAIL", "INFO"


@dataclass
class Trace:
    """A plotted series: frequency (Hz) vs value."""
    label: str
    freq: np.ndarray
    value: np.ndarray
    unit: str = "dBuV/m"
    style: str = "line"      # 'line' | 'step' | 'limit' | 'stem'


@dataclass
class Finding:
    """One assessment outcome (e.g. 'RE @ 3 m vs CISPR 32 Class B')."""
    check: str                 # analysis id e.g. 'radiated_emissions'
    title: str
    status: str                # PASS / MARGINAL / FAIL / INFO
    margin_db: Optional[float] = None    # +ve = headroom below limit, -ve = exceedance
    worst_freq_hz: Optional[float] = None
    standard: Optional[str] = None
    subject: Optional[str] = None        # circuit / cable / EED name
    detail: str = ""
    traces: List[Trace] = field(default_factory=list)
    y_label: str = ""
    y_log: bool = False
    data: Dict[str, Any] = field(default_factory=dict)   # extra numbers for the advisor


@dataclass
class Mitigation:
    title: str
    rationale: str
    applies_to: str
    category: str              # 'Shielding' | 'Filtering' | 'PCB layout' | 'Cabling' | 'Grounding' | 'Source' | 'Process'
    priority: int = 2          # 1 = do first
    expected_improvement_db: Optional[str] = None
    effort: str = "Medium"     # Low / Medium / High
    related_findings: List[str] = field(default_factory=list)


@dataclass
class Report:
    product_name: str
    findings: List[Finding] = field(default_factory=list)
    mitigations: List[Mitigation] = field(default_factory=list)
    next_steps: List[Dict[str, Any]] = field(default_factory=list)
    standards: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def overall(self) -> str:
        st = {f.status for f in self.findings}
        if FAIL in st:
            return FAIL
        if MARGINAL in st:
            return MARGINAL
        return PASS

    def counts(self) -> Dict[str, int]:
        out = {PASS: 0, MARGINAL: 0, FAIL: 0, INFO: 0}
        for f in self.findings:
            out[f.status] = out.get(f.status, 0) + 1
        return out


def classify(margin_db: float, marginal_band_db: float = 6.0) -> str:
    if margin_db is None or np.isnan(margin_db):
        return INFO
    if margin_db < 0:
        return FAIL
    if margin_db < marginal_band_db:
        return MARGINAL
    return PASS
