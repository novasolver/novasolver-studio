"""Case storage. case.json is the single source of truth; every change bumps revision and keeps the old copy."""
from __future__ import annotations

import copy
import json
import math
import os
import re
import secrets
import time
from pathlib import Path

from . import templates, units
from .config import workspace


class StudioError(Exception):
    """Error with a message key so the caller can localize it and tell the model what to fix."""

    def __init__(self, key: str, status: int = 400, **kw):
        super().__init__(key)
        self.key, self.status, self.kw = key, status, kw


_ID = re.compile(r"^c_[0-9a-z_]{4,40}$")


def cases_dir() -> Path:
    return workspace() / "cases"


def case_dir(case_id: str) -> Path:
    if not _ID.match(case_id or ""):
        raise StudioError("err.not_found", 404, case_id=case_id)
    d = (cases_dir() / case_id).resolve()
    if d.parent != cases_dir().resolve():          # path confinement
        raise StudioError("err.not_found", 404, case_id=case_id)
    if not (d / "case.json").is_file():
        raise StudioError("err.not_found", 404, case_id=case_id)
    return d


def new_id() -> str:
    return "c_" + time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(2)


def _write_json(path: Path, data) -> None:
    """Atomic write. On Windows the final rename fails while another process has the file open for reading
    (GUI polling, MCP job_status), so retry briefly instead of failing the job."""
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for attempt in range(60):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (1 + attempt % 5))
    os.replace(tmp, path)


