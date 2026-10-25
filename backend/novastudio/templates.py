"""Template definitions. A template = default case.json + what the UI may edit + its reference solution.

Faces are named by position on the bounding box (x0 = face at x min, ... z1 = face at z max).
In v0 every region is exactly one face, and the region id equals the face key.
"""
from __future__ import annotations

import copy

from . import SCHEMA_VERSION
from .i18n import all3

MATERIALS_SOLID = {
    # sy = typical yield strength (SS400 / 6061-T6 / Ti-6Al-4V); used only to warn when linear elasticity stops holding
    "steel": {"E": {"value": 205, "unit": "GPa"}, "nu": {"value": 0.30, "unit": "-"}, "rho": {"value": 7850, "unit": "kg/m3"},
              "sy": {"value": 235, "unit": "MPa"}, "k": {"value": 50, "unit": "W/mK"}},
    "aluminium": {"E": {"value": 69, "unit": "GPa"}, "nu": {"value": 0.33, "unit": "-"}, "rho": {"value": 2700, "unit": "kg/m3"},
                  "sy": {"value": 275, "unit": "MPa"}, "k": {"value": 167, "unit": "W/mK"}},
    "titanium": {"E": {"value": 114, "unit": "GPa"}, "nu": {"value": 0.34, "unit": "-"}, "rho": {"value": 4430, "unit": "kg/m3"},
                 "sy": {"value": 880, "unit": "MPa"}, "k": {"value": 6.7, "unit": "W/mK"}},
    "copper": {"E": {"value": 117, "unit": "GPa"}, "nu": {"value": 0.34, "unit": "-"}, "rho": {"value": 8960, "unit": "kg/m3"},
               "sy": {"value": 70, "unit": "MPa"}, "k": {"value": 390, "unit": "W/mK"}},
}
MATERIALS_FLUID = {
    "water": {"nu": {"value": 1.0e-6, "unit": "m2/s"}, "rho": {"value": 998, "unit": "kg/m3"}},
    "air": {"nu": {"value": 1.5e-5, "unit": "m2/s"}, "rho": {"value": 1.2, "unit": "kg/m3"}},
}

STRUCT_ROLES = ["free", "fixed", "load", "pressure"]
FLOW_ROLES = ["wall", "moving-wall", "inlet", "outlet", "plane2d"]
THERMAL_ROLES = ["insulated", "temperature", "heat-flux", "convection"]
DIRECTIONS = ["-z", "+z", "-y", "+y", "-x", "+x", "normal"]   # load direction; "normal" = pushes into the face

# value fields each role carries (path suffix -> default quantity)
ROLE_FIELDS = {
    "load": {"force": {"value": 100, "unit": "N"}, "direction": "-z"},
    "pressure": {"pressure": {"value": 1, "unit": "MPa"}},
    "moving-wall": {"speed": {"value": 1, "unit": "m/s"}},
    "inlet": {"speed": {"value": 1, "unit": "m/s"}},
    "temperature": {"temperature": {"value": 20, "unit": "degC"}},
    "heat-flux": {"flux": {"value": 1000, "unit": "W/m2"}},
    "convection": {"h": {"value": 10, "unit": "W/m2K"}, "tinf": {"value": 20, "unit": "degC"}},
    "water-inlet": {"speed": {"value": 0.2, "unit": "m/s"}, "temperature": {"value": 20, "unit": "degC"}},
}
CONJUGATE_FLUID_ROLES = ["water-wall", "water-inlet", "water-outlet"]
CONJUGATE_SOLID_ROLES = ["insulated", "temperature", "heat-flux", "convection"]
FLUID_PROPS = {   # rho, cp, mu, Pr (for multi-region thermal flow)
    "water": {"rho": 998.0, "cp": 4181.0, "mu": 1.0e-3, "Pr": 7.0},
    "air": {"rho": 1.2, "cp": 1005.0, "mu": 1.8e-5, "Pr": 0.71},
}
SOLID_PROPS = {   # rho, cp (k comes from MATERIALS_SOLID)
    "steel": {"rho": 7850.0, "cp": 460.0}, "aluminium": {"rho": 2700.0, "cp": 900.0}, "titanium": {"rho": 4430.0, "cp": 520.0},
    "copper": {"rho": 8960.0, "cp": 385.0},
}
VALUE_FIELDS = sorted({k for v in ROLE_FIELDS.values() for k in v})

