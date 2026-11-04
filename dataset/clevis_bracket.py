"""Family: clevis mounting bracket, a part with no closed-form answer. A base plate is bolted down through four holes
(their walls are fixed); two tapered lugs with a pin hole stand on it, joined by a web; the pin pushes the lugs sideways
(+x, spread evenly over the two pin holes). All the feet are filleted, and the stress reported is the peak on those fillets.

Lengths are scaled by the base length B (B = 100 mm in the solves), E and F scale out as in l_bracket.py."""
from __future__ import annotations

import math
from pathlib import Path

B = 100.0                     # mm, base length (x); the base is 1.2 B wide (y)
F = 1000.0                    # N, total force on the pin holes, +x
E = 200e9                     # Pa
NU = 0.3
# fixed proportions of the part, / B
FOOT = 0.32                   # half-length of a lug's foot
HEAD = 0.20                   # radius of the lug's rounded top
PIN = 0.10                    # radius of the pin hole
GAP = 0.18                    # half of the clear gap between the lugs
BOLT = 0.05                   # bolt hole radius
BOLT_X, BOLT_Y = 0.42, 0.50   # bolt hole centres, from the part's centre
EDGE = 0.25                   # radius of the rounded lug outline / lug thickness

PARAMS = {
    "h_over_B": (0.35, 0.75),     # pin height above the base
    "tl_over_B": (0.06, 0.14),    # lug thickness
    "tb_over_B": (0.08, 0.20),    # base thickness
    "tw_over_B": (0.04, 0.12),    # web thickness
    "r_over_tl": (0.30, 0.80),    # foot fillet radius / lug thickness
}

EXPECTED_DIRECTIONS = {
    "sigma_star": {"h_over_B": 1, "tl_over_B": -1, "r_over_tl": -1},
    "delta_star": {"h_over_B": 1, "tl_over_B": -1, "tb_over_B": -1},
}
LEVELS = {"coarser": 1 / 2, "standard": 1 / 4, "finer": 1 / 8}
QUANTITIES = ("sigma_star", "delta_star")
NORMALISED = {"sigma_star": "kt", "delta_star": "beam_ratio"}
CHECK_EQUILIBRIUM = True


def dims(p: dict, scale: float = 1.0) -> dict:
    s = B * scale
    tl = p["tl_over_B"] * s
    return {"B": s, "W": 1.2 * s, "h": p["h_over_B"] * s, "tl": tl, "tb": p["tb_over_B"] * s, "tw": p["tw_over_B"] * s,
            "r": p["r_over_tl"] * tl}


def _lug(occ, d: dict, y0: float) -> int:
    """A lug: the profile in the x-z plane from the foot, along the tangents, round the head; extruded from y0 by tl."""
    s, cx, zb = d["B"], d["B"] / 2, d["tb"]
    zc, R, c = zb + d["h"], HEAD * s, FOOT * s
    dist = math.hypot(c, zc - zb)
    ang = math.atan2(zb - zc, c) + math.acos(R / dist)                # angle of the right tangent point on the head
    tx, tz = R * math.cos(ang), R * math.sin(ang)
    pts = [occ.addPoint(cx - c, y0, zb), occ.addPoint(cx + c, y0, zb), occ.addPoint(cx + tx, y0, zc + tz),
           occ.addPoint(cx - tx, y0, zc + tz)]
    centre = occ.addPoint(cx, y0, zc)
    loop = occ.addCurveLoop([occ.addLine(pts[0], pts[1]), occ.addLine(pts[1], pts[2]),
                             occ.addCircleArc(pts[2], centre, pts[3]), occ.addLine(pts[3], pts[0])])
    surf = occ.addPlaneSurface([loop])
    ext = occ.extrude([(2, surf)], 0, d["tl"], 0)
    return next(t for dim, t in ext if dim == 3)