def create(template_id: str) -> dict:
    try:
        templates.get(template_id)
    except KeyError:
        raise StudioError("err.path", 400, path=f"template={template_id}")
    cid = new_id()
    d = cases_dir() / cid
    (d / "revisions").mkdir(parents=True)
    case = templates.new_case(template_id, cid)
    case["provenance"]["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write_json(d / "case.json", case)
    return case


def load(case_id: str) -> dict:
    return json.loads((case_dir(case_id) / "case.json").read_text(encoding="utf-8"))


class case_lock:
    """Per-case lock shared by every process (the UI server and the MCP server are separate processes), so that
    load -> check revision -> apply -> save is one step and a second writer gets 409 instead of erasing the first."""

    def __init__(self, case_id: str, timeout: float = 10.0, stale: float = 30.0):
        self.path = case_dir(case_id) / ".lock"
        self.timeout, self.stale = timeout, stale

    def __enter__(self):
        t0 = time.time()
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale:   # a writer that died mid-save
                        self.path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.time() - t0 > self.timeout:
                    raise StudioError("err.busy", 409)
                time.sleep(0.02)

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def save(case: dict, bump: bool = True) -> dict:
    d = case_dir(case["case_id"])
    if bump:
        old = load(case["case_id"])
        _write_json(d / "revisions" / f"{old['revision']}.json", old)
        case["revision"] = old["revision"] + 1
    _write_json(d / "case.json", case)
    return case


def list_all() -> list[dict]:
    out = []
    for d in sorted(cases_dir().glob("c_*"), reverse=True):
        f = d / "case.json"
        if f.is_file():
            c = json.loads(f.read_text(encoding="utf-8"))
            tp = templates.TEMPLATES.get(c["template"], {})
            out.append({"case_id": c["case_id"], "template": c["template"], "title": c["title"], "revision": c["revision"],
                        "physics": tp.get("physics"), "source_file": c["geometry"].get("name")})
    return out


def delete(case_id: str) -> int:
    import shutil
    d = case_dir(case_id)
    size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
    shutil.rmtree(d)
    return size


# ---------------------------------------------------------------- editing

def editable_paths(case: dict) -> list[str]:
    tp = templates.get(case["template"])
    paths = [p for p, *_ in tp["params"]]
    paths += ["mesh.size", "run.mode"]
    if case["physics"]["kind"] == "dc-current":
        paths.append("physics.joule_heating")
    if "flow" in case:
        paths += ["flow.speed", "flow.direction"]
    for b in case.get("bodies", {}):
        paths += [f"bodies.{b}.role", f"bodies.{b}.material"]
    for b in case.get("body_materials", {}):           # multi-material assembly (structural / thermal)
        paths += [f"body_materials.{b}"] + [f"body_props.{b}.{p}" for p in templates.BODY_PROPS]
    mats = case["materials"]
    if "solid" in mats:
        paths += ["materials.solid.preset", "materials.solid.E", "materials.solid.nu", "materials.solid.sy",
                  "materials.solid.k", "materials.solid.eps_r", "materials.solid.sigma"]
    if "fluid" in mats:
        paths += ["materials.fluid.preset", "materials.fluid.nu"]
    for face in templates.face_keys(case):
        if face in tp["locked_faces"]:
            continue
        paths.append(f"boundaries.{face}.role")
        paths += [f"boundaries.{face}.{k}" for k in templates.VALUE_FIELDS]
        if case["physics"]["kind"] == "dc-current":
            paths += [f"boundaries.{face}.thermal.role"]
            paths += [f"boundaries.{face}.thermal.{k}" for r in templates.THERMAL_ROLES for k in templates.ROLE_FIELDS.get(r, {})]
        if tp.get("import") and case["mesh"].get("method") == "gmsh":
            paths.append(f"mesh.refine.{face}")      # local element size on this face (a fillet, a notch)
    return sorted(set(paths))


ENUMS = {
    "mesh.size": ["coarse", "normal", "fine"],
    "run.mode": ["preview", "final"],
    "flow.direction": ["+x", "-x", "+y", "-y", "+z", "-z"],
}

GEOM_KEYS = ("geometry.", "mesh.")


def apply_changes(case: dict, changes: dict) -> tuple[dict, list[dict]]:
    """Apply {dotted.path: value}. Returns (new_case, diff). Raises StudioError with a fixable message."""
    tp = templates.get(case["template"])
    allowed = set(editable_paths(case))
    expanded = {}
    for path, value in changes.items():
        if path.startswith('boundaries.@'):
            tail = path[len('boundaries.@'):]
            names = [name for name in case.get('face_groups', {}) if tail.startswith(name + '.')]
            if not names:
                raise StudioError('err.unknown_group', 400, name=tail.rsplit('.', 1)[0])
            name = max(names, key=len)  # CAD names can contain dots; prefer the longest matching group name.
            field = tail[len(name) + 1:]
            for face in case['face_groups'][name]:
                expanded[f'boundaries.{face}.{field}'] = value
        else:
            expanded[path] = value
    changes = expanded
    new = copy.deepcopy(case)
    diff = []
    # roles first, so that values sent in the same call land on the new role
    ordered = sorted(changes.items(), key=lambda kv: 0 if kv[0].endswith(".role") else 1)
    for path, value in ordered:
        if path.startswith('face_groups.'):
            name = path[len('face_groups.'):]
            if not name.strip() or len(name) > 100:
                raise StudioError('err.path', 400, path=path)
            if value is not None and (not isinstance(value, list) or
                    any(not isinstance(k, str) or k not in templates.face_keys(case) for k in value)):
                raise StudioError('err.group_members', 400)
            groups = new.setdefault('face_groups', {})
            old = groups.get(name)
            if value is None:
                groups.pop(name, None)
            else:
                groups[name] = list(dict.fromkeys(value))
            diff.append({'path': path, 'old': old, 'new': groups.get(name)})
            continue
        if path not in allowed:
            raise StudioError("err.path", 400, path=path)
        parts = path.split(".")
        parent = new
        for p in parts[:-1]:
            parent = parent.setdefault(p, {})
        key = parts[-1]
        old = parent.get(key)
        if path == "physics.joule_heating":
            if not isinstance(value, bool):
                raise StudioError("err.path", 400, path=path)
            nv = value
        elif path in ENUMS:
            if value not in ENUMS[path]:
                raise StudioError("err.path", 400, path=f"{path}={value} (allowed: {', '.join(ENUMS[path])})")
            nv = value
        elif parts[0] == "bodies" and key == "role":     # before the face-role branch, which would swallow it
            if value not in ("fluid", "solid"):
                raise StudioError("err.path", 400, path=f"{path}={value} (allowed: fluid, solid)")
            nv = value
        elif key == "role":
            if tp.get("fixed_roles") and value != old:
                raise StudioError("err.fixed_roles", 400, path=path)
            roles = templates.THERMAL_ROLES if "thermal" in parts else tp["roles"]
            if value not in roles or value == "plane2d":
                raise StudioError("err.role", 400, role=value, roles=", ".join(r for r in roles if r != "plane2d"))
            nv = value
        elif parts[0] == "bodies" and key == "material":
            allowed_m = list(templates.FLUID_PROPS) if new["bodies"][parts[1]]["role"] == "fluid" else list(templates.SOLID_PROPS)
            if value not in allowed_m:
                raise StudioError("err.path", 400, path=f"{path}={value} (allowed: {', '.join(allowed_m)})")
            nv = value
        elif parts[0] == "body_materials":
            if value not in templates.MATERIALS_SOLID:
                raise StudioError("err.path", 400, path=f"{path}={value} (allowed: {', '.join(templates.MATERIALS_SOLID)})")
            nv = value
            new.get("body_props", {}).pop(parts[1], None)     # a new preset drops the old overrides
        elif parts[0] == "body_props":
            if value in (None, "", "none"):                    # back to the preset's value
                parent.pop(key, None)
                diff.append({"path": path, "old": old, "new": None})
                continue
            try:
                nv = units.normalize(value, old if isinstance(old, dict) else
                                     {"value": 1.0, "unit": templates.BODY_PROPS[key]})
                si = units.to_si(nv)
            except (units.UnitError, TypeError, ValueError) as e:
                raise StudioError("err.unit", 400, msg=str(e))
            if not (not isinstance(si, list) and math.isfinite(si) and si > 0 and
                    (key != "nu" or si < 0.5) and (key != "eps_r" or si >= 1)):
                raise StudioError("err.range", 400, path=path, lo="1" if key == "eps_r" else "0", hi="0.5" if key == "nu" else "-")
        elif parts[:2] == ["mesh", "refine"]:
            if value in (None, "", "none", 0):         # back to the automatic size
                parent.pop(key, None)
                diff.append({"path": path, "old": old, "new": None})
                continue
            try:
                nv = units.normalize(value, {"value": 1.0, "unit": "mm"})
                si = units.to_si(nv)
            except (units.UnitError, TypeError, ValueError) as e:
                raise StudioError("err.unit", 400, msg=str(e))
            if not si > 0:
                raise StudioError("err.range", 400, path=path, lo="0 mm", hi="-")
        elif key == "components":                      # constraint role: which displacement components are held
            if new["boundaries"].get(parts[1], {}).get("role") != "constraint":
                raise StudioError("err.path", 400, path=f"{path} (only the 'constraint' role has components)")
            if not (isinstance(value, str) and value and set(value) <= set("xyz") and len(set(value)) == len(value)):
                raise StudioError("err.path", 400, path=f"{path}={value} (one or more of x, y, z, e.g. \"xy\")")
            nv = "".join(c for c in "xyz" if c in value)
        elif key == "direction":
            if value not in templates.DIRECTIONS:
                raise StudioError("err.path", 400, path=f"{path}={value} (allowed: {', '.join(templates.DIRECTIONS)})")
            nv = value
        elif key == "preset":
            presets = templates.MATERIALS_SOLID if parts[1] == "solid" else templates.MATERIALS_FLUID
            if value != "custom" and value not in presets:
                raise StudioError("err.path", 400, path=f"{path}={value} (allowed: custom, {', '.join(presets)})")
            nv = value
            if value != "custom":
                for k, q in presets[value].items():
                    parent[k] = copy.deepcopy(q)
        else:
            if parts[0] == "boundaries":
                role = parent.get("role")
                if key not in templates.ROLE_FIELDS.get(role, {}):
                    raise StudioError("err.path", 400, path=f"{path} (role '{role}' has no '{key}')")
            ref_old = old if isinstance(old, dict) else _default_quantity(path)
            try:
                nv = units.normalize(value, ref_old)
                si = units.to_si(nv)
            except (units.UnitError, TypeError, ValueError) as e:
                raise StudioError("err.unit", 400, msg=str(e))
            bounds = templates.bounds_si(case["template"]).get(path)
            if bounds and not isinstance(si, list):
                lo, hi = bounds
                if not (lo <= si <= hi):
                    unit = nv["unit"]
                    raise StudioError("err.range", 400, path=path, lo=f"{units.from_si(lo, unit):g} {unit}",
                                      hi=f"{units.from_si(hi, unit):g} {unit}")
            if path.startswith("materials.") and key in ("eps_r", "sigma") and isinstance(si, list):
                raise StudioError("err.range", 400, path=path, lo="1" if key == "eps_r" else "0", hi="-")
            if path.startswith("materials.") and not isinstance(si, list):
                # physical range for every template (a negative modulus solves "fine" and mirrors the answer)
                poisson = parts[1] == "solid" and key == "nu"
                ok = math.isfinite(si) and ((0 <= si < 0.5) if poisson else si >= 1 if key == "eps_r" else si > 0)
                if not ok:
                    raise StudioError("err.range", 400, path=path, lo="1" if key == "eps_r" else "0", hi="0.5" if poisson else "-")
            if path.startswith("materials.") and parts[1] in new["materials"]:
                new["materials"][parts[1]]["preset"] = "custom"
        parent[key] = nv
        diff.append({"path": path, "old": old, "new": nv})
    normalize_boundaries(new)
    if new["geometry"]["kind"] == "tube":
        p = new["geometry"]["params"]
        if units.to_si(p["a"]) >= units.to_si(p["b"]):
            raise StudioError("err.tube_radii", 400)
    if new.get("bodies"):
        normalize_conjugate(new)
    if any(d["path"].startswith(GEOM_KEYS) for d in diff):
        new.setdefault("provenance", {})["mesh_stale"] = True
        templates.face_descriptors(new)
    return new, diff


def history(case_id: str) -> dict:
    path = case_dir(case_id) / 'history.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'undo': [], 'redo': []}


def record_change(before: dict, after: dict, paths: list[str], source: str) -> None:
    h = history(before['case_id'])
    now = time.time()
    paths = sorted(paths)
    prev = h['undo'][-1] if h['undo'] else None
    if (not h['redo'] and prev and prev['source'] == source and prev['paths'] == paths
            and prev['rev_after'] == before['revision'] and 0 <= now - prev['ts'] <= 2):
        prev.update(rev_after=after['revision'], ts=now)
    else:
        h['undo'].append({'rev_before': before['revision'], 'rev_after': after['revision'],
                          'ts': now, 'source': source, 'paths': paths, 'before': before})
    h['undo'] = h['undo'][-100:]
    h['redo'] = []
    _write_json(case_dir(before['case_id']) / 'history.json', h)


def body_of_face(case: dict) -> dict:
    return {f["key"]: f.get("bodies", [None])[0] for f in case["geometry"].get("faces", []) if not f.get("interface")}


def normalize_conjugate(case: dict) -> None:
    """Face roles must match their body: water faces take water-* roles, solid faces take thermal roles.
    A body switched between fluid and solid gets a valid material and default face roles."""
    for b, info in case["bodies"].items():
        if info["role"] == "fluid" and info.get("material") not in templates.FLUID_PROPS:
            info["material"] = "water"
        if info["role"] == "solid" and info.get("material") not in templates.SOLID_PROPS:
            info["material"] = "aluminium"
    for face, body in body_of_face(case).items():
        role = case["boundaries"].setdefault(face, {"role": "insulated"}).get("role")
        fluid = case["bodies"].get(body, {}).get("role") == "fluid"
        if fluid and role not in templates.CONJUGATE_FLUID_ROLES:
            case["boundaries"][face] = {"role": "water-wall"}
        elif not fluid and role not in templates.CONJUGATE_SOLID_ROLES:
            case["boundaries"][face] = {"role": "insulated"}
    normalize_boundaries(case)


def normalize_boundaries(case: dict) -> None:
    """Each face carries exactly the value fields its role needs (defaults filled in, others dropped)."""
    for face, b in case["boundaries"].items():
        thermal = b.get("thermal", {"role": "insulated"}) if case["physics"]["kind"] == "dc-current" else None
        want = templates.ROLE_FIELDS.get(b.get("role"), {})
        for k in list(b):
            if k != "role" and k not in want:
                b.pop(k)
        for k, default in want.items():
            if k not in b:
                b[k] = copy.deepcopy(default)
        if thermal is not None:
            fields = templates.ROLE_FIELDS.get(thermal.get("role"), {})
            b["thermal"] = {"role": thermal.get("role", "insulated"),
                            **{k: copy.deepcopy(thermal.get(k, v)) for k, v in fields.items()}}


def _default_quantity(path: str) -> dict:
    key = path.rsplit(".", 1)[-1]
    for fields in templates.ROLE_FIELDS.values():
        if key in fields and isinstance(fields[key], dict):
            return copy.deepcopy(fields[key])
    if path.endswith(".nu") and "fluid" in path:
        return {"value": 1e-6, "unit": "m2/s"}
    if path.endswith(".nu"):
        return {"value": 0.3, "unit": "-"}
    if path.endswith(".E"):
        return {"value": 200, "unit": "GPa"}
    if path == "flow.speed":
        return {"value": 1, "unit": "m/s"}
    if path.endswith(".k"):
        return {"value": 50, "unit": "W/mK"}
    if path.endswith(".sy"):
        return {"value": 235, "unit": "MPa"}
    if path.endswith(".eps_r"):
        return {"value": 1, "unit": "-"}
    if path.endswith(".sigma"):
        return {"value": 1, "unit": "S/m"}
    return {"value": 0, "unit": "-"}
