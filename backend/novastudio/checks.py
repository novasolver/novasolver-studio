"""Readiness checks. Layer 1 (error) = cannot solve. Layer 2 (warn) = solvable but the answer may mislead.
Every item names the step to fix and, where useful, the faces involved and the MCP call that fixes it."""
from __future__ import annotations

from . import geometry, templates, units
from .config import engines
from .i18n import t


def run(case: dict, lang: str) -> list[dict]:
    tp = templates.get(case["template"])
    items: list[dict] = []

    def add(level, code, step, faces=None, fix=None, **kw):
        items.append({"level": level, "code": code, "step": step, "message": t(f"check.{code}", lang, **kw),
                      "faces": faces or [], "fix": fix})

    b = case["boundaries"]
    if tp["physics"] == "conjugate":
        roles_ = [v.get("role") for v in b.values()]
        kinds = [i["role"] for i in case.get("bodies", {}).values()]
        if "fluid" not in kinds or "solid" not in kinds:
            add("error", "need_fluid_and_solid", "physics")
        if "water-inlet" not in roles_:
            add("error", "no_inlet", "boundaries")
        if "water-outlet" not in roles_:
            add("error", "no_outlet", "boundaries")
        if not any(r in ("heat-flux", "temperature") for r in roles_):
            add("warn", "no_heat", "boundaries")
    elif tp["physics"] == "thermal":
        if not any(v["role"] in ("temperature", "convection") for v in b.values()):
            add("error", "no_temperature", "boundaries")
        if not any(v["role"] in ("temperature", "convection", "heat-flux") for v in b.values()) or \
                (sum(v["role"] == "temperature" for v in b.values()) < 2 and not any(v["role"] in ("heat-flux", "convection") for v in b.values())):
            add("warn", "no_heat", "boundaries")
        if case["mesh"]["size"] == "coarse":
            add("warn", "coarse", "mesh", fix='update_case(changes={"mesh.size": "normal"})')
        ms = geometry.mesh_state(case)
        if ms["exists"] and ms["stale"]:
            add("warn", "mesh_stale", "mesh", fix="generate_mesh(case_id)")
    elif tp["physics"] == "structural":
        if not any(v["role"] == "fixed" for v in b.values()):
            add("error", "no_fixed", "boundaries", fix='update_case(changes={"boundaries.x0.role": "fixed"})')
        if not any(v["role"] in ("load", "pressure") for v in b.values()):
            add("error", "no_load", "boundaries", fix='update_case(changes={"boundaries.x1.role": "load"})')
        if case["template"] == "cantilever":
            p = case["geometry"]["params"]
            L, h = units.to_si(p["length"]), units.to_si(p["height"])
            if h > 0 and L / h < 10:
                add("warn", "slender", "geometry", ratio=L / h)
        if case["mesh"]["size"] == "coarse":
            add("warn", "coarse", "mesh", fix='update_case(changes={"mesh.size": "normal"})')
        ms = geometry.mesh_state(case)
        if ms["exists"] and ms["stale"]:
            add("warn", "mesh_stale", "mesh", fix="generate_mesh(case_id)")
    else:
        nu = units.to_si(case["materials"]["fluid"]["nu"])
        if case["template"] == "cavity":
            L = units.to_si(case["geometry"]["params"]["size"])
            U = units.to_si(b["y1"]["speed"]) if b["y1"]["role"] == "moving-wall" else 0.0
            re = U * L / nu if nu > 0 else 0
            if U <= 0:
                add("error", "no_load", "boundaries", faces=["y1"],
                    fix='update_case(changes={"boundaries.y1.role": "moving-wall"})')
            elif re > 1000:
                add("warn", "re_turbulent", "physics", re=re)
            elif abs(re - 100) / 100 > 0.01:
                add("warn", "re_range", "physics", re=re)
        if case["template"] == "channel":
            g = units.to_si(case["geometry"]["params"]["gap"])
            Lx = units.to_si(case["geometry"]["params"]["length"])
            U = units.to_si(b["x0"]["speed"]) if b["x0"]["role"] == "inlet" else 0.0
            re = U * g / nu if nu > 0 else 0
            if re > 2000:
                add("error", "re_turbulent", "physics", re=re)
            le = 0.05 * re * g
            if le > 0.5 * Lx:
                add("warn", "entrance", "geometry", le=le)
        if not case.get("flow") and not any(v["role"] in ("inlet", "moving-wall") for v in b.values()):
            add("error", "no_inlet", "boundaries")
        if case.get("flow"):                       # external flow: Reynolds number from the body size
            (x0, y0, z0), (x1, y1, z1) = case["geometry"]["bbox"]
            L = max(x1 - x0, y1 - y0, z1 - z0)
            re = units.to_si(case["flow"]["speed"]) * L / nu if nu > 0 else 0
            if re > 300:
                add("warn", "turbulent_model", "physics", re=re)
        if case["template"] == "import-flow":
            if not any(v["role"] == "outlet" for v in b.values()):
                add("error", "no_outlet", "boundaries")
            from .flow3d import inlet_reynolds
            re = inlet_reynolds(case)
            if re and re > 2300:
                add("warn", "turbulent_model", "physics", re=re)

    eng = engines()
    preview_engine = next((e for e in tp["engines"] if e.startswith("builtin")), None)
    final_engine = next((e for e in tp["engines"] if not e.startswith("builtin")), None)
    if case["run"]["mode"] == "preview" and preview_engine is None:
        add("error", "no_builtin", "run", fix='update_case(changes={"run.mode": "final"})')
    if case["run"]["mode"] == "final" and final_engine and not eng[final_engine]["available"]:
        add("error", "engine_missing", "run", engine={"calculix": "CalculiX", "openfoam": "OpenFOAM"}[final_engine],
            fix='update_case(changes={"run.mode": "preview"})' if preview_engine else None)
    return items


def engine_for(case: dict) -> str:
    tp = templates.get(case["template"])
    if case["run"]["mode"] == "preview":
        return next((e for e in tp["engines"] if e.startswith("builtin")), tp["engines"][0])
    return next((e for e in tp["engines"] if not e.startswith("builtin")), tp["engines"][0])


def steps(case: dict, items: list[dict], latest: dict | None) -> dict:
    by_step = {}
    for it in items:
        lvl = by_step.get(it["step"])
        by_step[it["step"]] = "error" if it["level"] == "error" or lvl == "error" else "warn"
    ms = geometry.mesh_state(case)
    out = {
        "geometry": "warn" if "geometry" in by_step else "ok",
        "mesh": ("warn" if "mesh" in by_step else "ok") if ms["exists"] else "todo",
        "physics": "warn" if "physics" in by_step else "ok",
        "boundaries": "warn" if "boundaries" in by_step else "ok",
        "run": "todo", "results": "todo",
    }
    if latest and latest.get("state") == "done" and latest.get("revision") == case["revision"]:
        out["run"] = "ok"
        out["results"] = "ok" if latest.get("gates", {}).get("converged") and not latest.get("warnings") else "warn"
    elif latest and latest.get("state") == "done":
        out["run"] = "warn"            # results exist but belong to an older revision
        out["results"] = "warn"
    elif "run" in by_step:
        out["run"] = "warn"
    return out