FACE_KEYS = ["x0", "x1", "y0", "y1", "z0", "z1"]

TEMPLATES: dict[str, dict] = {
    "cantilever": {
        "physics": "structural",
        "analysis": "linear-static",
        "engines": ["builtin-fem", "calculix"],
        "default_engine": "builtin-fem",
        "roles": STRUCT_ROLES,
        "face_labels": {k: f"face.{k}" for k in FACE_KEYS},
        "locked_faces": [],
        "case": {
            "geometry": {"kind": "box", "params": {
                "length": {"value": 200, "unit": "mm"},
                "width": {"value": 20, "unit": "mm"},
                "height": {"value": 20, "unit": "mm"}}},
            "physics": {"kind": "linear-static"},
            "materials": {"solid": {"preset": "steel", **copy.deepcopy(MATERIALS_SOLID["steel"])}},
            "boundaries": {
                "x0": {"role": "fixed"},
                "x1": {"role": "load", "force": {"value": 1000, "unit": "N"}, "direction": "-z"},
                "y0": {"role": "free"}, "y1": {"role": "free"}, "z0": {"role": "free"}, "z1": {"role": "free"}},
            "mesh": {"method": "gmsh", "size": "normal", "order": 2},
            "reference": {"kind": "analytic", "id": "timoshenko-tip-deflection", "quantity": "tip_disp", "tolerance_pct": 3.0},
        },
        "params": [
            ("geometry.params.length", "param.length", "length", 10, 5000),
            ("geometry.params.width", "param.width", "length", 1, 1000),
            ("geometry.params.height", "param.height", "length", 1, 1000),
            ("boundaries.x1.force", "param.force", "force", 0, 1e7),
            ("materials.solid.E", "param.E", "pressure", 0.1, 1000),
            ("materials.solid.nu", "param.poisson", "dimensionless", 0, 0.49),
        ],
        "nova_tool": "https://novasolver.jp/tools/beam-deflection.html",
    },
    "cavity": {
        "physics": "cfd",
        "analysis": "incompressible-laminar",
        "engines": ["builtin-cavity", "openfoam"],
        "default_engine": "builtin-cavity",
        "roles": FLOW_ROLES,
        "face_labels": {"x0": "face.cavity.wall", "x1": "face.cavity.wall", "y0": "face.cavity.wall",
                        "y1": "face.cavity.lid", "z0": "face.plane", "z1": "face.plane"},
        "locked_faces": ["z0", "z1"],
        "case": {
            "geometry": {"kind": "box2d", "params": {"size": {"value": 0.1, "unit": "m"}}},
            "physics": {"kind": "incompressible-laminar"},
            "materials": {"fluid": {"preset": "custom", "nu": {"value": 1.0e-3, "unit": "m2/s"}}},
            "boundaries": {
                "y1": {"role": "moving-wall", "speed": {"value": 1.0, "unit": "m/s"}},
                "x0": {"role": "wall"}, "x1": {"role": "wall"}, "y0": {"role": "wall"},
                "z0": {"role": "plane2d"}, "z1": {"role": "plane2d"}},
            "mesh": {"method": "structured", "size": "normal"},
            "reference": {"kind": "literature", "id": "ghia1982-re100-u", "quantity": "u_centerline", "tolerance_pct": 3.0},
        },
        "params": [
            ("geometry.params.size", "param.size", "length", 0.001, 10),
            ("boundaries.y1.speed", "param.lid_speed", "velocity", 0, 100),
            ("materials.fluid.nu", "param.nu", "kinematic_viscosity", 1e-8, 1),
        ],
        "nova_tool": "https://novasolver.jp/tools/navier-stokes-2d.html",
    },
    "channel": {
        "physics": "cfd",
        "analysis": "incompressible-laminar",
        "engines": ["openfoam"],
        "default_engine": "openfoam",
        "roles": FLOW_ROLES,
        "face_labels": {"x0": "face.channel.inlet", "x1": "face.channel.outlet", "y0": "face.channel.wall",
                        "y1": "face.channel.wall", "z0": "face.plane", "z1": "face.plane"},
        "locked_faces": ["z0", "z1"],
        "case": {
            "geometry": {"kind": "channel2d", "params": {
                "length": {"value": 1.0, "unit": "m"}, "gap": {"value": 20, "unit": "mm"}}},
            "physics": {"kind": "incompressible-laminar"},
            "materials": {"fluid": {"preset": "water", **copy.deepcopy(MATERIALS_FLUID["water"])}},
            "boundaries": {
                "x0": {"role": "inlet", "speed": {"value": 0.01, "unit": "m/s"}},
                "x1": {"role": "outlet"}, "y0": {"role": "wall"}, "y1": {"role": "wall"},
                "z0": {"role": "plane2d"}, "z1": {"role": "plane2d"}},
            "mesh": {"method": "structured", "size": "normal"},
            "reference": {"kind": "analytic", "id": "poiseuille-umax", "quantity": "umax_outlet", "tolerance_pct": 2.0},
        },
        "params": [
            ("geometry.params.length", "param.length", "length", 0.01, 100),
            ("geometry.params.gap", "param.gap", "length", 0.0001, 1),
            ("boundaries.x0.speed", "param.inlet_speed", "velocity", 0, 10),
            ("materials.fluid.nu", "param.nu", "kinematic_viscosity", 1e-8, 1),
        ],
        "nova_tool": "https://novasolver.jp/tools/hagen-poiseuille.html",
    },
    "thermal-block": {
        "physics": "thermal",
        "analysis": "steady-thermal",
        "engines": ["builtin-fem", "calculix"],
        "default_engine": "builtin-fem",
        "roles": THERMAL_ROLES,
        "face_labels": {k: f"face.{k}" for k in FACE_KEYS},
        "locked_faces": [],
        "case": {
            "geometry": {"kind": "box", "params": {
                "length": {"value": 100, "unit": "mm"},
                "width": {"value": 50, "unit": "mm"},
                "height": {"value": 20, "unit": "mm"}}},
            "physics": {"kind": "steady-thermal"},
            "materials": {"solid": {"preset": "steel", **copy.deepcopy(MATERIALS_SOLID["steel"])}},
            "boundaries": {
                "x0": {"role": "temperature", "temperature": {"value": 100, "unit": "degC"}},
                "x1": {"role": "temperature", "temperature": {"value": 20, "unit": "degC"}},
                "y0": {"role": "insulated"}, "y1": {"role": "insulated"}, "z0": {"role": "insulated"}, "z1": {"role": "insulated"}},
            "mesh": {"method": "gmsh", "size": "normal", "order": 2},
            "reference": {"kind": "analytic", "id": "fourier-1d-slab", "quantity": "heat_flow", "tolerance_pct": 2.0},
        },
        "params": [
            ("geometry.params.length", "param.length", "length", 1, 5000),
            ("geometry.params.width", "param.width", "length", 1, 5000),
            ("geometry.params.height", "param.height", "length", 1, 5000),
            ("boundaries.x0.temperature", "param.t_hot", "temperature", -273.15, 3000),
            ("boundaries.x1.temperature", "param.t_cold", "temperature", -273.15, 3000),
            ("materials.solid.k", "param.k", "conductivity", 0.01, 5000),
        ],
        "nova_tool": "https://novasolver.jp/tools/heat-conduction-1d.html",
    },
    # standard problem: stress concentration at a hole in a plate under tension (Heywood, finite width)
    "plate-hole": {
        "physics": "structural", "analysis": "linear-static",
        "engines": ["builtin-fem", "calculix"], "default_engine": "builtin-fem",
        "roles": STRUCT_ROLES, "faces": FACE_KEYS + ["hole"],
        "face_labels": {**{k: f"face.{k}" for k in FACE_KEYS}, "hole": "face.hole"}, "locked_faces": [],
        "case": {
            "geometry": {"kind": "plate_hole", "params": {
                "length": {"value": 150, "unit": "mm"}, "width": {"value": 50, "unit": "mm"},
                "thickness": {"value": 5, "unit": "mm"}, "hole": {"value": 10, "unit": "mm"}}},
            "physics": {"kind": "linear-static"},
            "materials": {"solid": {"preset": "steel", **copy.deepcopy(MATERIALS_SOLID["steel"])}},
            "boundaries": {"x0": {"role": "fixed"}, "x1": {"role": "load", "force": {"value": 5, "unit": "kN"}, "direction": "+x"},
                           "y0": {"role": "free"}, "y1": {"role": "free"}, "z0": {"role": "free"}, "z1": {"role": "free"},
                           "hole": {"role": "free"}},
            "mesh": {"method": "gmsh", "size": "normal", "order": 2},
            "reference": {"kind": "analytic", "id": "heywood-kt", "quantity": "kt", "tolerance_pct": 5.0},
        },
        "params": [
            ("geometry.params.length", "param.length", "length", 20, 5000),
            ("geometry.params.width", "param.width", "length", 5, 2000),
            ("geometry.params.thickness", "param.thickness", "length", 0.5, 500),
            ("geometry.params.hole", "param.hole", "length", 0.5, 1000),
            ("boundaries.x1.force", "param.tension", "force", 0, 1e8),
        ],
        "nova_tool": "https://novasolver.jp/tools/stress-concentration.html",
    },
    # standard problem: straight fin with a convective tip (analytic 1D fin solution)
    "fin": {
        "physics": "thermal", "analysis": "steady-thermal",
        "engines": ["builtin-fem", "calculix"], "default_engine": "builtin-fem",
        "roles": THERMAL_ROLES, "face_labels": {k: f"face.{k}" for k in FACE_KEYS}, "locked_faces": [],
        "case": {
            "geometry": {"kind": "box", "params": {
                "length": {"value": 100, "unit": "mm"}, "width": {"value": 10, "unit": "mm"},
                "height": {"value": 10, "unit": "mm"}}},
            "physics": {"kind": "steady-thermal"},
            "materials": {"solid": {"preset": "steel", **copy.deepcopy(MATERIALS_SOLID["steel"])}},
            "boundaries": {"x0": {"role": "temperature", "temperature": {"value": 100, "unit": "degC"}},
                           **{k: {"role": "convection", "h": {"value": 25, "unit": "W/m2K"}, "tinf": {"value": 20, "unit": "degC"}}
                              for k in ("x1", "y0", "y1", "z0", "z1")}},
            "mesh": {"method": "gmsh", "size": "normal", "order": 2},
            "reference": {"kind": "analytic", "id": "fin-convective-tip", "quantity": "heat_flow", "tolerance_pct": 2.0},
        },
        "params": [
            ("geometry.params.length", "param.length", "length", 1, 5000),
            ("geometry.params.width", "param.width", "length", 0.5, 1000),
            ("geometry.params.height", "param.height", "length", 0.5, 1000),
            ("boundaries.x0.temperature", "param.t_base", "temperature", -273.15, 3000),
            ("materials.solid.k", "param.k", "conductivity", 0.01, 5000),
        ],
        "nova_tool": "https://novasolver.jp/tools/fin-heat-transfer.html",
    },
    # Generic analyses on an imported CAD shape. Not shown as templates; created through import_geometry.
    "import-structural": {
        "physics": "structural", "analysis": "linear-static", "import": True,
        "engines": ["builtin-fem", "calculix"], "default_engine": "builtin-fem",
        "roles": STRUCT_ROLES, "face_labels": {}, "locked_faces": [],
        "case": {
            "geometry": {"kind": "import"},
            "physics": {"kind": "linear-static"},
            "materials": {"solid": {"preset": "steel", **copy.deepcopy(MATERIALS_SOLID["steel"])}},
            "boundaries": {},
            "mesh": {"method": "gmsh", "size": "normal", "order": 2},
            "reference": {"kind": "none"},
        },
        "params": [
            ("materials.solid.E", "param.E", "pressure", 0.1, 1000),
            ("materials.solid.nu", "param.poisson", "dimensionless", 0, 0.49),
        ],
    },
    "import-thermal": {
        "physics": "thermal", "analysis": "steady-thermal", "import": True,
        "engines": ["builtin-fem", "calculix"], "default_engine": "builtin-fem",
        "roles": THERMAL_ROLES, "face_labels": {}, "locked_faces": [],
        "case": {
            "geometry": {"kind": "import"},
            "physics": {"kind": "steady-thermal"},
            "materials": {"solid": {"preset": "steel", **copy.deepcopy(MATERIALS_SOLID["steel"])}},
            "boundaries": {},
            "mesh": {"method": "gmsh", "size": "normal", "order": 2},
            "reference": {"kind": "none"},
        },
        "params": [("materials.solid.k", "param.k", "conductivity", 0.01, 5000)],
    },
    "import-flow": {
        "physics": "cfd", "analysis": "incompressible-steady", "import": True,
        "engines": ["openfoam"], "default_engine": "openfoam",
        "roles": ["wall", "inlet", "outlet"], "face_labels": {}, "locked_faces": [],
        "case": {
            "geometry": {"kind": "import"},
            "physics": {"kind": "incompressible-steady"},
            "materials": {"fluid": {"preset": "water", **copy.deepcopy(MATERIALS_FLUID["water"])}},
            "boundaries": {},
            "mesh": {"method": "gmsh", "size": "normal", "order": 1},
            "run": {"mode": "final"},
            "reference": {"kind": "none"},
        },
        "params": [("materials.fluid.nu", "param.nu", "kinematic_viscosity", 1e-8, 1)],
    },
    "import-external": {
        "physics": "external", "analysis": "external-steady", "import": True,
        "engines": ["openfoam"], "default_engine": "openfoam",
        "roles": ["wall"], "face_labels": {}, "locked_faces": [],
        "case": {
            "geometry": {"kind": "import"},
            "physics": {"kind": "external-steady"},
            "materials": {"fluid": {"preset": "air", **copy.deepcopy(MATERIALS_FLUID["air"])}},
            "boundaries": {},
            "flow": {"speed": {"value": 1.0, "unit": "m/s"}, "direction": "+x"},
            "mesh": {"method": "gmsh", "size": "normal", "order": 1},
            "run": {"mode": "final"},
            "reference": {"kind": "none"},
        },
        "params": [("flow.speed", "param.free_speed", "velocity", 1e-6, 1000),
                   ("materials.fluid.nu", "param.nu", "kinematic_viscosity", 1e-8, 1)],
    },
    # standard benchmark: steady flow past a sphere, compared with the Schiller-Naumann drag correlation
    "sphere-drag": {
        "physics": "external", "analysis": "external-steady", "sample": "sphere.step", "base": "import-external",
        "engines": ["openfoam"], "default_engine": "openfoam",
        "roles": ["wall"], "face_labels": {}, "locked_faces": [],
        "case": {
            "geometry": {"kind": "import"},
            "physics": {"kind": "external-steady"},
            "materials": {"fluid": {"preset": "water", **copy.deepcopy(MATERIALS_FLUID["water"])}},
            "boundaries": {},
            "flow": {"speed": {"value": 0.01, "unit": "m/s"}, "direction": "+x"},
            "mesh": {"method": "gmsh", "size": "normal", "order": 1},
            "run": {"mode": "final"},
            "reference": {"kind": "correlation", "id": "schiller-naumann", "quantity": "cd", "tolerance_pct": 8.0},
        },
        "params": [("flow.speed", "param.free_speed", "velocity", 1e-6, 1000),
                   ("materials.fluid.nu", "param.nu", "kinematic_viscosity", 1e-8, 1)],
        "nova_tool": "https://novasolver.jp/tools/sphere-drag.html",
    },
    # conjugate heat transfer: water flowing through/around solids (assembly with two or more bodies)
    "import-conjugate": {
        "physics": "conjugate", "analysis": "conjugate-steady", "import": True,
        "engines": ["openfoam"], "default_engine": "openfoam",
        "roles": CONJUGATE_FLUID_ROLES + CONJUGATE_SOLID_ROLES, "face_labels": {}, "locked_faces": [],
        "case": {
            "geometry": {"kind": "import"},
            "physics": {"kind": "conjugate-steady"},
            "materials": {"solid": {"preset": "aluminium", **copy.deepcopy(MATERIALS_SOLID["aluminium"])},
                          "fluid": {"preset": "water", **copy.deepcopy(MATERIALS_FLUID["water"])}},
            "boundaries": {},
            "mesh": {"method": "gmsh", "size": "normal", "order": 1},
            "run": {"mode": "final"},
            "reference": {"kind": "none"},
        },
        "params": [],
    },
}

