"""Probe a finished run: values at points, along a line, and statistics (plus flow through) per face.
Works on the tetra mesh results (structural, thermal, internal flow, conjugate, external on a tetra mesh).
Coordinates in and out are mm, like the face centroids that import_geometry reports."""
from __future__ import annotations

import numpy as np

from .results import load
from .store import StudioError

MAX_POINTS = 500
_TET_FACES = ((0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 3, 1), (1, 2, 3, 0))   # three corners + the opposite one


def _fields(kind: str, data) -> dict[str, tuple[np.ndarray, str]]:
    """Nodal quantities in display units."""
    if kind == "structural":
        u = data["u"] * 1e3
        out = {"disp": (np.linalg.norm(u, axis=1), "mm"), "ux": (u[:, 0], "mm"), "uy": (u[:, 1], "mm"),
               "uz": (u[:, 2], "mm"), "vm": (data["vm"] / 1e6, "MPa")}
        if "s" in data.files:                     # stress tensor (xx, yy, zz, xy, yz, zx); runs before 0.2.2 lack it
            s = data["s"] / 1e6
            for i, c in enumerate(("sxx", "syy", "szz", "sxy", "syz", "szx")):
                out[c] = (s[:, i], "MPa")
            T = np.stack([np.stack([s[:, 0], s[:, 3], s[:, 5]], 1), np.stack([s[:, 3], s[:, 1], s[:, 4]], 1),
                          np.stack([s[:, 5], s[:, 4], s[:, 2]], 1)], 1)
            ev = np.linalg.eigvalsh(T)
            out["s1"], out["s3"] = (ev[:, 2], "MPa"), (ev[:, 0], "MPa")
        return out
    out = {}
    if "V" in data.files:
        E = data["E"]
        out.update(v=(data["V"], "V"), emag=(np.linalg.norm(E, axis=1), "V/m"))
        for i, q in enumerate(("ex", "ey", "ez")):
            out[q] = (E[:, i], "V/m")
        if "J" in data.files:
            out.update(jmag=(np.linalg.norm(data["J"], axis=1), "A/m2"), q=(data["q"], "W/m3"))
    if "T" in data.files:
        out["temp"] = (data["T"] - 273.15, "°C")
    if "U" in data.files:
        U = data["U"]
        out.update({"speed": (np.linalg.norm(U, axis=1), "m/s"), "ux": (U[:, 0], "m/s"), "uy": (U[:, 1], "m/s"),
                    "uz": (U[:, 2], "m/s")})
    if "p" in data.files:
        out["p"] = (data["p"], "Pa")
    return out


