"""Design data model: product -> circuits / enclosure / cables / filters / environment.

Every class round-trips to plain dicts (``to_dict`` / ``from_dict``) so that the
same model can come from YAML/JSON project files, a Python script, a MATLAB
struct or a SPICE netlist importer.

Numeric fields accept engineering strings ("100k", "2.2u", "1.5G") when loaded
from dicts.
"""
from __future__ import annotations

import dataclasses
import typing
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .units import parse_si


# --------------------------------------------------------------------------- helpers
def _coerce(tp, value):
    """Coerce a raw value (from YAML/JSON/MATLAB) to the annotated field type."""
    if value is None:
        return None
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Union:  # Optional[X]
        inner = [a for a in args if a is not type(None)][0]
        return _coerce(inner, value)
    if origin in (list, List):
        inner = args[0] if args else Any
        if isinstance(value, dict):  # allow {name: {...}} maps
            value = [dict(v, name=k) if isinstance(v, dict) and "name" not in v else v for k, v in value.items()]
        return [_coerce(inner, v) for v in value]
    if origin in (tuple, Tuple):
        return tuple(_coerce(a, v) for a, v in zip(args, value)) if args and args[-1] is not Ellipsis \
            else tuple(_coerce(args[0], v) for v in value)
    if dataclasses.is_dataclass(tp):
        return value if isinstance(value, tp) else tp.from_dict(value)
    if tp is float:
        return parse_si(value)
    if tp is int:
        return int(parse_si(value))
    if tp is bool:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "y", "on")
        return bool(value)
    if tp is str:
        return str(value)
    return value


class _Serializable:
    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        if data is None:
            return None
        if isinstance(data, cls):
            return data
        hints = typing.get_type_hints(cls)
        kwargs, extra = {}, {}
        names = {f.name for f in dataclasses.fields(cls)}
        for k, v in dict(data).items():
            if k in names:
                kwargs[k] = _coerce(hints[k], v)
            else:
                extra[k] = v
        obj = cls(**kwargs)
        if extra and hasattr(obj, "extra"):
            obj.extra.update(extra)
        return obj

    def to_dict(self) -> Dict[str, Any]:
        def conv(v):
            if dataclasses.is_dataclass(v):
                return v.to_dict()
            if isinstance(v, (list, tuple)):
                return [conv(x) for x in v]
            if isinstance(v, dict):
                return {k: conv(x) for k, x in v.items()}
            return v
        out = {}
        for f in dataclasses.fields(self):
            v = getattr(self, f.name)
            if v is None or v == [] or v == {}:
                continue
            out[f.name] = conv(v)
        return out


# --------------------------------------------------------------------------- sources
@dataclass
class NoiseSource(_Serializable):
    """A periodic emitter: clock, switching node, PWM, or CW oscillator.

    kind: 'clock' | 'switching' | 'pwm' | 'sinusoid'
    amplitude_v: peak-to-peak voltage swing (V)
    current_a: peak current in the associated loop (A), optional
    """
    name: str
    kind: str = "clock"
    frequency: float = 1e6
    amplitude_v: float = 3.3
    rise_time: float = 1e-9
    fall_time: Optional[float] = None
    duty: float = 0.5
    current_a: Optional[float] = None
    spread_spectrum_pct: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CurrentLoop(_Serializable):
    """A differential-mode current loop (PCB trace + return path) driven by a source."""
    name: str
    source: str
    area_m2: float = 1e-4
    current_a: Optional[float] = None
    inside_enclosure: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- filters
@dataclass
class FilterElement(_Serializable):
    """kind: 'L' | 'C' | 'R' ; position: 'series' | 'shunt'"""
    kind: str
    value: float
    position: str = "series"
    esr: float = 0.0
    esl: float = 0.0           # for capacitors
    parasitic_c: float = 0.0   # inter-winding capacitance for inductors
    rated_power_w: Optional[float] = None
    name: str = ""


@dataclass
class Filter(_Serializable):
    name: str
    topology: str = "custom"   # 'C','L','LC','CL','pi','T','custom' (documentation only)
    elements: List[FilterElement] = field(default_factory=list)
    source_impedance: float = 50.0
    load_impedance: float = 50.0
    rated_power_w: Optional[float] = None
    rated_voltage_v: Optional[float] = None
    rated_current_a: Optional[float] = None
    mode: str = "DM"            # 'DM' | 'CM' | 'both'
    extra: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- victims
@dataclass
class EED(_Serializable):
    """Electro-explosive device (squib / initiator) for HERO-style assessment."""
    name: str
    no_fire_current_a: float = 1.0
    bridgewire_resistance_ohm: float = 1.0
    no_fire_power_w: Optional[float] = None
    safety_margin_db: float = 16.5   # MIL-STD-464 safety-critical EED margin
    cable: Optional[str] = None
    filter: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def nfp_w(self) -> float:
        if self.no_fire_power_w:
            return self.no_fire_power_w
        return self.no_fire_current_a ** 2 * self.bridgewire_resistance_ohm


@dataclass
class Victim(_Serializable):
    """A susceptible circuit input (sensor, comms line, reset pin, ADC...)."""
    name: str
    threshold_v: float = 0.1
    f_min: float = 10e3
    f_max: float = 6e9
    input_impedance_ohm: float = 1e3
    cable: Optional[str] = None
    filter: Optional[str] = None
    margin_db: float = 6.0
    extra: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- circuits
