"""Browser demo driver (runs in Pyodide). Uses Studio's own solver modules unchanged: novastudio/fem_tet10.py and
novastudio/box_mesh.py, copied next to this file by build_demo.py. Returns plain lists for the JavaScript viewer."""
import numpy as np

from novastudio import box_mesh, fem_tet10

MATERIALS = {"steel": (205e9, 0.30, 250e6), "aluminium": (70e9, 0.33, 150e6), "pla": (3.5e9, 0.36, 50e6)}


def run(L_mm, b_mm, h_mm, F_N, material):
    L, b, h = L_mm / 1e3, b_mm / 1e3, h_mm / 1e3
    E, nu, sy = MATERIALS[material]
    nx = 2 * int(np.clip(round(4 * L / h), 4, 20))          # even: a node row lies exactly at mid-span
    ny = int(np.clip(round(2 * b / h), 1, 4))
    nz = 2
    m = box_mesh.generate((L, b, h), (nx, ny, nz))
    nodes, tets = m["nodes"], m["tets"]
    traction = np.array([0.0, 0.0, -F_N / (b * h)])          # total F on the free end, downwards
    r = fem_tet10.solve(nodes, tets, E, nu, [m["face_x0"]], [(m["face_x1"], traction)])
    u = r["u"]
    tip = -float(u[np.isclose(nodes[:, 0], L), 2].mean())
    # references: Euler-Bernoulli bending + Timoshenko shear term, and the root bending stress M c / I
    I = b * h ** 3 / 12
    G = E / (2 * (1 + nu))
    ref_tip = F_N * L ** 3 / (3 * E * I) + F_N * L / ((5 / 6) * G * b * h)
    ref_sigma = F_N * L * (h / 2) / I
    # bending stress away from the clamp (the clamp itself has a local peak that beam theory does not have)
    sx = r["s"][:, 0]
    sel = np.isclose(nodes[:, 0], 0.5 * L, atol=1e-9) & np.isclose(np.abs(nodes[:, 2] - h / 2), h / 2)
    mid = float(np.abs(sx[sel]).max()) if sel.any() else float("nan")
    ref_mid = F_N * (0.5 * L) * (h / 2) / I
    # exterior surface for drawing: each tri6 face as 4 linear triangles
    tris = []
    for key in ("face_x0", "face_x1", "face_y0", "face_y1", "face_z0", "face_z1"):
        a, b6, d, ab, bd, da = m[key].T
        tris.append(np.stack([np.stack([a, ab, da], 1), np.stack([ab, b6, bd], 1), np.stack([da, bd, d], 1),
                              np.stack([ab, bd, da], 1)], 1).reshape(-1, 3))
    tri = np.concatenate(tris)
    used, inv = np.unique(tri, return_inverse=True)
    return {
        "positions": nodes[used].ravel().tolist(), "displacement": u[used].ravel().tolist(),
        "vm": r["vm"][used].tolist(), "indices": inv.ravel().tolist(),
        "tip": tip, "ref_tip": ref_tip, "vm_max": float(r["vm"].max()), "sigma_mid": mid, "ref_mid": ref_mid,
        "ref_root": ref_sigma, "sy": sy, "nodes": int(len(nodes)), "elements": int(len(tets)),
        "imbalance": float(r["imbalance"]), "L": L, "b": b, "h": h,
    }
