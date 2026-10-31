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
    # quenched and tempered alloy steel (SCM440 / Cr-V tool steel class): tools, shafts, bolts
    "alloy_steel": {"E": {"value": 205, "unit": "GPa"}, "nu": {"value": 0.29, "unit": "-"}, "rho": {"value": 7850, "unit": "kg/m3"},
                    "sy": {"value": 785, "unit": "MPa"}, "k": {"value": 42, "unit": "W/mK"}},
    "copper": {"E": {"value": 117, "unit": "GPa"}, "nu": {"value": 0.34, "unit": "-"}, "rho": {"value": 8960, "unit": "kg/m3"},
               "sy": {"value": 70, "unit": "MPa"}, "k": {"value": 390, "unit": "W/mK"}},
    # 3D-printing plastics, solid (100 % infill) and loaded along the layers; across the layers they are weaker
    "pla": {"E": {"value": 3.5, "unit": "GPa"}, "nu": {"value": 0.36, "unit": "-"}, "rho": {"value": 1240, "unit": "kg/m3"},
            "sy": {"value": 50, "unit": "MPa"}, "k": {"value": 0.13, "unit": "W/mK"}},
    "petg": {"E": {"value": 2.1, "unit": "GPa"}, "nu": {"value": 0.38, "unit": "-"}, "rho": {"value": 1270, "unit": "kg/m3"},
             "sy": {"value": 50, "unit": "MPa"}, "k": {"value": 0.2, "unit": "W/mK"}},
    "abs": {"E": {"value": 2.2, "unit": "GPa"}, "nu": {"value": 0.35, "unit": "-"}, "rho": {"value": 1040, "unit": "kg/m3"},
            "sy": {"value": 40, "unit": "MPa"}, "k": {"value": 0.17, "unit": "W/mK"}},
    # parts of assemblies (several bodies, one material each): buildings and electronics. sy = tensile for concrete/glass
    "concrete": {"E": {"value": 30, "unit": "GPa"}, "nu": {"value": 0.2, "unit": "-"}, "rho": {"value": 2400, "unit": "kg/m3"},
                 "sy": {"value": 3, "unit": "MPa"}, "k": {"value": 1.6, "unit": "W/mK"}},
    "insulation": {"E": {"value": 0.005, "unit": "GPa"}, "nu": {"value": 0.1, "unit": "-"}, "rho": {"value": 25, "unit": "kg/m3"},
                   "sy": {"value": 0.1, "unit": "MPa"}, "k": {"value": 0.035, "unit": "W/mK"}},
    "wood": {"E": {"value": 11, "unit": "GPa"}, "nu": {"value": 0.3, "unit": "-"}, "rho": {"value": 500, "unit": "kg/m3"},
             "sy": {"value": 40, "unit": "MPa"}, "k": {"value": 0.13, "unit": "W/mK"}},
    "glass": {"E": {"value": 70, "unit": "GPa"}, "nu": {"value": 0.22, "unit": "-"}, "rho": {"value": 2500, "unit": "kg/m3"},
              "sy": {"value": 40, "unit": "MPa"}, "k": {"value": 1.0, "unit": "W/mK"}},
    "fr4": {"E": {"value": 22, "unit": "GPa"}, "nu": {"value": 0.15, "unit": "-"}, "rho": {"value": 1850, "unit": "kg/m3"},
            "sy": {"value": 300, "unit": "MPa"}, "k": {"value": 0.3, "unit": "W/mK"}},
    "silicon": {"E": {"value": 130, "unit": "GPa"}, "nu": {"value": 0.28, "unit": "-"}, "rho": {"value": 2330, "unit": "kg/m3"},
                "sy": {"value": 120, "unit": "MPa"}, "k": {"value": 148, "unit": "W/mK"}},
}
# Room-temperature, isotropic nominal values. Air/water elastic values are numerical placeholders for other templates.
for _name, _E, _nu, _rho, _k, _eps, _sigma in [
    ("air", 0.00014, 0.0, 1.2, 0.026, 1.0006, 1e-15),
    ("ptfe", 0.5, 0.46, 2200, 0.25, 2.1, 1e-16),
    ("alumina", 300, 0.22, 3950, 30, 9.8, 1e-14),
    ("epoxy", 3, 0.35, 1200, 0.2, 3.6, 1e-14),
    ("water_deionised", 0.0022, 0.0, 998, 0.6, 80, 5.5e-6),
]:
    MATERIALS_SOLID[_name] = {p: {"value": v, "unit": u} for p, v, u in
                             (("E", _E, "GPa"), ("nu", _nu, "-"), ("rho", _rho, "kg/m3"),
                              ("k", _k, "W/mK"), ("eps_r", _eps, "-"), ("sigma", _sigma, "S/m"))}