class _Locator:
    """Find the tetrahedron that holds a point and interpolate nodal values in it (quadratic on tet10)."""

    def __init__(self, nodes: np.ndarray, tets: np.ndarray):
        from scipy.spatial import cKDTree
        self.nodes, self.tets = nodes, tets
        self.corner = nodes[tets[:, :4]]
        self.tree = cKDTree(self.corner.mean(axis=1))
        self.node_tree = cKDTree(nodes)

    def bary(self, e: int, x: np.ndarray) -> np.ndarray:
        a, b, c, d = self.corner[e]
        lam = np.linalg.solve(np.stack([b - a, c - a, d - a], 1), x - a)
        return np.array([1 - lam.sum(), *lam])

    def locate(self, x: np.ndarray):
        k = min(64, len(self.tets))
        _, cand = self.tree.query(x, k=k)
        best, best_min = None, -np.inf
        for e in np.atleast_1d(cand):
            try:
                L = self.bary(int(e), x)
            except np.linalg.LinAlgError:
                continue
            if L.min() >= -1e-9:
                return int(e), L
            if L.min() > best_min:
                best, best_min = (int(e), L), L.min()
        return None if best is None else (*best, False)

    def _pairs(self, conn) -> list[tuple[int, int]]:
        """tet10: the two corners each edge node sits between (independent of the node ordering)."""
        corners = self.nodes[conn[:4]]
        pairs = [(a, b) for a in range(4) for b in range(a + 1, 4)]
        return [min(pairs, key=lambda p: np.linalg.norm((corners[p[0]] + corners[p[1]]) / 2 - self.nodes[j]))
                for j in conn[4:10]]

    @staticmethod
    def _shape(L, pairs) -> np.ndarray:
        return np.array([*(L * (2 * L - 1)), *(4 * L[a] * L[b] for a, b in pairs)])

    def curved(self, e: int, x: np.ndarray, L: np.ndarray) -> np.ndarray:
        """Volume coordinates of x in a curved tet10 (CAD meshes put midside nodes on the true surface): Newton on the
        quadratic map, started from the straight-sided answer. A field linear in x is then read back exactly."""
        conn = self.tets[e]
        if len(conn) < 10:
            return L
        pairs, X = self._pairs(conn), self.nodes[conn[:10]]
        xi = L[1:].copy()
        for _ in range(8):
            Lf = np.array([1 - xi.sum(), *xi])
            r = self._shape(Lf, pairs) @ X - x
            if np.linalg.norm(r) < 1e-12 * max(1.0, float(np.ptp(X))):
                break
            J = np.empty((3, 3))
            for k in range(3):
                d = xi.copy()
                d[k] += 1e-7
                Ld = np.array([1 - d.sum(), *d])
                J[:, k] = (self._shape(Ld, pairs) @ X - x - r) / 1e-7
            try:
                xi = xi - np.linalg.solve(J, r)
            except np.linalg.LinAlgError:
                return L
        return np.array([1 - xi.sum(), *xi])

    def weights(self, e: int, L: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        conn = self.tets[e]
        if len(conn) == 4:
            return conn, L
        return conn[:10], self._shape(L, self._pairs(conn))


def _tri_owner_side(tri: np.ndarray, tets: np.ndarray, nodes: np.ndarray) -> np.ndarray:
    """Unit normals of boundary triangles pointing out of the meshed domain (away from the tet that owns each one)."""
    n = np.int64(len(nodes))
    c4 = tets[:, :4].astype(np.int64)
    keys, opp = [], []
    for i, j, k, o in _TET_FACES:
        s = np.sort(c4[:, [i, j, k]], axis=1)
        keys.append((s[:, 0] * n + s[:, 1]) * n + s[:, 2])
        opp.append(c4[:, o])
    keys, opp = np.concatenate(keys), np.concatenate(opp)
    order = np.argsort(keys)
    keys, opp = keys[order], opp[order]
    t = np.sort(tri[:, :3].astype(np.int64), axis=1)
    q = (t[:, 0] * n + t[:, 1]) * n + t[:, 2]
    pos = np.clip(np.searchsorted(keys, q), 0, len(keys) - 1)
    found = keys[pos] == q
    P = nodes[tri[:, :3]]
    nrm = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    inside = nodes[opp[pos]] - P[:, 0]
    sign = np.where(np.einsum("ij,ij->i", nrm, inside) > 0, -1.0, 1.0)
    return nrm * np.where(found, sign, 1.0)[:, None] / 2.0            # |vector| = triangle area


def probe(case: dict, points: list | None = None, line: dict | None = None, faces: list[str] | None = None,
          run_id: str | None = None) -> dict:
    jd, r = load(case["case_id"], run_id)
    kind = r["kind"]
    if not (jd / "mesh.npz").is_file():
        raise StudioError("err.probe_unsupported", 400, kind=kind)
    data = np.load(jd / "results.npz")
    if "snappy" in data.files:
        raise StudioError("err.probe_unsupported", 400, kind="external (snappyHexMesh)")
    mesh = np.load(jd / "mesh.npz")
    nodes, tets = mesh["nodes"], mesh["tets"]
    F = _fields(kind, data)
    if not F or len(next(iter(F.values()))[0]) != len(nodes):
        raise StudioError("err.probe_unsupported", 400, kind=kind)
    out = {"case_id": case["case_id"], "run_id": jd.name, "kind": kind, "stale": r.get("revision") != case["revision"],
           "quantities": {q: u for q, (_, u) in F.items()}}

    pts = []
    if points:
        pts += [("point", np.asarray(p, float)) for p in points]
    if line:
        a, b = np.asarray(line["from"], float), np.asarray(line["to"], float)
        n = int(line.get("n", 50))
        if not 2 <= n <= MAX_POINTS:
            raise StudioError("err.path", 400, path=f"line.n={n} (2..{MAX_POINTS})")
        pts += [("line", a + (b - a) * s) for s in np.linspace(0, 1, n)]
    if len(pts) > MAX_POINTS:
        raise StudioError("err.path", 400, path=f"{len(pts)} probe points (max {MAX_POINTS})")
    if pts:
        loc = _Locator(nodes, tets)
        res = []
        for _, p_mm in pts:
            if p_mm.shape != (3,):
                raise StudioError("err.path", 400, path="points: each point is [x, y, z] in mm")
            x = p_mm * 1e-3
            hit = loc.locate(x)
            if hit is not None and len(hit) == 2:
                idx, w = loc.weights(hit[0], loc.curved(hit[0], x, hit[1]))
                vals = {q: float(v[idx] @ w) for q, (v, _) in F.items()}
                res.append({"at_mm": p_mm.round(4).tolist(), "inside": True, "values": vals})
            else:
                dist, j = loc.node_tree.query(x)
                res.append({"at_mm": p_mm.round(4).tolist(), "inside": False, "nearest_node_mm": round(dist * 1e3, 4),
                            "values": {q: float(v[j]) for q, (v, _) in F.items()}})
        npt = len(points or [])
        if npt:
            out["points"] = res[:npt]
        if line:
            seg = res[npt:]
            a = np.asarray(line["from"], float)
            for s in seg:
                s["s_mm"] = round(float(np.linalg.norm(np.asarray(s["at_mm"]) - a)), 4)
            ins = [s for s in seg if s["inside"]]
            out["line"] = {"from_mm": line["from"], "to_mm": line["to"], "samples": seg,
                           "inside_fraction": round(len(ins) / len(seg), 3),
                           "min": {q: min(s["values"][q] for s in ins) for q in F} if ins else None,
                           "max": {q: max(s["values"][q] for s in ins) for q in F} if ins else None}

    if faces:
        stats = []
        for key in faces:
            arr = f"face_{key}"
            if arr not in mesh.files:
                raise StudioError("err.path", 400, path=f"faces: {key} (not a face of this mesh)")
            tri = mesh[arr]
            P = nodes[tri[:, :3]]
            area_v = _tri_owner_side(tri, tets, nodes)
            A = np.linalg.norm(area_v, axis=1)
            At = float(A.sum())
            st = {"key": key, "area_mm2": round(At * 1e6, 4),
                  "centroid_mm": ((P.mean(axis=1) * A[:, None]).sum(0) / At * 1e3).round(4).tolist(),
                  "mean": {}, "min": {}, "max": {}}
            fn = np.unique(tri)
            for metric, key_out in (("face_charge_c", "charge_c"), ("face_current_a", "current_a")):
                if key in r.get("metrics", {}).get(metric, {}):
                    st[key_out] = r["metrics"][metric][key]
            # area mean of the interpolant: on a tri6 the corner shape functions integrate to 0 and each midside one
            # to A/3, so the mean of a triangle is the mean of its midside values (corners only on linear tri3)
            avg_nodes = tri[:, 3:6] if tri.shape[1] >= 6 else tri[:, :3]
            for q, (v, _) in F.items():
                st["mean"][q] = float((v[avg_nodes].mean(axis=1) * A).sum() / At)
                st["min"][q], st["max"][q] = float(v[fn].min()), float(v[fn].max())
            if "U" in data.files:
                exact = (r.get("metrics") or {}).get("face_flux_m3s", {})
                if key in exact:                  # the solver's own face fluxes (inlets and outlets)
                    q_out = exact[key]
                else:                             # elsewhere from nodal velocities: low on coarse meshes
                    Ut = data["U"][avg_nodes].mean(axis=1)
                    q_out = float(np.einsum("ij,ij->", Ut, area_v))
                st["flow_out_m3s"] = q_out
                st["flow_out_lmin"] = q_out * 6e4
            stats.append(st)
        out["faces"] = stats
    if not (points or line or faces):
        raise StudioError("err.path", 400, path="give points, line or faces")
    return out
