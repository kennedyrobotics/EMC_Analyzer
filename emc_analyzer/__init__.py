"""EMC Analyzer - Kennedy Robotics EMI/EMC design-assessment toolkit.

Load circuit, enclosure and product descriptions (YAML/JSON, Python models,
MATLAB .mat files, SPICE netlists), assess them against a library of EMC
standards / RF environments, and generate mitigations and next-step advice.
"""
__version__ = "0.1.0"

from .core.models import (  # noqa: F401
    Product, Circuit, Enclosure, Aperture, Seam, Cable, Filter, FilterElement,
    NoiseSource, CurrentLoop, EED, Victim, Environment,
)
from .engine import AnalysisEngine, run_analysis  # noqa: F401
