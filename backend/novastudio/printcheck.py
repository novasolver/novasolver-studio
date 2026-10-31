"""3D-print strength check for a solved structural case in PLA, PETG or ABS.

FDM parts are weakest between layers: tension across the layers opens them long before the filament itself breaks.
For each of the three possible print directions (layers normal to x, y or z) the check compares
  - the tension across the layers (the normal stress along the build direction) with the layer-bond strength, and
  - the von Mises stress with the strength along the filament,
and reports the safety factor of each orientation and the best one. The part is assumed printed solid (100 % infill,
enough walls); the strengths are conservative typical values, replaceable by the filament's datasheet values.
Linear-elastic results only: the check is a screening tool, not a certification.
"""
from __future__ import annotations

import numpy as np

from . import results
from .store import StudioError

# typical FDM strengths at 100 % infill [Pa]: along the filament (XY), across layers (Z). Conservative ends of
# published datasheet ranges; the person can replace them with their filament's values.
PRINT_MATERIALS = {"pla": (50e6, 25e6), "petg": (45e6, 25e6), "abs": (35e6, 20e6)}
FIXED_ROLES = ("fixed", "beam-clamp")
AXES = ("x", "y", "z")


def _material(case: dict) -> str | None:
    m = case.get("materials", {}).get("solid", {})
    key = m.get("preset")
    if key == "custom":
        key = m.get("base_preset")
    return key if key in PRINT_MATERIALS else None


def check(case: dict, run_id: str | None = None, strength_xy_mpa: float | None = None,
          strength_z_mpa: float | None = None) -> dict:
    mat = _material(case)
    if case.get("physics", {}).get("kind") != "linear-static" or mat is None:
        raise StudioError("err.print_check_scope", 400)
    jd, r = results.load(case["case_id"], run_id)
    npz = jd / "results.npz"
    if r.get("kind") not in (None, "structural", "linear-static") or not npz.is_file():
        raise StudioError("err.print_check_scope", 400)
    with np.load(npz) as d:
        if "s" not in d.files:
            raise StudioError("err.print_check_scope", 400)
        s, vm = d["s"], d["vm"]
    with np.load(jd / "mesh.npz") as mesh:
        nodes = mesh["nodes"]
        support = np.zeros(len(nodes), bool)
        for key, b in case.get("boundaries", {}).items():
            if b.get("role") in FIXED_ROLES and f"face_{key}" in mesh.files:
                support[np.unique(mesh[f"face_{key}"])] = True
    sxy, sz = PRINT_MATERIALS[mat]
    if strength_xy_mpa:
        sxy = float(strength_xy_mpa) * 1e6
    if strength_z_mpa:
        sz = float(strength_z_mpa) * 1e6
    if not (sxy > 0 and sz > 0):
        raise StudioError("err.print_check_strength", 400)
    away = ~support if (~support).any() else np.ones(len(nodes), bool)

    def peak(values, mask):
        i = int(np.argmax(np.where(mask, values, -np.inf)))
        return float(values[i]), (nodes[i] * 1e3).round(2).tolist()

    vm_peak, vm_at = peak(vm, away)
    sf_filament = sxy / vm_peak if vm_peak > 0 else float("inf")
    axes = []
    for i, ax in enumerate(AXES):
        tension, at = peak(s[:, i], away)
        tension = max(tension, 0.0)
        sf_layers = sz / tension if tension > 0 else float("inf")
        axes.append({"axis": ax, "layer_tension_mpa": tension / 1e6, "at_mm": at, "sf_layers": sf_layers,
                     "sf": min(sf_layers, sf_filament)})
    best = max(axes, key=lambda a: a["sf"])
    support_peak = float(vm[support].max()) if support.any() else 0.0
    return {"case_id": case["case_id"], "run_id": jd.name, "material": mat,
            "strength_xy_mpa": sxy / 1e6, "strength_z_mpa": sz / 1e6,
            "vm_max_mpa": vm_peak / 1e6, "vm_at_mm": vm_at, "sf_filament": sf_filament,
            "axes": axes, "best_axis": best["axis"], "best_sf": best["sf"],
            "worst_sf": min(a["sf"] for a in axes),
            "support_peak_mpa": support_peak / 1e6,
            "support_peak_exceeds": support_peak > 1.2 * vm_peak}
