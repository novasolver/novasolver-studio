"""Face names from a STEP file.

gmsh reads the names of the top-level shapes (OCCImportLabels) but not those of faces. CAD systems that name faces
(build123d/CadQuery labels, CATIA, NX, OCCT's write.stepcaf.subshapes.name) write them as the name attribute of
ADVANCED_FACE. We read them from the text and find the gmsh face with the same vertices: the face order of the two
readers is not guaranteed to match, the vertices are. Parts placed in an assembly are moved by their placement
transform first."""
from __future__ import annotations

import re
from itertools import product

import numpy as np



def _parse_args(s: str, i: int = 0):
    """Parse a parenthesised STEP argument list starting at s[i] == '('. Returns (list, index after ')')."""
    out, i = [], i + 1
    while i < len(s):
        c = s[i]
        if c in " \t\r\n,":
            i += 1
        elif c == ")":
            return out, i + 1
        elif c == "(":
            sub, i = _parse_args(s, i)
            out.append(sub)
        elif c == "'":
            j, buf = i + 1, []
            while j < len(s):
                if s[j] == "'":
                    if s[j + 1:j + 2] == "'":
                        buf.append("'"); j += 2; continue
                    break
                buf.append(s[j]); j += 1
            out.append(_decode("".join(buf)))
            i = j + 1
        elif c == "#":
            m = re.match(r"#(\d+)", s[i:])
            out.append(("#", int(m.group(1))))
            i += m.end()
        else:
            m = re.match(r"[A-Z_][A-Z0-9_]*\s*\(", s[i:], re.I)
            if m:                                   # typed parameter, e.g. LENGTH_MEASURE(25.4)
                sub, i = _parse_args(s, i + m.end() - 1)
                out.append(sub[0] if len(sub) == 1 else sub)
                continue
            m = re.match(r"[^,()]+", s[i:])
            tok = m.group(0).strip()
            try:
                out.append(float(tok))
            except ValueError:
                out.append(tok)                     # .T. / .MILLI. / $ / *
            i += m.end()
    return out, i