for _name, _mat in MATERIALS_SOLID.items():
    _mat['alpha'] = {'value': {'steel': 12e-6, 'aluminium': 23e-6, 'titanium': 8.6e-6, 'copper': 17e-6,
        'alloy_steel': 12e-6, 'pla': 68e-6, 'petg': 60e-6, 'abs': 90e-6, 'concrete': 10e-6,
        'glass': 9e-6, 'fr4': 14e-6, 'silicon': 2.6e-6, 'wood': 5e-6, 'insulation': 0,
        'ptfe': 100e-6, 'alumina': 8e-6, 'epoxy': 50e-6}.get(_name, 0), 'unit': '1/K'}
    _mat.setdefault("eps_r", {"value": {"pla": 3, "petg": 3.2, "abs": 2.8, "concrete": 5,
                                      "insulation": 1.05, "wood": 2, "glass": 5, "fr4": 4.4, "silicon": 11.7}.get(_name, 1), "unit": "-"})
    _mat.setdefault("sigma", {"value": {"copper": 5.96e7, "aluminium": 3.77e7, "steel": 6.99e6,
                                      "alloy_steel": 4e6, "titanium": 2.38e6, "silicon": 4.3e-4}.get(_name, 1e-12), "unit": "S/m"})
BODY_PROPS = {"k": "W/mK", "E": "GPa", "nu": "-", "eps_r": "-", "sigma": "S/m", "rho": "kg/m3", "alpha": "1/K", 'sy':'MPa', 'H':'Pa'}


def solid_props(case: dict, body: str | None = None) -> dict:
    """E, nu and k (SI) of one body: its preset (body_materials) with any overrides (body_props), else the case's
    single solid material."""
    from . import units
    mat = case["materials"]["solid"]
    mat = {**MATERIALS_SOLID.get(mat.get('preset'), MATERIALS_SOLID['steel']), **mat}
    if body is not None and body in case.get("body_materials", {}):
        mat = {**MATERIALS_SOLID[case["body_materials"][body]], **case.get("body_props", {}).get(body, {})}
    out = {p: units.to_si(mat[p]) for p in BODY_PROPS if p in mat}
    out['model'] = mat.get('model','linear')
    out.setdefault('H',out['E']/100)
    return out


def element_groups(case: dict, tet_body) -> list[tuple]:
    """[(element indices, props)]: one group per body of a multi-material assembly, else one group for all."""
    import numpy as np
    tet_body = np.asarray(tet_body)
    if not case.get("body_materials"):
        return [(np.arange(len(tet_body)), solid_props(case))]
    out = []
    for b in sorted(case["body_materials"]):
        idx = np.where(tet_body == int(b[1:]))[0]
        if len(idx):
            out.append((idx, solid_props(case, b)))
    if sum(len(i) for i, _ in out) != len(tet_body):
        raise ValueError("some elements belong to no body: regenerate the mesh")
    return out


def element_prop(case: dict, mesh: dict, prop: str):
    """One value of E, nu or k per element (a scalar when the part has a single material)."""
    import numpy as np
    groups = element_groups(case, mesh.get("tet_body", np.zeros(len(mesh["tets"]), int)))
    if len(groups) == 1:
        return groups[0][1][prop]
    out = np.empty(len(mesh["tets"]))
    for idx, p in groups:
        out[idx] = p[prop]
    return out


def element_k(case: dict, mesh: dict):
    return element_prop(case, mesh, "k")
MATERIALS_FLUID = {
    "water": {"nu": {"value": 1.0e-6, "unit": "m2/s"}, "rho": {"value": 998, "unit": "kg/m3"}},
    "air": {"nu": {"value": 1.5e-5, "unit": "m2/s"}, "rho": {"value": 1.2, "unit": "kg/m3"}},
}

STRUCT_ROLES = ["free", "fixed", 'beam-clamp', "symmetry", "constraint", "displacement", "load", "pressure", "moment", "bearing", "remote-force", 'spring']
FLOW_ROLES = ["wall", "moving-wall", "inlet", "outlet", "plane2d"]
THERMAL_ROLES = ["insulated", "temperature", "heat-flux", "convection"]
ELECTROSTATIC_ROLES = ["open", "voltage", "surface-charge"]
CURRENT_ROLES = ["insulated", "voltage", "current"]
DIRECTIONS = ["-z", "+z", "-y", "+y", "-x", "+x", "normal"]   # load direction; "normal" = pushes into the face