DEFAULT_ROLE = {"structural": "free", "thermal": "insulated", "cfd": "wall", "flow": "wall", "external": "wall",
                "conjugate": "insulated"}


def face_keys(case: dict) -> list[str]:
    g = case["geometry"]
    if g["kind"] == "import":
        return [f["key"] for f in g.get("faces", []) if not f.get("interface")]   # shared faces are internal
    return list(TEMPLATES.get(case["template"], {}).get("faces", FACE_KEYS))


def bounds_si(template_id: str) -> dict[str, tuple[float, float]]:
    """Allowed range per editable parameter, in SI. The template lists bounds in the parameter's default unit."""
    from . import units
    tp = TEMPLATES[template_id]
    out = {}
    for path, _label, _dim, lo, hi in tp["params"]:
        node = tp["case"]
        for p in path.split(".")[0:]:
            node = node.get(p, {}) if isinstance(node, dict) else {}
        u = node.get("unit", "-") if node else "-"
        out[path] = (units.to_si({"value": lo, "unit": u}), units.to_si({"value": hi, "unit": u}))
    return out


def get(template_id: str) -> dict:
    if template_id not in TEMPLATES:
        raise KeyError(template_id)
    return TEMPLATES[template_id]


def summary(lang: str) -> list[dict]:
    from .config import engines
    eng = engines()
    out = []
    for tid, tp in TEMPLATES.items():
        if tp.get("import"):
            continue
        out.append({
            "id": tid,
            "physics": tp["physics"],
            "title": all3(f"template.{tid}.title")[lang],
            "description": all3(f"template.{tid}.description")[lang],
            "has_reference": True,
            "engines": [{"id": e, "available": eng[e]["available"]} for e in tp["engines"]],
            "runnable_now": any(eng[e]["available"] for e in tp["engines"]),
        })
    return out


def new_case(template_id: str, case_id: str) -> dict:
    tp = get(template_id)
    c = copy.deepcopy(tp["case"])
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "revision": 1,
        "template": template_id,
        "title": all3(f"template.{template_id}.title"),
        "engine": {"kind": tp["default_engine"]},
        "geometry": c["geometry"],
        "physics": c["physics"],
        "materials": c["materials"],
        "boundaries": c["boundaries"],
        **({"flow": c["flow"]} if "flow" in c else {}),
        "mesh": c["mesh"],
        "run": {"mode": "preview", "max_wall_s": 900, **c.get("run", {})},
        "reference": c["reference"],
        "checks": {},
        "provenance": {},
    }