@dataclass
class Circuit(_Serializable):
    name: str
    type: str = "digital"   # 'digital' | 'smps' | 'analog' | 'rf' | 'eed' | 'motor_drive'
    supply_voltage: float = 12.0
    sources: List[NoiseSource] = field(default_factory=list)
    loops: List[CurrentLoop] = field(default_factory=list)
    input_filter: Optional[str] = None
    # SMPS conducted-emission parameters
    input_current_a: Optional[float] = None
    input_cap_f: float = 10e-6
    input_cap_esr: float = 0.01
    input_cap_esl: float = 2e-9
    switch_node_to_chassis_f: float = 20e-12
    power_cable: Optional[str] = None
    # PCB practice flags used by the mitigation advisor
    pcb: Dict[str, Any] = field(default_factory=dict)
    eeds: List[EED] = field(default_factory=list)
    victims: List[Victim] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def source(self, name: str) -> Optional[NoiseSource]:
        return next((s for s in self.sources if s.name == name), None)


# --------------------------------------------------------------------------- enclosure
@dataclass
class Aperture(_Serializable):
    name: str
    length_m: float            # largest linear dimension
    width_m: Optional[float] = None
    count: int = 1
    depth_m: float = 0.0       # waveguide depth (honeycomb / thick wall)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Seam(_Serializable):
    name: str
    length_m: float
    fastener_pitch_m: float = 0.05
    gasket: bool = False
    gasket_se_db: float = 60.0
    extra: Dict[str, Any] = field(default_factory=dict)


MATERIALS = {
    # name: (conductivity S/m, relative permeability)
    "copper": (5.8e7, 1.0),
    "aluminium": (3.5e7, 1.0),
    "aluminum": (3.5e7, 1.0),
    "brass": (1.6e7, 1.0),
    "steel": (6.0e6, 200.0),
    "mild_steel": (6.0e6, 200.0),
    "stainless_steel": (1.4e6, 1.0),
    "mu_metal": (1.6e6, 20000.0),
    "nickel": (1.45e7, 100.0),
    "tin": (8.7e6, 1.0),
    "zinc": (1.7e7, 1.0),
    "plastic": (0.0, 1.0),
}


@dataclass
class Enclosure(_Serializable):
    name: str = "Enclosure"
    material: str = "aluminium"
    conductivity: Optional[float] = None
    relative_permeability: Optional[float] = None
    thickness_m: float = 1.5e-3
    dimensions_m: Tuple[float, float, float] = (0.2, 0.15, 0.05)
    apertures: List[Aperture] = field(default_factory=list)
    seams: List[Seam] = field(default_factory=list)
    coating_surface_resistance_ohm_sq: Optional[float] = None   # conductive paint/plating on plastic
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def sigma(self) -> float:
        if self.conductivity is not None:
            return self.conductivity
        return MATERIALS.get(self.material.lower(), (3.5e7, 1.0))[0]

    @property
    def mu_r(self) -> float:
        if self.relative_permeability is not None:
            return self.relative_permeability
        return MATERIALS.get(self.material.lower(), (3.5e7, 1.0))[1]


# --------------------------------------------------------------------------- cables
@dataclass
class Cable(_Serializable):
    name: str
    length_m: float = 1.0
    shielded: bool = False
    shield_termination: str = "none"      # '360' | 'pigtail' | 'none'
    pigtail_length_m: float = 0.02
    transfer_impedance_mohm_per_m: float = 10.0   # at low frequency
    exits_enclosure: bool = True
    height_above_ground_m: float = 0.05
    cm_impedance_ohm: float = 150.0       # common-mode impedance seen by the cable
    ferrite_impedance_ohm: float = 0.0    # clamp-on ferrite impedance @100 MHz
    filter: Optional[str] = None
    connected_circuit: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- environment
@dataclass
class Environment(_Serializable):
    """An external RF environment (EED / HERO assessment, immunity levels).

    bands: list of [f_low, f_high, value] where value is in `unit`
    unit: 'W/m2' (power density) or 'V/m' (field strength)
    """
    name: str
    unit: str = "W/m2"
    bands: List[Tuple[float, float, float]] = field(default_factory=list)
    description: str = ""
    source: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- product
@dataclass
class Product(_Serializable):
    name: str = "Untitled product"
    description: str = ""
    platform: str = ""
    system: str = ""
    classification: str = "Unclassified"
    circuits: List[Circuit] = field(default_factory=list)
    enclosure: Optional[Enclosure] = None
    cables: List[Cable] = field(default_factory=list)
    filters: List[Filter] = field(default_factory=list)
    environment: Optional[Environment] = None
    standards: List[str] = field(default_factory=list)   # default standards to assess against
    measurement_distance_m: float = 3.0
    extra: Dict[str, Any] = field(default_factory=dict)

    # lookups -------------------------------------------------------------
    def cable(self, name: Optional[str]) -> Optional[Cable]:
        return next((c for c in self.cables if c.name == name), None) if name else None

    def filter(self, name: Optional[str]) -> Optional[Filter]:
        return next((f for f in self.filters if f.name == name), None) if name else None

    def circuit(self, name: Optional[str]) -> Optional[Circuit]:
        return next((c for c in self.circuits if c.name == name), None) if name else None

    def summary(self) -> str:
        enc = self.enclosure.material if self.enclosure else "none"
        return (f"{self.name}: {len(self.circuits)} circuit(s), {len(self.cables)} cable(s), "
                f"{len(self.filters)} filter(s), enclosure={enc}")