# value fields each role carries (path suffix -> default quantity)
ROLE_FIELDS = {
    'displacement': {'ux': {'value':0,'unit':'mm'}, 'uy':None, 'uz':None},
    'spring': {'stiffness': {'value':1e5,'unit':'N/m'}, 'components':'xyz'},
    'moment': {'torque': {'value': 100, 'unit': 'N-m'}, 'direction': '+z', 'point': {'value': [0, 0, 0], 'unit': 'mm'}},
    'bearing': {'force': {'value': 100, 'unit': 'N'}, 'direction': '+x'},
    'remote-force': {'force': {'value': 100, 'unit': 'N'}, 'direction': '-z', 'point': {'value': [0, 0, 0], 'unit': 'mm'}},
    "voltage": {"voltage": {"value": 0, "unit": "V"}},
    "surface-charge": {"charge": {"value": 1e-6, "unit": "C/m2"}},
    "current": {"current": {"value": 1, "unit": "A"}},
    "load": {"force": {"value": 100, "unit": "N"}, "direction": "-z"},
    "constraint": {"components": "xy"},        # displacement held at zero along these axes (any face, flat or curved)
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
    "copper": {"rho": 8960.0, "cp": 385.0}, "alloy_steel": {"rho": 7850.0, "cp": 470.0},
    "pla": {"rho": 1240.0, "cp": 1800.0}, "petg": {"rho": 1270.0, "cp": 1200.0}, "abs": {"rho": 1040.0, "cp": 1400.0},
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
        # the solvers for this benchmark build its walls and lid themselves: a changed role would be ignored silently
        "fixed_roles": True,
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
        "fixed_roles": True,
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

def _electric_template(kind, material, params, boundaries, reference, fields, faces=FACE_KEYS):
    return {"physics": "electric", "analysis": kind, "engines": ["builtin-fem"], "default_engine": "builtin-fem",
            "roles": ELECTROSTATIC_ROLES if kind == "electrostatic" else CURRENT_ROLES,
            "faces": list(faces), "face_labels": {f: f"face.{f}" for f in faces}, "locked_faces": [],
            "case": {"geometry": {"kind": "box", "params": params},
                     "physics": {"kind": kind, **({"joule_heating": True} if kind == "dc-current" else {})},
                     "materials": {"solid": {"preset": material, **copy.deepcopy(MATERIALS_SOLID[material])}},
                     "boundaries": boundaries, "mesh": {"method": "gmsh", "size": "normal", "order": 2},
                     "reference": {"kind": "analytic", "id": reference[0], "quantity": reference[1], "tolerance_pct": 1.0}},
            "params": fields}


_box_fields = [(f"geometry.params.{p}", f"param.{p}", "length", 0.01, 5000) for p in ("length", "width", "height")]
_eps_field = ("materials.solid.eps_r", "param.eps_r", "dimensionless", 1, 10000)
_sigma_field = ("materials.solid.sigma", "param.sigma", "electrical_conductivity", 1e-18, 1e9)
_k_field = ("materials.solid.k", "param.k", "conductivity", 0.001, 5000)
TEMPLATES["capacitor"] = _electric_template(
    "electrostatic", "ptfe", {p: {"value": v, "unit": "mm"} for p, v in zip(("length", "width", "height"), (50, 50, 2))},
    {**{f: {"role": "open"} for f in FACE_KEYS}, "z0": {"role": "voltage", "voltage": {"value": 0, "unit": "V"}},
     "z1": {"role": "voltage", "voltage": {"value": 100, "unit": "V"}}},
    ("parallel-plate-capacitance", "capacitance"), _box_fields + [("boundaries.z1.voltage", "param.voltage", "voltage", -1e6, 1e6), _eps_field])
TEMPLATES["coax"] = _electric_template(
    "electrostatic", "ptfe", {p: {"value": v, "unit": "mm"} for p, v in (("a", 1), ("b", 3.5), ("length", 10))},
    {"inner": {"role": "voltage", "voltage": {"value": 1000, "unit": "V"}},
     "outer": {"role": "voltage", "voltage": {"value": 0, "unit": "V"}}, "z0": {"role": "open"}, "z1": {"role": "open"}},
    ("coax-capacitance", "capacitance"), [(f"geometry.params.{p}", f"param.{p}", "length", 0.01, 5000) for p in ("a", "b", "length")] +
    [("boundaries.inner.voltage", "param.voltage", "voltage", -1e6, 1e6), _eps_field], ("inner", "outer", "z0", "z1"))
TEMPLATES["coax"]["case"]["geometry"]["kind"] = "tube"
TEMPLATES["capacitor"]["nova_tool"] = "https://novasolver.jp/tools/capacitor-energy.html"
TEMPLATES["coax"]["nova_tool"] = "https://novasolver.jp/tools/coaxial-cable-impedance.html"
TEMPLATES["busbar"] = _electric_template(
    "dc-current", "copper", {p: {"value": v, "unit": "mm"} for p, v in zip(("length", "width", "height"), (200, 20, 5))},
    {f: {"role": "voltage" if f in ("x0", "x1") else "insulated",
         **({"voltage": {"value": 20 if f == "x0" else 0, "unit": "mV"}} if f in ("x0", "x1") else {}),
         "thermal": {"role": "temperature", "temperature": {"value": 20, "unit": "degC"}} if f in ("x0", "x1") else {"role": "insulated"}}
     for f in FACE_KEYS}, ("busbar-joule-rise", "t_rise"),
    _box_fields + [("boundaries.x0.voltage", "param.voltage", "voltage", -1e6, 1e6), _sigma_field, _k_field])
for _id, _kind, _mat, _fields in [("electrostatic", "electrostatic", "ptfe", [_eps_field]),
                                  ("current", "dc-current", "copper", [_sigma_field, _k_field])]:
    _tp = _electric_template(_kind, _mat, {}, {}, ("none", ""), _fields)
    _tp.update({"import": True, "face_labels": {}})
    _tp["case"]["geometry"] = {"kind": "import"}
    _tp["case"]["reference"] = {"kind": "none"}
    TEMPLATES[f"import-{_id}"] = _tp



def _structural_template(tid, geometry, physics, boundaries, quantity, fields):
    return {'physics': 'structural', 'analysis': 'linear-static',
            'engines': ['builtin-fem', 'calculix'], 'default_engine': 'builtin-fem',
            'roles': STRUCT_ROLES, 'faces': list(boundaries),
            # "face.outer" is the coax's outer *electrode*; a shaft or disk rim is just its outer surface
            'face_labels': {f: 'face.outer_surface' if f == 'outer' else 'face.'+f for f in boundaries}, 'locked_faces': [],
            'case': {'geometry': geometry, 'physics': {'kind': 'linear-static', **physics},
                     'materials': {'solid': {'preset': 'steel', **copy.deepcopy(MATERIALS_SOLID['steel'])}},
                     'boundaries': boundaries, 'mesh': {'method': 'gmsh', 'size': 'normal', 'order': 2},
                     'reference': {'kind': 'analytic', 'id': tid, 'quantity': quantity, 'tolerance_pct': 2.}},
            'params': fields}


def _box(l, w, h):
    return {'kind': 'box', 'params': {k: {'value': v, 'unit': 'mm'} for k,v in zip(('length','width','height'), (l,w,h))}}


_free = {f: {'role': 'free'} for f in FACE_KEYS}
TEMPLATES['cantilever-modal'] = _structural_template('cantilever-modal', _box(200,10,10),
    {'analysis': 'modal', 'modes': 6}, {**copy.deepcopy(_free), 'x0': {'role': 'fixed'}}, 'frequency', _box_fields)
# Euler columns, L/h = 40. The clamped column is driven by a 0.1 mm axial shortening of x1 with y and z held.
TEMPLATES['column-buckling'] = _structural_template('column-buckling', _box(400,10,10), {'analysis': 'buckling', 'modes': 4},
    {**copy.deepcopy(_free), 'x0': {'role': 'fixed'}, 'x1': {'role': 'load', 'force': {'value': 1, 'unit': 'kN'}, 'direction': '-x'}},
    'critical_load', _box_fields + [('boundaries.x1.force', 'field.force', 'force', 0, 1e9)])
TEMPLATES['column-buckling-clamped'] = _structural_template('column-buckling-clamped', _box(400,10,10), {'analysis': 'buckling', 'modes': 4},
    {**copy.deepcopy(_free), 'x0': {'role': 'fixed'},
     'x1': {'role': 'displacement', 'ux': {'value': -0.1, 'unit': 'mm'}, 'uy': {'value': 0, 'unit': 'mm'}, 'uz': {'value': 0, 'unit': 'mm'}}},
    'critical_load', _box_fields)
# Fatigue of a bar loaded 0 -> 15 kN -> 0 (R = 0, sigma_max 150 MPa), polished: Goodman by hand.
TEMPLATES['fatigue-bar'] = _structural_template('fatigue-bar', _box(100,10,10),
    {'fatigue': {'enabled': True, 'ratio': 0.0, 'surface': 'polished', 'cycles': 1e6}},
    {**copy.deepcopy(_free), 'x0': {'role': 'constraint', 'components': 'x'}, 'y0': {'role': 'symmetry'},
     'z0': {'role': 'symmetry'}, 'x1': {'role': 'load', 'force': {'value': 15, 'unit': 'kN'}, 'direction': '+x'}},
    'fatigue_sf', _box_fields + [('boundaries.x1.force', 'field.force', 'force', 0, 1e9)])
TEMPLATES['fatigue-bar']['case']['reference']['tolerance_pct'] = 1.
for _tid in ('thermal-bar-fixed', 'thermal-bar-free'):
    _b = {**copy.deepcopy(_free), 'x0': {'role': 'constraint', 'components': 'x'},
          'y0': {'role': 'symmetry'}, 'z0': {'role': 'symmetry'}}
    if _tid.endswith('fixed'):
        _b['x1'] = {'role': 'constraint', 'components': 'x'}
    TEMPLATES[_tid] = _structural_template(_tid, _box(100,10,10),
        {'thermal_load': {'mode': 'uniform', 'temperature': {'value': 120, 'unit': 'degC'}},
         'T_ref': {'value': 20, 'unit': 'degC'}}, _b, 'thermal_stress' if _tid.endswith('fixed') else 'elongation', _box_fields)
TEMPLATES['thermal-bar-free']['case']['reference']['tolerance_pct'] = 1.
TEMPLATES['hanging-bar'] = _structural_template('hanging-bar', _box(20,20,1000),
    {'gravity': {'enabled': True, 'g': {'value': 9.81, 'unit': 'm/s2'}, 'direction': '-z'}},
    {**copy.deepcopy(_free), 'z1': {'role': 'constraint', 'components': 'z'},
     'x0': {'role': 'symmetry'}, 'y0': {'role': 'symmetry'}}, 'tip_disp', _box_fields)
TEMPLATES['rotating-disk'] = _structural_template('rotating-disk',
    {'kind': 'quarter_disk', 'params': {'radius': {'value': 100, 'unit': 'mm'}, 'height': {'value': 2.5, 'unit': 'mm'}}},
    {'rotation': {'enabled': True, 'rpm': 10000., 'axis': 'z', 'axis_point': [0,0,0]}},
    {'x0': {'role': 'symmetry'}, 'y0': {'role': 'symmetry'}, 'z0': {'role': 'symmetry'},
     'z1': {'role': 'free'}, 'outer': {'role': 'free'}}, 'center_stress',
    [('geometry.params.radius', 'param.radius', 'length', 1, 5000), ('geometry.params.height', 'param.height', 'length', .1, 50)])
TEMPLATES['shaft-torsion'] = _structural_template('shaft-torsion',
    {'kind': 'shaft', 'params': {'radius': {'value': 10, 'unit': 'mm'}, 'height': {'value': 200, 'unit': 'mm'}}}, {},
    {'z0': {'role': 'fixed'}, 'z1': {'role': 'moment', 'torque': {'value': 100, 'unit': 'N-m'}, 'direction': '+z',
                                  'point': {'value': [0,0,200], 'unit': 'mm'}}, 'outer': {'role': 'free'}}, 'twist',
    [('geometry.params.radius', 'param.radius', 'length', 1, 5000), ('geometry.params.height', 'param.height', 'length', 1, 5000),
     ('boundaries.z1.torque', 'field.torque', 'torque', 0, 1e8)])

DEFAULT_ROLE = {"structural": "free", "thermal": "insulated", "cfd": "wall", "flow": "wall", "external": "wall",
                "conjugate": "insulated", "electric": "open", "electrostatic": "open", "current": "insulated"}


for _name,_E,_nu in [('rubber',5,.49),('tpu',26,.45),('silicone',1.5,.49)]:
    MATERIALS_SOLID[_name] = {**copy.deepcopy(MATERIALS_SOLID['ptfe']), 'model':'neo-hookean',
                            'E':{'value':_E,'unit':'MPa'},'nu':{'value':_nu,'unit':'-'}}

_nonlinear = {'analysis':'nonlinear','nonlinear':{'large_deformation':True,'steps':'auto','max_iterations':25}}
TEMPLATES['large-cantilever'] = _structural_template('large-cantilever',_box(200,20,2),copy.deepcopy(_nonlinear),
    {**copy.deepcopy(_free),'x0':{'role':'fixed'},'x1':{'role':'load','force':{'value':205e9*(.02*.002**3/12)/.2**2,'unit':'N'},'direction':'-z'}},
    'tip_disp',_box_fields)
TEMPLATES['plastic-bar'] = _structural_template('plastic-bar',_box(100,10,10),
    {'analysis':'nonlinear','nonlinear':{'large_deformation':False,'steps':10,'max_iterations':25,'face':'x1',
                                      'path':[1.,1-(250e6+2.05e9*(.01-250e6/205e9))/(205e9*.01),0.]}},
    {**copy.deepcopy(_free),'x0':{'role':'constraint','components':'x'},'y0':{'role':'symmetry'},'z0':{'role':'symmetry'},
     'x1':{'role':'displacement','ux':{'value':1,'unit':'mm'},'uy':None,'uz':None}},'axial_stress',_box_fields)
TEMPLATES['plastic-beam-collapse'] = _structural_template('plastic-beam-collapse',_box(200,10,20),
    {'analysis':'nonlinear','nonlinear':{'large_deformation':False,'steps':20,'max_iterations':25}},
    {**copy.deepcopy(_free),'x0':{'role':'fixed'},'x1':{'role':'load','force':{'value':1.1*250e6*.01*.02**2/(4*.2),'unit':'N'},'direction':'-z'}},
    'limit_load',_box_fields)
for _tid in ('plastic-bar','plastic-beam-collapse'):
    _mat = TEMPLATES[_tid]['case']['materials']['solid']
    _mat.update(model='elastoplastic',sy={'value':250,'unit':'MPa'},H={'value':0 if _tid.endswith('collapse') else 2.05e9,'unit':'Pa'})
for _tid in ('large-cantilever','plastic-beam-collapse'):
    TEMPLATES[_tid]['case']['boundaries']['x0'] = {'role':'beam-clamp'}
# A spring-steel strip: the elastica bends it to about 1 GPa, which mild steel (235 MPa) would not survive elastically.
TEMPLATES['large-cantilever']['case']['materials']['solid'] = {**copy.deepcopy(MATERIALS_SOLID['steel']),
    'preset':'custom','sy':{'value':1400,'unit':'MPa'}}
TEMPLATES['rubber-tension'] = _structural_template('rubber-tension',_box(10,10,50),copy.deepcopy(_nonlinear),
    {**copy.deepcopy(_free),'x0':{'role':'symmetry'},'y0':{'role':'symmetry'},'z0':{'role':'constraint','components':'z'},
     'z1':{'role':'displacement','ux':None,'uy':None,'uz':{'value':50,'unit':'mm'}}},'axial_stress',_box_fields)
TEMPLATES['rubber-tension']['case']['materials']['solid'] = {'preset':'tpu',**copy.deepcopy(MATERIALS_SOLID['tpu'])}
TEMPLATES['rubber-tension']['case']['physics']['nonlinear']['face'] = 'z1'

TEMPLATES['press-fit'] = _structural_template('press-fit',
    {'kind':'press_fit','params':{'radius':{'value':20,'unit':'mm'},'outer_radius':{'value':40,'unit':'mm'},'height':{'value':20,'unit':'mm'}}},
    {},{'x0':{'role':'symmetry'},'y0':{'role':'symmetry'},'z0':{'role':'symmetry'},'z1':{'role':'free'},'outer':{'role':'free'}},
    'contact_pressure',[(f'geometry.params.{k}','param.'+k,'length',1,500) for k in ('radius','outer_radius','height')])
TEMPLATES['press-fit']['case']['contacts'] = {'interface':{'type':'frictionless','mu':.2,'offset':{'value':.02,'unit':'mm'}}}
for _tid in ('stacked-blocks','friction-block'):
    _b = {'bottom':{'role':'fixed'},'top':{'role':'pressure','pressure':{'value':10,'unit':'MPa'}},
          'x0':{'role':'symmetry'},'y0':{'role':'symmetry'},'x1':{'role':'free'},'lower_x1':{'role':'free'},'y1':{'role':'free'}}
    if _tid == 'friction-block':
        _b['x0'] = {'role':'spring','stiffness':{'value':1e3,'unit':'N/m'},'components':'x'}
        _b['x1'] = {'role':'load','force':{'value':400,'unit':'N'},'direction':'+x'}
    TEMPLATES[_tid] = _structural_template(_tid,{'kind':'stacked','params':{'length':{'value':20,'unit':'mm'},'width':{'value':20,'unit':'mm'},'height':{'value':20,'unit':'mm'}}},
        {},_b,'contact_force',_box_fields)
    TEMPLATES[_tid]['case']['contacts'] = {'interface':{'type':'frictional' if _tid == 'friction-block' else 'frictionless','mu':.2,'offset':{'value':0,'unit':'mm'}}}
# Separate parts (no shared face), meshed independently: the upper block is finer, so the contact is non-matching.
for _tid in ('gap-blocks', 'tied-parts'):
    _gap = 0.05 if _tid == 'gap-blocks' else 0
    _b = {'bottom': {'role': 'constraint', 'components': 'z'}, 'x0': {'role': 'symmetry'}, 'y0': {'role': 'symmetry'},
          'x1': {'role': 'free'}, 'y1': {'role': 'free'}, 'lower_top': {'role': 'free'}, 'upper_bottom': {'role': 'free'},
          'top': {'role': 'displacement', 'ux': None, 'uy': None, 'uz': {'value': -0.1 if _tid == 'gap-blocks' else 0.05, 'unit': 'mm'}}}
    TEMPLATES[_tid] = _structural_template(_tid, {'kind': 'gap_blocks', 'params': {
        'length': {'value': 20, 'unit': 'mm'}, 'width': {'value': 20, 'unit': 'mm'}, 'height': {'value': 20, 'unit': 'mm'},
        'gap': {'value': _gap, 'unit': 'mm'}}}, {}, _b, 'contact_force',
        _box_fields + [('geometry.params.gap', 'param.block_gap', 'length', 0, 50)])
    TEMPLATES[_tid]['case']['contact_pairs'] = {'interface': {'master': ['lower_top'], 'slave': ['upper_bottom'],
        'type': 'frictionless' if _tid == 'gap-blocks' else 'bonded', 'mu': .2, 'search': {'value': 1, 'unit': 'mm'}}}
    TEMPLATES[_tid]['case']['reference']['tolerance_pct'] = .5
# Hertz line contact: R 40 mm steel cylinder on a steel block, a 0.5 mm slab held in z (plane strain), quarter model.
# The load gives a contact half-width a = 1 mm (R/40, peak strain about 0.7 %, so small strain holds): P = a^2 pi E*/(4R)
# per metre; the model carries half of it.
# The block is 10a wide and 8a deep: a small model that solves in about a minute, close enough to a half-space.
_Es = 205e9/(2*(1-.3**2))
TEMPLATES['hertz-cylinder'] = _structural_template('hertz-cylinder', {'kind': 'hertz', 'params': {
    'radius': {'value': 40, 'unit': 'mm'}, 'length': {'value': 10, 'unit': 'mm'}, 'height': {'value': 8, 'unit': 'mm'},
    'thickness': {'value': 0.5, 'unit': 'mm'}}}, {},
    {'load': {'role': 'load', 'force': {'value': round(1e-3**2*3.141592653589793*_Es/(4*.04)*.5e-3/2, 3), 'unit': 'N'},
              'direction': '-y'},
     'x0': {'role': 'symmetry'}, 'bottom': {'role': 'fixed'}, 'z0': {'role': 'constraint', 'components': 'z'},
     'z1': {'role': 'constraint', 'components': 'z'}, 'x1': {'role': 'free'}, 'block_top': {'role': 'free'},
     'cyl_surface': {'role': 'free'}}, 'contact_pressure',
    [('geometry.params.radius', 'param.radius', 'length', 1, 1000), ('boundaries.load.force', 'field.force', 'force', 0, 1e9)])
TEMPLATES['hertz-cylinder']['case']['contact_pairs'] = {'interface': {'master': ['cyl_surface'], 'slave': ['block_top'],
    'type': 'frictionless', 'mu': .2, 'search': {'value': 2, 'unit': 'mm'}}}
TEMPLATES['hertz-cylinder']['case']['reference']['tolerance_pct'] = 5.
TEMPLATES['friction-block']['case']['body_props'] ={'b1':{'nu':{'value':0,'unit':'-'}},'b2':{'nu':{'value':0,'unit':'-'}}}
TEMPLATES['stacked-blocks']['case']['reference']['tolerance_pct'] = .5
TEMPLATES['friction-block']['case']['reference']['tolerance_pct'] = 1.
TEMPLATES['plastic-bar']['case']['reference']['tolerance_pct'] = 1.
TEMPLATES['plastic-beam-collapse']['case']['reference']['tolerance_pct'] = 3.


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
    case = {
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
    for key in ('contacts','contact_pairs','body_materials','body_props'):
        if key in c:
            case[key] = c[key]
    face_descriptors(case)
    return case


def face_descriptors(case: dict) -> None:
    """Cheap primitive descriptors; imported faces retain the CAD kernel's descriptors."""
    if case['geometry']['kind'] in ('gap_blocks', 'hertz'):
        own = {'bottom': ['b1'], 'lower_top': ['b1'], 'upper_bottom': ['b2'], 'top': ['b2']} \
            if case['geometry']['kind'] == 'gap_blocks' else \
            {'bottom': ['b1'], 'block_top': ['b1'], 'x1': ['b1'], 'cyl_surface': ['b2'], 'load': ['b2']}   # x1: block only
        case['geometry']['faces'] = [{'key':k,'n':i+1,'type':'Plane','bodies':own.get(k,['b1','b2']),'interface':False,
            'neighbors':[],'smooth_neighbors':[]} for i,k in enumerate(face_keys(case))]
        case['body_materials'] = case.get('body_materials',{'b1':'steel','b2':'steel'})
        return
    if case['geometry']['kind'] in ('press_fit','stacked'):
        from .geometry import dims
        size = dims(case)
        keys = face_keys(case)
        case['geometry']['faces'] = [{'key':k,'n':i+1,'type':'Plane','bodies':['b1','b2'],
            'interface':False,'neighbors':[],'smooth_neighbors':[]} for i,k in enumerate(keys)]
        from .units import to_si
        import math
        radius = to_si(case['geometry']['params'].get('radius',0))
        case['geometry']['faces'].append({'key':'interface','n':len(keys)+1,'type':'Cylinder' if radius else 'Plane',
            'bodies':['b1','b2'],'interface':True,'area':math.pi/2*radius*size[2] if radius else size[0]*size[1]})
        case['body_materials'] = case.get('body_materials',{'b1':'steel','b2':'steel'})
        return
    if case['geometry']['kind'] == 'import':
        return
    if case['geometry']['kind'] in ('shaft', 'quarter_disk'):
        from .units import to_si
        import math
        p = case['geometry']['params']
        r,h = to_si(p['radius']),to_si(p['height'])
        quarter = case['geometry']['kind'] == 'quarter_disk'
        keys = face_keys(case)
        faces = []
        for i,k in enumerate(keys):
            f = {'key':k,'n':i+1,'neighbors':[v for v in keys if v != k], 'smooth_neighbors':[]}
            if k == 'outer':
                f.update(type='Cylinder', axis=[0,0,1], axis_point=[0,0,0], radius=r,
                         centroid=[0,0,h/2], area=(math.pi/2 if quarter else 2*math.pi)*r*h,
                         bbox=[[0,0,0] if quarter else [-r,-r,0],[r,r,h]])
            else:
                axis = 'xyz'.index(k[0]); normal = [0,0,0]; normal[axis] = -1 if k[1] == '0' else 1
                lo,hi = ([0,0,0] if quarter else [-r,-r,0]),[r,r,h]
                lo[axis] = hi[axis] = h if k == 'z1' else 0
                f.update(type='Plane',normal=normal,bbox=[lo,hi],centroid=[(a+b)/2 for a,b in zip(lo,hi)],
                         area=math.pi*r*r/(4 if quarter else 1) if axis == 2 else r*h)
            faces.append(f)
        case['geometry']['faces'] = faces
        return
    from .geometry import dims
    import math
    size = dims(case)
    keys = face_keys(case)
    faces = []
    for i, key in enumerate(keys):
        f = {'key': key, 'n': i + 1, 'neighbors': [], 'smooth_neighbors': []}
        if key in FACE_KEYS:
            axis = 'xyz'.index(key[0])
            n = [0., 0., 0.]
            n[axis] = -1. if key[1] == '0' else 1.
            lo, hi = [0., 0., 0.], list(size)
            lo[axis] = hi[axis] = size[axis] if key[1] == '1' else 0.
            f.update(type='Plane', normal=n, bbox=[lo, hi], centroid=[(a+b)/2 for a,b in zip(lo,hi)],
                     area=math.prod(size[j] for j in range(3) if j != axis),
                     neighbors=[k for k in keys if k != key and (k not in FACE_KEYS or k[0] != key[0])])
        if case['geometry']['kind'] == 'tube':
            from .units import to_si
            a, b = (to_si(case['geometry']['params'][k]) for k in ('a', 'b'))
            if key in ('inner', 'outer'):
                r = a if key == 'inner' else b
                f.update(type='Cylinder', axis=[0., 0., 1.], axis_point=[0., 0., 0.], radius=r,
                         bbox=[[-r, -r, 0.], [r, r, size[2]]], area=2*math.pi*r*size[2],
                         centroid=[0., 0., size[2]/2], neighbors=['z0', 'z1'])
            else:
                f.update(area=math.pi*(b*b-a*a), neighbors=['inner', 'outer'],
                         bbox=[[-b, -b, f['centroid'][2]], [b, b, f['centroid'][2]]],
                         centroid=[0., 0., f['centroid'][2]])
        if case['geometry']['kind'] == 'plate_hole':
            from .units import to_si
            r = to_si(case['geometry']['params']['hole'])/2
            if key == 'hole':
                f.update(type='Cylinder', axis=[0., 0., 1.], axis_point=[size[0]/2, size[1]/2, 0.],
                         radius=r, centroid=[size[0]/2, size[1]/2, size[2]/2], area=2*math.pi*r*size[2],
                         bbox=[[size[0]/2-r, size[1]/2-r, 0.], [size[0]/2+r, size[1]/2+r, size[2]]],
                         neighbors=['z0', 'z1'])
            elif key[0] == 'z':
                f['area'] -= math.pi*r*r
            else:
                f['neighbors'] = [k for k in f['neighbors'] if k != 'hole']
        faces.append(f)
    case['geometry']['faces'] = faces