def write_step(p: dict, path: Path, scale: float = 1.0) -> None:
    import gmsh
    d = dims(p, scale)
    s, W, cx, cy, zb, tl = d["B"], d["W"], d["B"] / 2, d["W"] / 2, d["tb"], d["tl"]
    gap = GAP * s
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("clevis")
        occ = gmsh.model.occ
        base = occ.addBox(0, 0, 0, s, W, zb)
        lug1 = _lug(occ, d, cy - gap - tl)
        lug2 = _lug(occ, d, cy + gap)
        web_h = 0.55 * d["h"]
        web = occ.addBox(cx - d["tw"] / 2, cy - gap, zb, d["tw"], 2 * gap, web_h)
        out, _ = occ.fuse([(3, base)], [(3, lug1), (3, lug2), (3, web)])
        cut = [(3, occ.addCylinder(cx, cy - gap - tl - s, zb + d["h"], 0, 2 * (gap + tl + s), 0, PIN * s))]
        for sx in (-1, 1):
            for sy in (-1, 1):
                cut.append((3, occ.addCylinder(cx + sx * BOLT_X * s, cy + sy * BOLT_Y * s, -s, 0, 0, zb + 2 * s, BOLT * s)))
        out, _ = occ.cut(out, cut)
        occ.synchronize()
        vol = out[0][1]
        tol = 1e-4 * s
        # round the lugs' outlines first: a sharp corner running into the foot fillet is a stress that grows with every
        # mesh refinement (12.5, 12.8, 14.0 MPa on the sharp version)
        zc = zb + d["h"]
        faces_y = [cy - gap - tl, cy - gap, cy + gap, cy + gap + tl]
        outline = []
        for _, e in gmsh.model.getEntities(1):
            x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(1, e)
            flat_y = abs(y1 - y0) < tol and any(abs(y0 - v) < tol for v in faces_y)
            on_foot = abs(z1 - zb) < tol
            at_web = x0 > cx - d["tw"] / 2 - tol and x1 < cx + d["tw"] / 2 + tol and z1 < zb + web_h + tol
            at_pin = x0 > cx - (PIN * s + tol) and x1 < cx + PIN * s + tol and z0 > zc - (PIN * s + tol) and z1 < zc + PIN * s + tol
            if flat_y and z1 > zb + tol and not (on_foot or at_web or at_pin):
                outline.append(e)
        assert len(outline) == 12, f"lug outline edges: {len(outline)}"
        out = occ.fillet([vol], outline, [EDGE * tl])
        occ.synchronize()
        vol = gmsh.model.getEntities(3)[0][1]
        edges = []
        for _, e in gmsh.model.getEntities(1):
            x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(1, e)
            on_base = abs(z0 - zb) < tol and abs(z1 - zb) < tol
            in_foot = x0 > cx - (FOOT * s + tol) and x1 < cx + FOOT * s + tol and y0 > cy - (gap + tl + tol) and y1 < cy + gap + tl + tol
            if on_base and in_foot:
                edges.append(e)
        assert len(edges) >= 8, f"foot edges not found ({len(edges)})"
        occ.fillet([vol], edges, [d["r"]])
        occ.synchronize()
        assert len(gmsh.model.getEntities(3)) == 1, "fillet split the part"
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def refine_face(faces: list[dict]) -> list[str]:
    """The curved faces at the feet: just above the base's top (its height and the part's size come from the bolt holes,
    the four lowest curved faces); the rounded lug outlines reach far higher."""
    cyl = sorted((f for f in faces if f.get("type") != "Plane"), key=lambda f: f["centroid_mm"][2])
    bolts = cyl[:4]
    size = (max(f["centroid_mm"][0] for f in bolts) - min(f["centroid_mm"][0] for f in bolts)) / (2 * BOLT_X)
    top = 2 * bolts[0]["centroid_mm"][2]
    keys = [f["key"] for f in cyl[4:] if f["centroid_mm"][2] < top + 0.115 * size]
    assert len(keys) >= 8, len(keys)
    return keys


def refine_length(p: dict, scale: float = 1.0) -> float:
    return dims(p, scale)["r"]


def _classify(faces: list[dict], d: dict) -> tuple[list[str], list[str]]:
    s, cx, cy, zc = d["B"], d["B"] / 2, d["W"] / 2, d["tb"] + d["h"]
    bolts, pins = [], []
    for f in faces:
        if f.get("type") != "Cylinder":
            continue
        x, y, z = f["centroid_mm"]
        if abs(z - d["tb"] / 2) < 0.02 * s and abs(abs(x - cx) - BOLT_X * s) < 1.1 * BOLT * s and abs(abs(y - cy) - BOLT_Y * s) < 1.1 * BOLT * s:
            bolts.append(f["key"])
        elif math.hypot(x - cx, z - zc) < 1.01 * PIN * s:
            pins.append(f["key"])
    return bolts, pins


def boundary_changes(faces: list[dict], p: dict, scale: float = 1.0, force: float = F) -> dict:
    d = dims(p, scale)
    bolts, pins = _classify(faces, d)
    assert len(bolts) >= 4 and len(pins) >= 2, (bolts, pins)
    ch = {f"boundaries.{k}.role": "fixed" for k in bolts}
    for k in pins:
        ch.update({f"boundaries.{k}.role": "load", f"boundaries.{k}.force": f"{force / len(pins)} N", f"boundaries.{k}.direction": "+x"})
    return ch


def _pins(p: dict, scale: float) -> list[list[float]]:
    """Top of each lug, in the middle of the ring round the pin hole: moves with the pin, and mirror images in y."""
    d = dims(p, scale)
    s, cx, cy = d["B"], d["B"] / 2, d["W"] / 2
    z = d["tb"] + d["h"] + (PIN + HEAD) / 2 * s
    return [[cx, cy - GAP * s - d["tl"] / 2, z], [cx, cy + GAP * s + d["tl"] / 2, z]]


def measure(C, cid: str, p: dict, scale: float, refine_key) -> dict:
    keys = refine_key if isinstance(refine_key, list) else [refine_key]
    pr = C.probe_results(cid, _pins(p, scale), None, keys, None, "en", 1, None)
    ux = [pt["values"]["ux"] for pt in pr["points"]]
    best = max(pr["faces"], key=lambda f: f["max"]["vm"])
    return {"foot_vm_mpa": best["max"]["vm"], "foot_face": best.get("face") or best.get("key"), "foot_where": best["max"].get("at") or best["max"].get("point"),
            "pin_ux_mm": sum(ux) / 2, "mirror_ux_mm": ux, "foot_faces": len(keys)}


def nondim(s: dict, p: dict, scale: float = 1.0, force: float = F) -> dict:
    Bmm = B * scale
    return {"sigma_star": s["foot_vm_mpa"] * Bmm ** 2 / force, "delta_star": abs(s["pin_ux_mm"]) * (E / 1e6) * Bmm / force}


def references(p: dict, s: dict, nd: dict) -> dict:
    """Hand sums: the two lugs as one cantilever of foot length c, height h. Reference only: no closed form fits this part."""
    d = dims(p)
    c = 2 * FOOT * d["B"]
    I = 2 * d["tl"] * c ** 3 / 12
    nominal = F * d["h"] * (c / 2) / I
    beam = F * d["h"] ** 3 / (3 * (E / 1e6) * I)
    return {"kt": s["foot_vm_mpa"] / nominal, "beam_ratio": abs(s["pin_ux_mm"]) / beam}


def mirror_err(s: dict) -> float:
    m = s["mirror_ux_mm"]
    return abs(m[0] - m[1]) / max(abs(m[0]), 1e-30)
