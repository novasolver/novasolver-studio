"""Unit handling. Every number in a case is {"value": x, "unit": "mm"}; only this module converts to SI."""
from __future__ import annotations

import re

# factor to SI and the SI dimension label
UNITS: dict[str, tuple[float, str]] = {
    "m": (1.0, "length"), "cm": (1e-2, "length"), "mm": (1e-3, "length"), "um": (1e-6, "length"),
    "N": (1.0, "force"), "kN": (1e3, "force"),
    'N/m': (1., 'stiffness'), 'N/mm': (1e3, 'stiffness'),
    'N-m': (1., 'torque'), 'N-mm': (1e-3, 'torque'), '1/K': (1., 'expansion'), 'm/s2': (1., 'acceleration'),
    "Pa": (1.0, "pressure"), "kPa": (1e3, "pressure"), "MPa": (1e6, "pressure"), "GPa": (1e9, "pressure"),
    "kg/m3": (1.0, "density"), "g/cm3": (1e3, "density"),
    "m/s": (1.0, "velocity"), "mm/s": (1e-3, "velocity"), "km/h": (1 / 3.6, "velocity"),
    "m2/s": (1.0, "kinematic_viscosity"), "mm2/s": (1e-6, "kinematic_viscosity"), "cSt": (1e-6, "kinematic_viscosity"),
    "K": (1.0, "temperature"), "degC": (1.0, "temperature"),
    "W/m2": (1.0, "heat_flux"), "kW/m2": (1e3, "heat_flux"),
    "W/m2K": (1.0, "heat_transfer_coeff"),
    "W/mK": (1.0, "conductivity"),
    "W": (1.0, "power"), "kW": (1e3, "power"),
    "V": (1.0, "voltage"), "kV": (1e3, "voltage"), "mV": (1e-3, "voltage"),
    "C/m2": (1.0, "surface_charge"),
    "A": (1.0, "current"), "mA": (1e-3, "current"),
    "S/m": (1.0, "electrical_conductivity"),
    "F": (1.0, "capacitance"), "pF": (1e-12, "capacitance"), "nF": (1e-9, "capacitance"), "uF": (1e-6, "capacitance"),
    "ohm": (1.0, "resistance"), "mohm": (1e-3, "resistance"),
    "-": (1.0, "dimensionless"),
}
# affine units: SI = value * factor + offset
OFFSETS = {"degC": 273.15}
ALIASES = {"°C": "degC", "℃": "degC", "C": "degC", 'Nm':'N-m', 'N·m':'N-m', 'Nmm':'N-mm', 'N·mm':'N-mm'}

UNIT_CHOICES: dict[str, list[str]] = {}
for _u, (_f, _d) in UNITS.items():
    UNIT_CHOICES.setdefault(_d, []).append(_u)


class UnitError(ValueError):
    pass


def dimension(unit: str) -> str:
    unit = ALIASES.get(unit, unit)
    if unit not in UNITS:
        raise UnitError(f"unknown unit '{unit}'. Known: {', '.join(UNITS)}")
    return UNITS[unit][1]


def to_si(q) -> float | list[float]:
    """Accepts {"value","unit"}, a bare number (already SI), or a string like '5 mm'."""
    if isinstance(q, (int, float)):
        return float(q)
    if isinstance(q, str):
        q = parse(q)
    v, u = q["value"], ALIASES.get(q.get("unit", "-"), q.get("unit", "-"))
    f = UNITS[u][0] if u in UNITS else _bad(u)
    off = OFFSETS.get(u, 0.0)
    if isinstance(v, list):
        return [float(x) * f + off for x in v]
    return float(v) * f + off


def from_si(x: float, unit: str) -> float:
    unit = ALIASES.get(unit, unit)
    return (x - OFFSETS.get(unit, 0.0)) / UNITS[unit][0]


def _bad(u):
    raise UnitError(f"unknown unit '{u}'")


_RX = re.compile(r"^\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*([A-Za-z/0-9\-°℃·]*)\s*$")


def parse(text: str, default_unit: str = "-") -> dict:
    m = _RX.match(text)
    if not m:
        raise UnitError(f"cannot read '{text}' as a number with unit")
    unit = ALIASES.get(m.group(2), m.group(2)) or default_unit
    dimension(unit)
    return {"value": float(m.group(1)), "unit": unit}


def normalize(new, old: dict | None):
    """Coerce a user/AI supplied value into {"value","unit"} keeping the old unit's dimension."""
    if isinstance(new, dict) and "value" in new:
        u = new.get("unit") or (old or {}).get("unit", "-")
        if old and dimension(u) != dimension(old.get("unit", "-")):
            raise UnitError(f"unit '{u}' has dimension {dimension(u)}, expected {dimension(old['unit'])}")
        return {"value": new["value"], "unit": u}
    if isinstance(new, str):
        q = parse(new, (old or {}).get("unit", "-"))
        if old and dimension(q["unit"]) != dimension(old.get("unit", "-")):
            raise UnitError(f"unit '{q['unit']}' has dimension {dimension(q['unit'])}, expected {dimension(old['unit'])}")
        return q
    if isinstance(new, (int, float, list)):
        return {"value": new, "unit": (old or {}).get("unit", "-")}
    raise UnitError(f"cannot interpret value {new!r}")
