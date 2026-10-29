"""The single command layer. api.py (GUI), mcp_server.py (AI) and the CLI call only these functions,
so the AI's changes and the user's changes go through the same validation and show up in the same place."""
from __future__ import annotations

import os
import platform
import shutil
import sys
import copy
import time
import json
from pathlib import Path

from . import __version__, checks, config, geometry, jobs, results, store, templates, units
from .config import engines, workspace
from .i18n import lang_of, t
from .store import StudioError

ENGINE_NAMES = {"builtin-fem": "Built-in FEM (preview)", "builtin-cavity": "Built-in CFD (preview)",
                "calculix": "CalculiX", "openfoam": "OpenFOAM"}


# ------------------------------------------------------------------ environment & templates

def environment_check(lang: str = "ja") -> dict:
    eng = engines()
    # how an MCP client starts this very installation: the packaged exe has an `mcp` subcommand, a source checkout
    # runs the module with the interpreter that is serving now
    frozen = bool(getattr(sys, "frozen", False))
    # an installed package (pip / pipx / uvx) also uses this interpreter: uv is not a dependency, so a "uvx" command
    # would fail where it is missing, and could start a different Studio where it is not
    mcp_command = {"command": sys.executable, "args": ["mcp"] if frozen else ["-m", "novastudio", "mcp"]}
    alternatives = []
    if config.INSTALLED and shutil.which("uvx"):
        alternatives.append({"command": "uvx", "args": ["novasolver-studio", "mcp"]})
    # an MCP client starts the server itself and does not inherit this process: a source checkout needs its backend
    # folder on the path, and a workspace override must follow so the AI sees the same cases as the UI
    env = {} if frozen or config.INSTALLED else {"PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    if os.environ.get("NOVASTUDIO_WORKSPACE"):
        env["NOVASTUDIO_WORKSPACE"] = str(workspace())
    if env:
        mcp_command["env"] = env
    return {"studio_version": __version__, "workspace": str(workspace()), "os": platform.platform(),
            "cpu_count": os.cpu_count(), "mcp_command": mcp_command, "mcp_command_alternatives": alternatives,
            "engines": [{"id": k, "name": ENGINE_NAMES[k], "available": v["available"], "kind": v["kind"]}
                        for k, v in eng.items()],
            "how_to_install": _solver_install(lang)}


def _solver_install(lang: str) -> dict:
    if sys.platform == "win32":
        return {"calculix": "Put ccx.exe in studio/solvers/calculix/ or set NOVASTUDIO_CCX.",
                "openfoam": "Install the OpenFOAM (ESI) Windows MinGW package into studio/solvers/openfoam/ "
                            "or set NOVASTUDIO_OPENFOAM to its folder."}
    os_key = "macos" if sys.platform == "darwin" else "linux"
    return {name: t(f"install.{os_key}.{name}", lang) for name in ("calculix", "openfoam")}


def list_templates(lang: str = "ja") -> dict:
    return {"templates": templates.summary(lang_of(lang))}


# ------------------------------------------------------------------ cases

def _latest_job(case_id: str) -> dict | None:
    js = jobs.list_for_case(case_id)
    if not js:
        return None
    j = js[0]
    if j["state"] == "done":
        try:
            case = store.load(case_id)
            pl = results.payload(case, "en", j["job_id"])
            j = dict(j, gates=pl["gates"], warnings=len(pl["warnings"]))
        except StudioError:
            pass
    return j


POSITION = {"x0": "pos.left", "x1": "pos.right", "y0": "pos.bottom", "y1": "pos.top", "z0": "pos.back", "z1": "pos.front"}


def face_label(tp: dict, key: str, lang: str, case: dict | None = None) -> str:
    """Template label, plus a position suffix when several faces share the same label (e.g. three 'wall' faces).
    Imported shapes: "Face n" plus the surface type."""
    if tp.get("import") or (case or {}).get("geometry", {}).get("kind") == "import":
        info = next((f for f in (case or {}).get("geometry", {}).get("faces", []) if f["key"] == key), None)
        n = info["n"] if info else key
        typ = t(f"surf.{info['type']}", lang) if info and info.get("type") else ""
        base = t('face.generic', lang, n=n)
        if info and info.get('name'):
            return t('face.named', lang, name=info['name'], face=base)
        direction = axis_word((info or {}).get('normal') or (info or {}).get('axis'))
        if info and info.get('type') == 'Cylinder' and info.get('radius'):
            return (base + ' · ' + typ + t('face.radius', lang, r=f"{info['radius']*1e3:g}") +
                    (t('face.axis', lang, axis=direction.lstrip('+-')) if direction else ''))
        return (base + (f" · {typ}" if typ and not typ.startswith('surf.') else '') +
                (f' {direction}' if direction else '') +
                (f" · {info['area']*1e6:,.4g} mm²" if info and info.get('area') is not None else ''))
    base = tp["face_labels"].get(key,'face.'+key)
    if sum(1 for v in tp["face_labels"].values() if v == base) > 1:
        return f"{t(base, lang)} ({t(POSITION[key], lang)})"
    return t(base, lang)


def axis_word(vector) -> str:
    import math
    if not vector:
        return ''
    i = max(range(3), key=lambda j: abs(vector[j]))
    return ('+' if vector[i] > 0 else '-') + 'XYZ'[i] if abs(vector[i]) >= math.cos(math.radians(2)) else ''


def face_descriptor(case: dict, f: dict, lang: str) -> dict:
    out = {k: f[k] for k in ('key', 'n', 'type', 'name', 'color', 'normal', 'axis', 'neighbors', 'smooth_neighbors') if k in f}
    out['label'] = face_label(templates.get(case['template']), f['key'], lang, case)
    out['role'] = case['boundaries'].get(f['key'], {}).get('role')
    if f.get('interface'):
        from .contact import settings
        out.update(interface=True,bodies=f.get('bodies',[]),contact=settings(case,f['key']))
    for k, scale, suffix in (('area', 1e6, '_mm2'), ('radius', 1e3, '_mm'), ('centroid', 1e3, '_mm'),
                              ('axis_point', 1e3, '_mm'), ('bbox', 1e3, '_mm')):
        if k in f:
            def scaled(v):
                return [scaled(x) for x in v] if isinstance(v, list) else round(v*scale, 2 if k in ('area', 'centroid') else 3)
            out[k+suffix] = scaled(f[k])
    return out


def history_summary(entry: dict, lang: str, mark_ai: bool = True) -> str:
    paths = entry['paths']
    faces = list(dict.fromkeys(p.split('.')[1] for p in paths if p.startswith('boundaries.')))
    if faces:
        first = face_label(templates.get(entry['before']['template']), faces[0], lang, entry['before']).split(' · ')[0]
        # a role change comes with its values ("pressure + 1 MPa"): name the role change, not the first value
        field = 'role' if any(p.endswith('.role') for p in paths) else paths[0].rsplit('.', 1)[-1]
        label = t('field.' + field, lang) if field != 'role' else t('history.role', lang)
        summary = t('history.faces' if len(faces) > 1 else 'history.face', lang, face=first, n=len(faces)-1, field=label)
    else:
        section = paths[0].split('.')[0] if paths else 'case'
        summary = t('history.' + section, lang)
    return summary + (t('history.ai', lang) if mark_ai and entry['source'] == 'ai' else '')


def history_payload(case_id: str, lang: str) -> dict:
    h = store.history(case_id)
    return {'undo': [{'rev': e['rev_after'], 'source': e['source'], 'ts': e['ts'], 'summary': history_summary(e, lang)}
                     for e in reversed(h['undo'][-10:])], 'redo_count': len(h['redo'])}


def job_view(j: dict, lang: str) -> dict:
    eta = None
    nonlinear = str(j.get('message_key','')).startswith('job.nonlinear')
    if j["state"] == "running" and not nonlinear and j.get("progress", 0) > 0.02:
        import time
        elapsed = time.time() - j["created_at"]
        eta = max(0.0, elapsed * (1 - j["progress"]) / j["progress"])
    return {"job_id": j["job_id"], "case_id": j["case_id"], "state": j["state"], "progress": j.get("progress", 0),
            "eta_s": eta, "engine": j.get("engine"), "mode": j.get("mode"), "revision": j.get("revision"),
            "message": t(j.get("message_key", "job." + j["state"]), lang, **j.get("message_args", {})),
            "gates": j.get("gates")}


def case_payload(case_id: str, lang: str = "ja") -> dict:
    lang = lang_of(lang)
    case = store.load(case_id)
    tp = templates.get(case["template"])
    items = checks.run(case, lang)
    latest = _latest_job(case_id)
    roles = [{"id": r, "label": t(f"role.{r}", lang)} for r in tp["roles"] if r != "plane2d"]
    params = []
    bounds = templates.bounds_si(case["template"])
    for path, label, dim, _lo, _hi in tp["params"]:
        lo, hi = bounds[path]
        node = case
        for p in path.split("."):
            node = node.get(p, {}) if isinstance(node, dict) else {}
        if not node:
            continue
        params.append({"path": path, "label": t(label, lang), "value": node.get("value"), "unit": node.get("unit"),
                       "units": units.UNIT_CHOICES[dim], "min_si": lo, "max_si": hi})
    if tp['physics'] == 'structural':
        material = case['materials']['solid']
        preset = templates.MATERIALS_SOLID.get(material.get('preset'),templates.MATERIALS_SOLID['steel'])
        for key,label,dim in [('E','E','pressure'),('nu','poisson','dimensionless'),('rho','rho','density'),('alpha','alpha','expansion'),('k','k','conductivity')]:
            path = 'materials.solid.'+key
            if not any(v['path'] == path for v in params):
                q = material.get(key,preset[key])
                params.append({'path':path,'label':t('param.'+label,lang),'value':q['value'],'unit':q['unit'],
                               'units':units.UNIT_CHOICES[dim],'min_si':0,'max_si':None})
    faces = []
    info = {f["key"]: f for f in case["geometry"].get("faces", [])}
    for key in templates.face_keys(case):
        b = case["boundaries"].get(key, {})
        values = {k: v for k, v in b.items() if k not in ("role", "thermal")}
        faces.append({"key": key, "region": key, "label": face_label(tp, key, lang, case), "role": b.get("role"),
                      "role_label": t(f"role.{b.get('role')}", lang), "locked": key in tp["locked_faces"],
                      "value": b.get("force") or b.get("pressure") or b.get("speed") or b.get("temperature") or b.get("flux"),
                      "values": values, "thermal": b.get("thermal"), "area_m2": info.get(key, {}).get("area"),
                      "descriptor": info.get(key, {})})
    mat_kind = "solid" if "solid" in case["materials"] else "fluid"
    presets = templates.MATERIALS_SOLID if mat_kind == "solid" else templates.MATERIALS_FLUID
    ms = geometry.mesh_state(case)
    return {
        "case": case,
        "history": history_payload(case_id, lang),
        "steps": checks.steps(case, items, latest),
        "checks": items,
        "ready": not any(i["level"] == "error" for i in items),
        "engine": checks.engine_for(case),
        "ui": {"params": params, "roles": roles, "faces": faces,
               'material_models': {b or 'solid':{k:({'value':v,'unit':'Pa'} if k in ('sy','H') else v)
                    for k,v in templates.solid_props(case,b).items() if k in ('model','sy','H')}
                    for b in (list(case.get('body_materials',{})) or [None])} if tp['physics'] == 'structural' else {},
               'interfaces': [dict(face_descriptor(case,f,lang),area_m2=f.get('area')) for f in info.values() if f.get('interface')],
               "thermal_roles": [{"id": r, "label": t(f"role.{r}", lang)} for r in templates.THERMAL_ROLES],
               "role_fields": {r: list(templates.ROLE_FIELDS.get(r, {})) for r in set(tp["roles"] + templates.THERMAL_ROLES)},
               "field_labels": {k: t(f"field.{k}", lang) for k in templates.VALUE_FIELDS},
               "field_units": {k: units.UNIT_CHOICES.get(units.dimension(v["unit"]), [])
                               for fl in templates.ROLE_FIELDS.values() for k, v in fl.items() if isinstance(v, dict)},
               "directions": [{"id": d, "label": t(f"dir.{d}", lang)} for d in templates.DIRECTIONS],
               "physics": tp["physics"], "imported": case["geometry"]["kind"] == "import",
               "fixed_roles": bool(tp.get("fixed_roles")),
               "flow": ({"direction": case["flow"]["direction"],
                         "directions": [{"id": d, "label": t(f"dir.{d}", lang)} for d in ("+x", "-x", "+y", "-y", "+z", "-z")]}
                        if case.get("flow") else None),
               "source_file": case["geometry"].get("name"),
               "materials": [{"id": k, "label": t(f"material.{k}", lang)} for k in [*presets, "custom"]],
               "material_kind": mat_kind,
               "mesh": {"size": case["mesh"]["size"], "sizes": ["coarse", "normal", "fine"], "state": ms},
               "modes": [{"id": "preview", "engine": next((e for e in tp["engines"] if e.startswith("builtin")), None)},
                         {"id": "final", "engine": next((e for e in tp["engines"] if not e.startswith("builtin")), None)}]},
        "jobs": [job_view(j, lang) for j in jobs.list_for_case(case_id)[:5]],
        "latest_run": job_view(latest, lang) if latest else None,
    }


def create_case(template: str, params: dict | None = None, lang: str = "ja", source: str = 'gui') -> dict:
    tp = templates.TEMPLATES.get(template, {})
    if tp.get("sample"):                       # benchmark built on a bundled CAD file (e.g. sphere drag)
        pl = import_geometry(tp["physics"], tp["sample"], path=str(_samples_dir() / tp["sample"]), lang=lang,
                             template=template)
        if params:
            update_case(pl["case"]["case_id"], pl["case"]["revision"], params, lang, source=source)
            pl = case_payload(pl["case"]["case_id"], lang)
        return pl
    case = store.create(template)
    if params:
        update_case(case["case_id"], case["revision"], params, lang, source=source)
    return case_payload(case["case_id"], lang)


STL_UNITS = {"mm": 1e-3, "m": 1.0, "inch": 0.0254}     # an STL has no units: the user says which
CAD_EXT = {".step": "step", ".stp": "step", ".iges": "iges", ".igs": "iges", ".brep": "brep", ".brp": "brep", ".stl": "stl"}
MAX_CAD_BYTES = 200 * 1024 * 1024
PHYSICS = ("structural", "thermal", "flow", "external", "conjugate", "electrostatic", "current")


def faceted_step_check(data: bytes) -> None:
    """A STEP that is really a triangle mesh (thousands of flat faces, as written by mesh-to-STEP converters) takes
    minutes to read and gives a face per triangle. Say so at once and point to the STL route, which handles it."""
    import re
    text = data.decode("latin-1")
    faces = len(re.findall(r"ADVANCED_FACE\s*\(", text))
    planes = len(re.findall(r"=\s*PLANE\s*\(", text))
    if faces > 2000 and planes >= 0.95 * faces:
        raise StudioError("err.faceted_step", 400, faces=faces)


def import_geometry(physics: str, filename: str, data: bytes | None = None, path: str | None = None,
                    lang: str = "ja", template: str | None = None, units: str = "mm") -> dict:
    """Create a case from a CAD file (STEP / IGES / BREP / STL). The file is copied into the case; faces get numbers.
    units applies to STL only (STEP/IGES/BREP carry their own units)."""
    import hashlib
    import json as _json
    import shutil
    from pathlib import Path
    if physics not in PHYSICS:
        raise StudioError("err.path", 400, path=f"physics={physics} (allowed: {', '.join(PHYSICS)})")
    ext = Path(filename).suffix.lower()
    if ext not in CAD_EXT:
        raise StudioError("err.cad_type", 400, ext=ext or "?", allowed=", ".join(sorted(CAD_EXT)))
    if units not in STL_UNITS:
        raise StudioError("err.path", 400, path=f"units={units} (allowed: {', '.join(STL_UNITS)})")
    if path is not None:
        src = Path(path)
        if not src.is_file():
            raise StudioError("err.cad_missing", 404, path=str(src))
        if src.stat().st_size > MAX_CAD_BYTES:
            raise StudioError("err.cad_size", 400, mb=MAX_CAD_BYTES // 2**20)
        data = src.read_bytes()
    if not data:
        raise StudioError("err.cad_missing", 400, path=filename)
    if len(data) > MAX_CAD_BYTES:
        raise StudioError("err.cad_size", 400, mb=MAX_CAD_BYTES // 2**20)
    if ext in (".step", ".stp"):
        faceted_step_check(data)
    case = store.create(template or f"import-{physics}")
    d = store.case_dir(case["case_id"])
    (d / "geometry").mkdir(exist_ok=True)
    (d / "geometry" / f"model{ext}").write_bytes(data)
    if template is None:
        case["title"] = {l: Path(filename).stem for l in ("ja", "en", "zh")}
    case["geometry"].update({"file": f"geometry/model{ext}", "name": Path(filename).name,
                             "sha256": hashlib.sha256(data).hexdigest(), "bbox": [[0, 0, 0], [1, 1, 1]]})
    if ext == ".stl":
        case["geometry"]["units"] = units
    try:
        geometry._run_worker(geometry.worker_job(case, size="normal", volume=False, order=1, out=str(d / "geom")),
                             timeout=300)
    except StudioError:
        shutil.rmtree(d, ignore_errors=True)
        raise
    disp = _json.loads((d / "geom" / "display.json").read_text(encoding="utf-8"))
    case["geometry"]["faces"] = disp["info"]
    case["geometry"]["bbox"] = disp["bbox"]
    case["geometry"]["volumes"] = disp.get("volumes", 1)
    role = templates.DEFAULT_ROLE[physics]
    case["boundaries"] = {f["key"]: {"role": role} for f in disp["info"] if not f.get("interface")}
    if physics == "conjugate":
        bodies = disp.get("bodies") or []
        if len(bodies) < 2:
            shutil.rmtree(d, ignore_errors=True)
            raise StudioError("err.need_two_bodies", 400)
        small = min(bodies, key=lambda b: b["volume"])["key"]    # first guess: the smallest body is the water
        case["bodies"] = {b["key"]: {"role": "fluid" if b["key"] == small else "solid",
                                     "material": "water" if b["key"] == small else "aluminium"} for b in bodies}
        case["geometry"]["bodies"] = bodies
        store.normalize_conjugate(case)
    elif physics in ("structural", "thermal", "electrostatic", "current") and len(disp.get("bodies") or []) >= 2:
        # an assembly: one material per body (all start as the case material; set body_materials.<b>)
        case["body_materials"] = {b["key"]: case["materials"]["solid"]["preset"] for b in disp["bodies"]}
        case["geometry"]["bodies"] = disp["bodies"]
    store.normalize_boundaries(case)
    store.save(case, bump=False)
    gkey = hashlib.sha256(_json.dumps(geometry._canon(case["geometry"]), sort_keys=True).encode()).hexdigest()[:16]
    (d / "geom" / "key.txt").write_text(gkey)          # the surface mesh just made is current
    return case_payload(case["case_id"], lang)


SAMPLES = {
    "cold_plate": {"file": "cold_plate.step", "physics": "conjugate",
                   "title": ("水冷プレート", "Water-cooled plate", "水冷板"),
                   "description": ("アルミ板の流路に水を流して冷やす。上面のヒーターの熱を水がどれだけ運ぶかを求める練習用。",
                                   "Water flows through a channel in an aluminium plate. Find how much of the heater's heat the water carries away.",
                                   "水流经铝板中的流道进行冷却，求水带走多少加热器的热量。")},
    "pipe_elbow": {"file": "pipe_elbow.step", "physics": "flow",
                   "title": ("90°エルボ管", "90° pipe elbow", "90° 弯管"),
                   "description": ("内径 20 mm の曲がり管の中の流れ。入口から水を流し、圧力損失を求める練習用。",
                                   "Flow inside a bent pipe (20 mm bore). Push water in at the inlet and find the pressure drop.",
                                   "内径 20 mm 弯管内的流动。从入口通入水，求压力损失。")},
    "l_bracket": {"file": "l_bracket.step", "physics": "structural",
                  "title": ("L字ブラケット", "L-bracket", "L 形支架"),
                  "description": ("ボルト穴つきの L 字金具。底面を固定し、立ち上がりに荷重をかける練習用。",
                                  "An L-shaped bracket with a bolt hole. Fix the base and load the upright flange.",
                                  "带螺栓孔的 L 形支架。固定底面，在立板上加载。")},
    "heatsink": {"file": "heatsink.step", "physics": "thermal",
                 "title": ("ヒートシンク", "Heat sink", "散热器"),
                 "description": ("フィンつき放熱器。底面から熱を入れ、フィンから空気へ逃がす練習用。",
                                 "A finned heat sink. Put heat into the base and let the fins shed it to the air.",
                                 "带翅片的散热器。从底面输入热量，经翅片散到空气中。")},
}


def _samples_dir():
    from .config import RESOURCES
    return RESOURCES / "samples"


def list_samples(lang: str = "ja") -> dict:
    i = ("ja", "en", "zh").index(lang_of(lang))
    return {"samples": [{"id": k, "physics": v["physics"], "title": v["title"][i], "description": v["description"][i],
                         "file": v["file"]} for k, v in SAMPLES.items() if (_samples_dir() / v["file"]).is_file()]}


def open_sample(name: str, physics: str | None = None, lang: str = "ja") -> dict:
    if name not in SAMPLES:
        raise StudioError("err.cad_missing", 404, path=name)
    s = SAMPLES[name]
    return import_geometry(physics or s["physics"], s["file"], path=str(_samples_dir() / s["file"]), lang=lang)


def list_cases() -> dict:
    return {"cases": store.list_all()}


def describe_case(case_id: str, detail: str = "concise", lang: str = "ja") -> dict:
    pl = case_payload(case_id, lang)
    c = pl["case"]
    out = {"case_id": case_id, "revision": c["revision"], "template": c["template"], "title": c["title"][lang_of(lang)],
           "engine_for_mode": pl["engine"], "mode": c["run"]["mode"], "steps": pl["steps"], "ready": pl["ready"],
           "checks": [{k: i[k] for k in ("level", "code", "message", "fix")} for i in pl["checks"]],
           "parameters": {p["path"]: f"{p['value']} {p['unit']}" for p in pl["ui"]["params"]},
           "boundaries": {f["key"]: f["role"] for f in pl["ui"]["faces"]},
           "latest_run": pl["latest_run"]}
    out['history'] = dict(pl['history'], undo=pl['history']['undo'][:5])
    out['faces'] = [face_descriptor(c, f, lang) for f in c['geometry'].get('faces', []) if not f.get('interface')]
    out['face_groups'] = c.get('face_groups', {})
    out['interfaces'] = pl['ui']['interfaces']
    if tp := c.get('physics',{}):
        out['analysis'] = tp.get('analysis','static')
        out['nonlinear'] = tp.get('nonlinear',{})
    if c.get("body_materials"):
        geo = {b["key"]: b for b in c["geometry"].get("bodies", [])}
        out["body_materials"] = {b: {"material": m, "overrides": c.get("body_props", {}).get(b, {}),
                                     "volume_mm3": round(geo.get(b, {}).get("volume", 0) * 1e9, 3),
                                     "centroid_mm": [round(x * 1e3, 3) for x in geo.get(b, {}).get("centroid", [])]}
                                 for b, m in c["body_materials"].items()}
    if pl["ui"]["physics"] == "electric":
        out["boundary_values"] = {f: {k: v for k, v in b.items() if k != "role"} for f, b in c["boundaries"].items()}
        out["joule_heating"] = c["physics"].get("joule_heating", False)
    if detail == "full":
        out["case"] = c
        out["editable"] = store.editable_paths(c)
        out["allowed_roles"] = [r["id"] for r in pl["ui"]["roles"]]
    return out


def update_case(case_id: str, expected_revision: int, changes: dict, lang: str = "ja", source: str = 'gui') -> dict:
    store.case_dir(case_id)                    # validates the id before a lock file is made from it
    with store.case_lock(case_id):
        case = store.load(case_id)
        if int(expected_revision) != case["revision"]:
            raise StudioError("err.revision", 409, current=case["revision"])
        new, diff = store.apply_changes(case, changes)
        diff = [d for d in diff if geometry._canon(d["old"]) != geometry._canon(d["new"])]
        if diff:                               # a no-op edit (e.g. 200 -> 200.0 from autosave) keeps the revision
            store.save(new)
            store.record_change(case, new, [d['path'] for d in diff], source)
    pl = case_payload(case_id, lang)
    pl["diff"] = diff
    return pl


def undo_case(case_id: str, expected_revision: int, redo: bool = False, source: str = 'gui', lang: str = 'ja') -> dict:
    with store.case_lock(case_id):
        current = store.load(case_id)
        if int(expected_revision) != current['revision']:
            raise StudioError('err.revision', 409, current=current['revision'])
        h = store.history(case_id)
        src, dst = ('redo', 'undo') if redo else ('undo', 'redo')
        if not h[src]:
            raise StudioError('err.nothing_to_' + src, 409)
        entry = h[src].pop()
        new = copy.deepcopy(entry['before'])
        for k in ('revision', 'provenance', 'checks'):
            if k in current:
                new[k] = copy.deepcopy(current[k])
        store.save(new)
        h[dst].append(dict(entry, before=current))
        h[dst] = h[dst][-100:]
        store._write_json(store.case_dir(case_id) / 'history.json', h)
    pl = case_payload(case_id, lang)
    pl['diff'] = []
    # the toast already says who made the change ("AIの変更を元に戻しました"), so no "(AI)" mark here
    pl['undone'] = {'source': entry['source'], 'paths': entry['paths'], 'summary': history_summary(entry, lang, mark_ai=False)}
    return pl


def put_gui_state(state: dict) -> dict:
    cid = state.get('case_id')
    if cid is not None:
        case = store.load(cid)
        valid = set(templates.face_keys(case)) | {f['key'] for f in case['geometry'].get('faces',[]) if f.get('interface')}
    else:
        valid = set()
    if (state.get('step') not in ('geometry', 'mesh', 'physics', 'boundaries', 'run', 'results') or
            not isinstance(state.get('revision'), int) or any(
                not isinstance(state.get(k), list) or any(not isinstance(f, str) or f not in valid for f in state[k])
                for k in ('selected', 'hidden'))):
        raise StudioError('err.path', 400, path='gui-state')
    data = {k: state[k] for k in ('case_id', 'revision', 'step', 'selected', 'hidden')}
    data['ts'] = time.time()
    store._write_json(workspace() / '.gui_state.json', data)
    return {'ok': True}


def get_gui_selection(lang: str = 'ja') -> dict:
    path = workspace() / '.gui_state.json'
    if not path.is_file():
        return {'message': t('gui.none', lang), 'selected': []}
    state = json.loads(path.read_text(encoding='utf-8'))
    age = max(0., time.time() - state['ts'])
    if age > 1800:
        return {'message': t('gui.expired', lang), 'selected': [], 'age_s': age}
    if not state['case_id']:
        return {'message': t('gui.none', lang), 'selected': [], 'age_s': age}
    try:
        case = store.load(state['case_id'])
    except StudioError:
        return {'message': t('gui.none', lang), 'selected': []}
    info = {f['key']: f for f in case['geometry'].get('faces', [])}
    return {**state, 'age_s': age, 'current_revision': case['revision'],
            'message': t('gui.selected' if state['selected'] else 'gui.empty', lang, n=len(state['selected'])),
            'selected': [face_descriptor(case, info.get(k, {'key': k}), lang) for k in state['selected']
                         if k in info or k in templates.face_keys(case)]}


def validate_case(case_id: str, lang: str = "ja") -> dict:
    case = store.load(case_id)
    items = checks.run(case, lang)
    return {"case_id": case_id, "revision": case["revision"], "ready": not any(i["level"] == "error" for i in items),
            "status": "red" if any(i["level"] == "error" for i in items) else ("orange" if items else "green"),
            "items": items}


def generate_mesh(case_id: str, size: str | None = None, lang: str = "ja", source: str = 'gui') -> dict:
    case = store.load(case_id)
    if size and size != case["mesh"]["size"]:
        update_case(case_id, case["revision"], {"mesh.size": size}, lang, source=source)
        case = store.load(case_id)
    stats = geometry.generate_mesh(case)
    return {"ok": True, "case_id": case_id, "revision": case["revision"], "stats": stats}


def geometry_payload(case_id: str, lang: str = "ja") -> dict:
    case = store.load(case_id)
    tp = templates.get(case["template"])
    disp = geometry.display(case)
    faces = []
    for f in disp["faces"]:
        b = case["boundaries"].get(f["key"], {})
        desc = next((v for v in case['geometry'].get('faces',[]) if v['key'] == f['key']),{})
        from .contact import settings
        faces.append({"id": f["id"], "key": f["key"], "region": f["key"], "label": face_label(tp, f["key"], lang, case),
                      'interface':bool(desc.get('interface')), 'bodies':desc.get('bodies',[]),
                      'contact':settings(case,f['key']) if desc.get('interface') else None,
                      "role": b.get("role"), "positions": f["positions"], "indices": f["indices"]})
    return {"faces": faces, "bbox": disp.get("bbox") or [[0, 0, 0], disp["dims"]]}


# ------------------------------------------------------------------ solving

def run_simulation(case_id: str, mode: str | None = None, wait_s: float = 20.0, lang: str = "ja", source: str = 'gui') -> dict:
    case = store.load(case_id)
    if mode and mode != case["run"]["mode"]:
        update_case(case_id, case["revision"], {"run.mode": mode}, lang, source=source)
        case = store.load(case_id)
    items = checks.run(case, lang)
    if any(i["level"] == "error" for i in items):
        raise StudioError("err.blocked", 400, items=[i["message"] for i in items if i["level"] == "error"])
    engine = checks.engine_for(case)
    j = jobs.start(case, case["run"]["mode"], engine)
    j = jobs.wait(j["job_id"], wait_s)
    view = job_view(j, lang)
    if j["state"] == "done":
        return {"done": True, "job": view, "results": results.payload(case, lang, j["job_id"])}
    if j["state"] == "failed":
        return {"done": True, "job": view, "results": None}
    return {"done": False, "job_id": j["job_id"], "job": view, "poll_after_s": 5}


def check_convergence(case_id: str, wait_s: float = 20.0, lang: str = "ja") -> dict:
    """Solve on coarse, normal and fine meshes and estimate the discretisation error (GCI). Runs as one job."""
    case = store.load(case_id)
    items = checks.run(case, lang)
    if any(i["level"] == "error" for i in items):
        raise StudioError("err.blocked", 400, items=[i["message"] for i in items if i["level"] == "error"])
    if case["mesh"]["method"] == "structured":
        pass                                      # grid levels come from mesh.size as well
    j = jobs.start(case, case["run"]["mode"], checks.engine_for(case), study="convergence")
    j = jobs.wait(j["job_id"], wait_s)
    view = job_view(j, lang)
    if j["state"] == "done":
        return {"done": True, "job": view, "results": results.payload(case, lang, j["job_id"])}
    if j["state"] == "failed":
        return {"done": True, "job": view, "results": None}
    return {"done": False, "job_id": j["job_id"], "job": view, "poll_after_s": 15}


def job_status(job_id: str, lang: str = "ja") -> dict:
    j = jobs.status(job_id)
    v = job_view(j, lang)
    if j["state"] == "done":
        case = store.load(j["case_id"])
        v["gates"] = results.payload(case, lang, job_id)["gates"]
    if j["state"] == "failed":
        from .jobs import _job_dir
        err = _job_dir(job_id) / "error.txt"
        if err.is_file():
            v["first_error"] = err.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1]
    return v


def stop_job(job_id: str, lang: str = "ja") -> dict:
    return job_view(jobs.stop(job_id), lang)


def get_results(case_id: str, run_id: str | None = None, lang: str = "ja") -> dict:
    return results.payload(store.load(case_id), lang_of(lang), run_id)


def verify_case(case_id: str, lang: str = "ja") -> dict:
    case = store.load(case_id)
    jd, raw = results.load(case_id)
    pl = results.payload(case, lang_of(lang))
    return {"case_id": case_id, "run_id": jd.name, "gates": pl["gates"], "gates_detail": pl["gates_detail"],
            "verification": pl["verification"], "reference_points": (raw.get("reference") or {}).get("points"),
            "stale": pl["stale"]}


def field(case_id: str, quantity: str, lang: str = "ja", mode: int = 1, section: dict | None = None, step: int | None = None) -> dict:
    return results.field(store.load(case_id), quantity, lang_of(lang), mode=mode, section=section,step=step)


def render_view(case_id: str, quantity: str = "", lang: str = "ja", view: str = 'iso',
                highlight: list[str] | None = None, mode: int = 1,step: int | None = None) -> tuple[bytes, dict]:
    if quantity == 'faces':
        return results.render_faces(store.load(case_id), lang_of(lang), view, highlight)
    return results.render_png(store.load(case_id), quantity, lang_of(lang), mode=mode,step=step)


def export_results(case_id: str, format: str, lang: str = 'ja') -> dict:
    from .exports import export
    path = export(store.load(case_id), format, lang_of(lang))
    return {'path': str(path), 'format': format, 'filename': path.name}


def probe_results(case_id: str, points: list | None = None, line: dict | None = None, faces: list[str] | None = None,
                  run_id: str | None = None, lang: str = "ja", mode: int = 1,step: int | None = None) -> dict:
    from .probe import probe
    return probe(store.load(case_id), points, line, faces, run_id, mode,step)


def clone_case(case_id: str, changes: dict | None = None, title: str | None = None, lang: str = "ja", source: str = 'gui') -> dict:
    """Copy a case (geometry, face roles, materials, mesh settings; not its runs) under a new id, then apply changes."""
    import shutil
    import time as _time
    src = store.case_dir(case_id)
    case = store.load(case_id)
    cid = store.new_id()
    while (store.cases_dir() / cid).exists():
        cid = store.new_id()
    dst = store.cases_dir() / cid
    shutil.copytree(src, dst, ignore=lambda d, names: [n for n in names if d == str(src) and n in ("run", "revisions", "history.json", ".lock")])
    (dst / "revisions").mkdir(exist_ok=True)
    case["case_id"], case["revision"] = cid, 1
    if title:
        case["title"] = {l: title for l in ("ja", "en", "zh")}
    prov = case.setdefault("provenance", {})
    prov.update({"created_at": _time.strftime("%Y-%m-%dT%H:%M:%S"), "cloned_from": case_id})
    store._write_json(dst / "case.json", case)
    if changes:
        try:
            update_case(cid, 1, changes, lang, source=source)
        except StudioError:
            shutil.rmtree(dst, ignore_errors=True)
            raise
    return case_payload(cid, lang)


MAX_SWEEP = 8


def run_sweep(case_id: str, path: str, values: list, mode: str | None = None, study: str = "single",
              lang: str = "ja", source: str = 'gui') -> dict:
    """One clone per value of `path`, each started as a background job. Compare them with compare_runs."""
    if not 1 <= len(values) <= MAX_SWEEP:
        raise StudioError("err.path", 400, path=f"values: 1..{MAX_SWEEP} items")
    if study not in ("single", "convergence"):
        raise StudioError("err.path", 400, path=f"study={study} (single|convergence)")
    base = store.load(case_id)
    stem = base["title"][lang_of(lang)]
    made = []
    for v in values:
        ch = {path: v}
        if mode:
            ch["run.mode"] = mode
        label = v if isinstance(v, str) else (f"{v.get('value')} {v.get('unit')}" if isinstance(v, dict) else str(v))
        pl = clone_case(case_id, ch, f"{stem} [{path.rsplit('.', 1)[-1]}={label}]", lang, source=source)
        cid = pl["case"]["case_id"]
        case = store.load(cid)
        items = checks.run(case, lang)
        if any(i["level"] == "error" for i in items):
            made.append({"case_id": cid, "value": v, "job_id": None,
                         "blocked": [i["message"] for i in items if i["level"] == "error"]})
            continue
        j = jobs.start(case, case["run"]["mode"], checks.engine_for(case),
                       **({"study": "convergence"} if study == "convergence" else {}))
        made.append({"case_id": cid, "value": v, "job_id": j["job_id"]})
    return {"base": case_id, "path": path, "study": study, "cases": made,
            "poll_after_s": 15 if study == "convergence" else 5}


def compare_runs(case_ids: list[str], lang: str = "ja") -> dict:
    rows = []
    for cid in case_ids:
        case = store.load(cid)
        row = {"case_id": cid, "title": case["title"][lang_of(lang)], "revision": case["revision"],
               "parameters": {p: f"{v.get('value')} {v.get('unit')}" for p, v in _flat_params(case).items()}}
        try:
            pl = results.payload(case, lang_of(lang))
            row["gates"] = pl["gates"]
            row["cards"] = {c["key"]: f"{c['value']} {c['unit']}" for c in pl["cards"]}
        except StudioError:
            row["gates"] = None
        rows.append(row)
    return {"rows": rows}


def _flat_params(case):
    tp = templates.get(case["template"])
    out = {}
    for path, *_ in tp["params"]:
        node = case
        for p in path.split("."):
            node = node.get(p, {}) if isinstance(node, dict) else {}
        out[path] = node
    return out


def delete_case(case_id: str, confirm: str, lang: str = "ja") -> dict:
    if confirm != case_id:
        raise StudioError("err.confirm", 400, case_id=case_id)
    for j in jobs.list_for_case(case_id):
        if j["state"] in ("queued", "running"):
            jobs.stop(j["job_id"])
    return {"deleted": case_id, "bytes_freed": store.delete(case_id)}


def error_payload(e: StudioError, lang: str) -> dict:
    kw = {k: v for k, v in e.kw.items() if k != "items"}
    msg = t(e.key, lang, **kw)
    out = {"error": e.key, "message": msg}
    out.update(e.kw)
    if "current" in e.kw:
        out["current_revision"] = e.kw["current"]
    return out
