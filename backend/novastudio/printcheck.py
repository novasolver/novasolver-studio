"""3D-print strength check for a solved structural case in PLA, PETG or ABS.

FDM parts are weakest between layers: tension and shear across the layers open them long before the filament itself
breaks. For each of the three possible print directions (layers normal to x, y or z) the check compares
  - the stress on the layer plane (tension across it and shear along it) with the layer-bond strength, combined as
    (tension / Z)^2 + (shear / Z)^2 = 1 (the bond is taken to be as strong in shear as in tension), and
  - the von Mises stress with the strength along the filament,
and reports the safety factor of each orientation and the best one. Stresses within about two elements of a fixed
face are left out: a rigid support is a singularity there, and its peak would otherwise pick the orientation.
The part is assumed printed solid (100 % infill, enough walls); the strengths are conservative typical values,
replaceable by the filament's datasheet values. Linear static results only: a screening tool, not a certification.
"""
from __future__ import annotations

import math

import numpy as np

from . import results
from .store import StudioError

# typical FDM strengths at 100 % infill [Pa]: along the filament (XY), across layers (Z). Conservative ends of
# published datasheet ranges; the person can replace them with their filament's values.
PRINT_MATERIALS = {"pla": (50e6, 25e6), "petg": (45e6, 25e6), "abs": (35e6, 20e6)}
FIXED_ROLES = ("fixed",)        # a beam clamp lets the section contract freely: no singularity, keep its stresses
AXES = ("x", "y", "z")
SHEAR = {"x": (3, 5), "y": (3, 4), "z": (4, 5)}     # s columns: sxx syy szz sxy syz szx


def _preset(m: dict) -> str | None:
    key = m.get("preset")
    return m.get("base_preset") if key == "custom" else key


def _material(case: dict) -> str | None:
    mat = _preset(case.get("materials", {}).get("solid", {}))
    if mat not in PRINT_MATERIALS or any(m != mat for m in case.get("body_materials", {}).values()):
        return None                 # an assembly with other materials: the print strengths would not apply
    from .templates import solid_props
    bodies = list(case.get("body_materials", {})) or [None]
    if any(solid_props(case, b).get("model", "linear") != "linear" for b in bodies):
        return None
    return mat


def _strength(value, default: float) -> float:
    if value is None:
        return default
    v = float(value) * 1e6
    if not (math.isfinite(v) and v > 0):
        raise StudioError("err.print_check_strength", 400)
    return v


def _von_mises(s: np.ndarray) -> np.ndarray:
    d = (s[:, 0] - s[:, 1]) ** 2 + (s[:, 1] - s[:, 2]) ** 2 + (s[:, 2] - s[:, 0]) ** 2
    return np.sqrt(0.5 * d + 3.0 * (s[:, 3] ** 2 + s[:, 4] ** 2 + s[:, 5] ** 2))


def _near_support(nodes: np.ndarray, tris: list[np.ndarray]) -> np.ndarray:
    """Nodes within about two elements of a fixed face (as run_worker.support_peak)."""
    near = np.zeros(len(nodes), bool)
    if not tris:
        return near
    from scipy.spatial import cKDTree
    tri = np.concatenate([t[:, :3] for t in tris])
    edge = np.linalg.norm(nodes[tri[:, 0]] - nodes[tri[:, 1]], axis=1)
    dist, _ = cKDTree(nodes[np.unique(tri)]).query(nodes)
    return dist <= 2.0 * float(np.median(edge))


def check(case: dict, run_id: str | None = None, strength_xy_mpa: float | None = None,
          strength_z_mpa: float | None = None) -> dict:
    mat = _material(case)
    ph = case.get("physics", {})
    if ph.get("kind") != "linear-static" or ph.get("analysis") in ("modal", "buckling", "nonlinear") or mat is None:
        raise StudioError("err.print_check_scope", 400)
    jd, r = results.load(case["case_id"], run_id)
    npz = jd / "results.npz"
    if r.get("kind") not in (None, "structural", "linear-static") or not npz.is_file():
        raise StudioError("err.print_check_scope", 400)
    with np.load(npz) as d:
        if "s" not in d.files:
            raise StudioError("err.print_check_scope", 400)
        s = d["s"]
    with np.load(jd / "mesh.npz") as mesh:
        nodes = mesh["nodes"]
        tris = [np.asarray(mesh[f"face_{key}"]) for key, b in case.get("boundaries", {}).items()
                if b.get("role") in FIXED_ROLES and f"face_{key}" in mesh.files]
    sxy, sz = PRINT_MATERIALS[mat]
    sxy, sz = _strength(strength_xy_mpa, sxy), _strength(strength_z_mpa, sz)
    near = _near_support(nodes, tris)
    away = ~near if (~near).any() else np.ones(len(nodes), bool)
    vm = _von_mises(s)                  # from the same nodal tensor as the layer stresses, so the two agree

    def at(i: int) -> list[float]:
        return (nodes[i] * 1e3).round(2).tolist()

    i_vm = int(np.argmax(np.where(away, vm, -np.inf)))
    vm_peak = float(vm[i_vm])
    sf_filament = sxy / vm_peak if vm_peak > 0 else float("inf")
    axes = []
    for i, ax in enumerate(AXES):
        tension = np.maximum(s[:, i], 0.0)
        shear = np.hypot(s[:, SHEAR[ax][0]], s[:, SHEAR[ax][1]])
        index = np.hypot(tension / sz, shear / sz)
        j = int(np.argmax(np.where(away, index, -np.inf)))
        sf_layers = 1.0 / float(index[j]) if index[j] > 0 else float("inf")
        axes.append({"axis": ax, "layer_tension_mpa": float(tension[j]) / 1e6,
                     "layer_shear_mpa": float(shear[j]) / 1e6, "at_mm": at(j), "sf_layers": sf_layers,
                     "sf": min(sf_layers, sf_filament)})
    best = max(axes, key=lambda a: a["sf"])
    support_peak = float(vm[near].max()) if near.any() else 0.0
    return {"case_id": case["case_id"], "run_id": jd.name, "material": mat,
            "strength_xy_mpa": sxy / 1e6, "strength_z_mpa": sz / 1e6,
            "vm_max_mpa": vm_peak / 1e6, "vm_at_mm": at(i_vm), "sf_filament": sf_filament,
            "axes": axes, "best_axis": best["axis"], "best_sf": best["sf"],
            "worst_sf": min(a["sf"] for a in axes),
            "support_peak_mpa": support_peak / 1e6,
            "support_peak_exceeds": support_peak > 1.2 * vm_peak}