def _decode(text: str) -> str:
    """ISO 10303-21 escapes: \\X2\\hhhh...\\X0\\ (UCS-2, how CAD writes Japanese), \\X\\hh (Latin-1), \\S\\c."""
    def x2(m):
        h = m.group(1)
        return "".join(chr(int(h[k:k + 4], 16)) for k in range(0, len(h) - 3, 4))
    text = re.sub(r"\\X2\\([0-9A-Fa-f]+)\\X0\\", x2, text)
    text = re.sub(r"\\X4\\([0-9A-Fa-f]+)\\X0\\",
                  lambda m: "".join(chr(int(m.group(1)[k:k + 8], 16)) for k in range(0, len(m.group(1)) - 7, 8)), text)
    text = re.sub(r"\\X\\([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), text)
    text = re.sub(r"\\S\\(.)", lambda m: chr(ord(m.group(1)) + 128), text)
    return text.replace("\\\\", "\\")


_STATEMENT = re.compile(r"#(\d+)\s*=\s*((?:[^;']|'(?:[^']|'')*')*);")
_TYPE = re.compile(r"\s*([A-Z_][A-Z0-9_]*)\s*\(", re.I)


class Entities:
    """The DATA section, parsed lazily: a 50 MB STEP file has a million entities, and only the faces, their loops and
    vertices, the shells and the assembly placements are needed."""

    def __init__(self, text: str):
        body = re.sub(r"/\*.*?\*/", "", text.split("DATA;", 1)[-1], flags=re.S)
        self.raw = {int(m.group(1)): m.group(2).strip() for m in _STATEMENT.finditer(body)}
        self.cache = {}
        self.index = {}
        for i, rhs in self.raw.items():
            types = [m.group(1) for m in re.finditer(r"([A-Z_][A-Z0-9_]*)\s*\(", rhs)] if rhs.startswith("(") \
                else [(_TYPE.match(rhs) or [None, None])[1]]
            for t in types:
                if t:
                    self.index.setdefault(t.upper(), []).append(i)

    def get(self, i, default=()):
        if i not in self.cache:
            rhs, recs = self.raw.get(i), []
            if rhs is None:
                return default
            if rhs.startswith("("):              # complex: (A(...) B(...) ...)
                k = 1
                while True:
                    m = _TYPE.match(rhs, k)
                    if not m:
                        break
                    args, k = _parse_args(rhs, m.end() - 1)
                    recs.append((m.group(1).upper(), args))
            else:
                m = _TYPE.match(rhs)
                if m:
                    recs.append((m.group(1).upper(), _parse_args(rhs, m.end() - 1)[0]))
            self.cache[i] = recs
        return self.cache[i]

    def of_type(self, *types, suffix=False):
        """(id, records) of the entities with one of these types (or a type ending in one, with suffix=True)."""
        keys = [t for t in self.index if any(t.endswith(x) for x in types)] if suffix else types
        for i in sorted({i for t in keys for i in self.index.get(t, ())}):
            yield i, self.get(i)


def parse(text: str) -> Entities:
    return Entities(text)


def _rec(ents, ref, typ=None):
    if not (isinstance(ref, tuple) and ref[0] == "#"):
        return None
    for t, a in ents.get(ref[1], ()):
        if typ is None or t == typ:
            return t, a
    return None


def _placement(ents, ref) -> np.ndarray:
    """AXIS2_PLACEMENT_3D -> 4x4 matrix from local to parent coordinates."""
    _, a = _rec(ents, ref, "AXIS2_PLACEMENT_3D")
    o = np.array(_rec(ents, a[1], "CARTESIAN_POINT")[1][1], float)
    z = np.array(_rec(ents, a[2], "DIRECTION")[1][1], float) if _rec(ents, a[2]) else np.array([0, 0, 1.])
    x = np.array(_rec(ents, a[3], "DIRECTION")[1][1], float) if _rec(ents, a[3]) else np.array([1, 0, 0.])
    z /= np.linalg.norm(z)
    x = x - (x @ z) * z
    if np.linalg.norm(x) < 1e-12:
        x = np.eye(3)[np.argmin(np.abs(z))]; x = x - (x @ z) * z
    x /= np.linalg.norm(x)
    T = np.eye(4)
    T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = x, np.cross(z, x), z, o
    return T


def _point(ents, ref):
    vp = _rec(ents, ref, "VERTEX_POINT")
    return np.array(_rec(ents, vp[1][1], "CARTESIAN_POINT")[1][1], float) if vp else None


def _edge_mid(ents, e):
    """Midpoint of an EDGE_CURVE on a LINE or CIRCLE; None for other curves."""
    a, b, curve = _point(ents, e[1]), _point(ents, e[2]), _rec(ents, e[3])
    if a is None or b is None or not curve:
        return None
    if curve[0] == "LINE":
        return (a + b) / 2
    if curve[0] != "CIRCLE":
        return None
    T, r = _placement(ents, curve[1][1]), float(curve[1][2])
    ang = lambda p: np.arctan2((p - T[:3, 3]) @ T[:3, 1], (p - T[:3, 3]) @ T[:3, 0])
    t1, t2 = (ang(a), ang(b)) if e[4] != ".F." else (ang(b), ang(a))   # along the curve's own direction
    span = (t2 - t1) % (2 * np.pi) or 2 * np.pi                        # a closed circle: the whole turn
    t = t1 + span / 2
    return T[:3, 3] + r * (np.cos(t) * T[:3, 0] + np.sin(t) * T[:3, 1])


def all_faces(ents) -> dict:
    """{face id: (name, vertex points, surface entity type, edge midpoints)} for every ADVANCED_FACE; name '' when it
    has none. Midpoints only of straight and circular edges (enough to tell the two halves of a cylinder apart)."""
    out = {}
    for fid, recs in ents.of_type("ADVANCED_FACE", "FACE_SURFACE"):
        for t, a in recs:
            if t not in ("ADVANCED_FACE", "FACE_SURFACE") or not a:
                continue
            pts, mids = [], []
            for b in a[1]:
                bound = _rec(ents, b)
                if not bound:
                    continue
                loop = _rec(ents, bound[1][1])
                if not loop:
                    continue
                if loop[0] == "VERTEX_LOOP":
                    verts = [loop[1][1]]
                else:
                    verts = []
                    for oe in loop[1][1]:
                        _, o = _rec(ents, oe, "ORIENTED_EDGE")
                        _, e = _rec(ents, o[3], "EDGE_CURVE")
                        verts += [e[1], e[2]]
                        mid = _edge_mid(ents, e)
                        if mid is not None:
                            mids.append(mid)
                for v in verts:
                    vp = _rec(ents, v, "VERTEX_POINT")
                    if vp:
                        pts.append(_rec(ents, vp[1][1], "CARTESIAN_POINT")[1][1])
            if pts:
                surf = _rec(ents, a[2])
                out[fid] = (a[0].strip() if isinstance(a[0], str) else '', np.unique(np.array(pts, float), axis=0),
                            surf[0] if surf else '', np.array(mids, float).reshape(-1, 3))
    return out


def face_owners(ents) -> tuple[dict, dict]:
    """{face id: representation id} through shell -> solid -> representation items, and {face id: shell id}."""
    face_shell = {}
    for sid, recs in ents.of_type("CLOSED_SHELL", "OPEN_SHELL"):
        for t, a in recs:
            if t in ("CLOSED_SHELL", "OPEN_SHELL"):
                for f in a[1]:
                    face_shell[f[1]] = sid
    shell_item = {}
    for iid, recs in ents.of_type("MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS", "SHELL_BASED_SURFACE_MODEL"):
        for t, a in recs:
            if t == "MANIFOLD_SOLID_BREP":
                shell_item[a[1][1]] = iid
            elif t == "BREP_WITH_VOIDS":
                for s in [a[1]] + list(a[2]):
                    shell_item[s[1]] = iid
            elif t in ("SHELL_BASED_SURFACE_MODEL",):
                for s in a[1]:
                    shell_item[s[1]] = iid
    item_rep = {}
    for rid, recs in ents.of_type("SHAPE_REPRESENTATION", suffix=True):
        for t, a in recs:
            if t.endswith("SHAPE_REPRESENTATION") and len(a) > 1 and isinstance(a[1], list):
                for it in a[1]:
                    if isinstance(it, tuple):
                        item_rep[it[1]] = rid
    return {f: item_rep.get(shell_item.get(s)) for f, s in face_shell.items()}, face_shell


def relations(ents) -> list[tuple[int, int, tuple | None]]:
    """(rep_1, rep_2, transform or None) for every representation relationship."""
    out = []
    for _, recs in ents.of_type("REPRESENTATION_RELATIONSHIP", "SHAPE_REPRESENTATION_RELATIONSHIP"):
        rel = next((a for t, a in recs if t in ("REPRESENTATION_RELATIONSHIP", "SHAPE_REPRESENTATION_RELATIONSHIP")
                    and len(a) >= 4 and isinstance(a[2], tuple) and isinstance(a[3], tuple)), None)
        if rel:
            tr = next((a for t, a in recs if t == "REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION"), None)
            out.append((rel[2][1], rel[3][1], tr[0] if tr else None))
    return out


def rep_transforms(ents, rels, rep, seen=frozenset()) -> list[np.ndarray]:
    """Every placement of a representation in the world: the products of its assembly transforms. A relationship
    without a transform links two representations of the same shape (either way round). The child of a transform is
    rep_1; both conventions of ITEM_DEFINED_TRANSFORMATION are returned (writers disagree) and the vertex match picks
    the right one."""
    seen = seen | {rep}
    if len(seen) > 20:
        return [np.eye(4)]
    out = []
    for r1, r2, tr in rels:
        if tr is None and rep in (r1, r2):
            other = r2 if r1 == rep else r1
            if other not in seen:
                out += rep_transforms(ents, rels, other, seen)
        elif tr is not None and r1 == rep and r2 not in seen:
            idt = _rec(ents, tr, "ITEM_DEFINED_TRANSFORMATION")
            if not idt:
                continue
            A, B = _placement(ents, idt[1][2]), _placement(ents, idt[1][3])
            for P in rep_transforms(ents, rels, r2, seen):
                out += [P @ B @ np.linalg.inv(A), P @ A @ np.linalg.inv(B)]
    return out or [np.eye(4)]


SCALES = (1e-3, 1.0, 1e-2, 0.0254, 0.3048)                 # file length unit -> metres (the best match wins)
SURFACE = {"PLANE": "Plane", "CYLINDRICAL_SURFACE": "Cylinder", "CONICAL_SURFACE": "Cone",
           "SPHERICAL_SURFACE": "Sphere", "TOROIDAL_SURFACE": "Torus"}


def gmsh_topology(gmsh):
    """The imported model as the matcher needs it: {face: (vertex points, surface type, volumes)}, {volume: points}."""
    def points(dim, tag):
        pts = gmsh.model.getBoundary([(dim, tag)], combined=False, oriented=False, recursive=True)
        return np.array([gmsh.model.getValue(0, p, []) for d, p in pts if d == 0], float).reshape(-1, 3)
    def mids(tag):
        out = []
        for _, c in gmsh.model.getBoundary([(2, tag)], combined=False, oriented=False):
            lo, hi = gmsh.model.getParametrizationBounds(1, abs(c))
            out.append(gmsh.model.getValue(1, abs(c), [(lo[0] + hi[0]) / 2]))
        return np.array(out, float).reshape(-1, 3)
    faces = {t: [points(2, t), gmsh.model.getType(2, t), [int(v) for v in gmsh.model.getAdjacencies(2, t)[0]], None]
             for _, t in gmsh.model.getEntities(2)}
    allv = np.concatenate([f[0] for f in faces.values()] or [np.zeros((1, 3))])
    tol = (float(np.linalg.norm(np.ptp(allv, axis=0))) or 1.0) * 1e-6
    groups = {}
    for t, f in faces.items():
        groups.setdefault(frozenset(map(tuple, np.round(f[0] / tol).astype(np.int64).tolist())), []).append(t)
    for tags in groups.values():
        if len(tags) > 1:                       # only these need the finer signature
            for t in tags:
                faces[t][3] = mids(t)
    vols = {t: points(3, t) for _, t in gmsh.model.getEntities(3)}
    return {t: tuple(f) for t, f in faces.items()}, vols


def match(text: str, faces: dict, vols: dict | None = None) -> dict:
    """faces: {tag: (vertex points (k, 3) in metres, gmsh surface type, [volumes])}, vols: {volume: vertex points}.
    Returns {face tag: name}. Several gmsh faces can share a vertex set: the coincident faces of two touching bodies,
    two halves of a split cylinder. The surface type and the body (its vertex set) tell them apart; a face that is
    still ambiguous stays unnamed rather than getting a wrong name."""
    ents = parse(text)
    every = all_faces(ents)
    if not faces or not any(f[0] for f in every.values()):
        return {}
    from scipy.spatial import cKDTree
    owner, shell_of = face_owners(ents)
    allv = np.concatenate([f[0] for f in faces.values()])
    tol = (float(np.linalg.norm(np.ptp(allv, axis=0))) or 1.0) * 1e-6
    uniq = np.unique(np.round(allv / tol), axis=0) * tol      # one point per CAD vertex
    tree = cKDTree(uniq)
    ids = lambda pts: frozenset(tree.query(pts)[1].tolist()) if len(pts) else frozenset()
    by_set = {}
    for tag, f in faces.items():
        by_set.setdefault(ids(f[0]), []).append((tag, f[1], f[2], f[3] if len(f) > 3 else None))
    vol_set = {t: ids(v) for t, v in (vols or {}).items()}
    shells = {}
    for fid, sid in shell_of.items():
        if fid in every:
            shells.setdefault(sid, []).append(every[fid][1])
    shell_pts = {sid: np.concatenate(p) for sid, p in shells.items()}
    rels = relations(ents)
    reps = {r: rep_transforms(ents, rels, r) if r else [np.eye(4)] for r in set(owner.values())}
    best = {}
    for scale in SCALES:
        found = {}
        for fid, (name, pts, surf, emid) in every.items():
            if not name:
                continue
            for T in reps.get(owner.get(fid), [np.eye(4)]):     # every placement: a part can be used twice
                move = lambda p: (np.c_[p, np.ones(len(p))] @ T.T)[:, :3] * scale
                d, i = tree.query(move(pts))
                if d.max() > 2 * tol:
                    continue
                cands = by_set.get(frozenset(i.tolist()), [])
                if len(cands) > 1 and SURFACE.get(surf):
                    cands = [c for c in cands if c[1] == SURFACE[surf]]
                if len(cands) > 1 and vol_set and shell_of.get(fid) in shell_pts:
                    body = ids(move(shell_pts[shell_of[fid]]))
                    cands = [c for c in cands if any(vol_set.get(v) == body for v in c[2])]
                if len(cands) > 1 and len(emid):
                    want = move(emid)
                    cands = [c for c in cands if c[3] is not None and len(c[3])
                             and cKDTree(c[3]).query(want)[0].max() <= 2 * tol]
                if cands:
                    found.setdefault(fid, []).append([c[0] for c in cands])
        if len(found) > len(best):
            best = found
    out = {}
    for fid, hits in best.items():
        for tags in hits:
            if len(tags) == 1:
                out.setdefault(tags[0], set()).add(every[fid][0])
    return {tag: names.pop() for tag, names in out.items() if len(names) == 1}
