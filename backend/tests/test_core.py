"""Core tests: units, editing rules, built-in solvers against references, compilers. Run: python -m pytest backend/tests -q"""
from __future__ import annotations

import os
import tempfile

import numpy as np
import pytest

os.environ["NOVASTUDIO_WORKSPACE"] = tempfile.mkdtemp(prefix="ns_test_")

from novastudio import cavity_fd, commands as C, external, units  # noqa: E402
from novastudio.store import StudioError  # noqa: E402


def test_units_roundtrip():
    assert units.to_si("5 mm") == pytest.approx(0.005)
    assert units.to_si({"value": 2, "unit": "kN"}) == 2000
    assert units.normalize("70 GPa", {"value": 205, "unit": "GPa"}) == {"value": 70.0, "unit": "GPa"}
    with pytest.raises(units.UnitError):
        units.normalize("3 m/s", {"value": 1, "unit": "mm"})


def test_cantilever_preview_verified():
    cid = C.create_case("cantilever")["case"]["case_id"]
    r = C.run_simulation(cid, "preview", wait_s=120)
    assert r["done"] and r["results"]["gates"] == {"ran": True, "converged": True, "verified": True}
    v = r["results"]["verification"]
    assert abs(v["error_pct"]) < 2.0


def test_edit_rules_and_blocking():
    p = C.create_case("cantilever")
    cid, rev = p["case"]["case_id"], p["case"]["revision"]
    with pytest.raises(StudioError) as e:
        C.update_case(cid, rev + 3, {"mesh.size": "fine"})
    assert e.value.key == "err.revision"
    with pytest.raises(StudioError) as e:
        C.update_case(cid, rev, {"boundaries.x0.role": "inlet"})
    assert e.value.key == "err.role"
    with pytest.raises(StudioError) as e:
        C.update_case(cid, rev, {"case_id": "x"})
    assert e.value.key == "err.path"
    C.update_case(cid, rev, {"boundaries.x0.role": "free"})
    with pytest.raises(StudioError) as e:
        C.run_simulation(cid, "preview")
    assert e.value.key == "err.blocked"


def test_yield_warning():
    cid = C.create_case("cantilever", {"geometry.params.length": "300 mm", "boundaries.x1.force": "2 kN",
                                       "materials.solid.preset": "aluminium"})["case"]["case_id"]
    r = C.run_simulation(cid, "preview", wait_s=120)
    assert any(w["code"] == "yield" for w in r["results"]["warnings"])


def test_cavity_matches_ghia():
    r = cavity_fd.solve(100.0, "coarse")
    assert r["converged"]
    assert cavity_fd.ghia_error(r)["mean_abs"] < 0.01


def test_openfoam_compiler_cavity():
    cid = C.create_case("cavity")["case"]["case_id"]
    from novastudio import store
    files = external.compile_openfoam(store.load(cid))
    assert {"system/blockMeshDict", "system/controlDict", "system/fvSchemes", "system/fvSolution",
            "constant/transportProperties", "0/U", "0/p"} <= set(files)
    assert "hex (0 1 2 3 4 5 6 7) (65 65 1)" in files["system/blockMeshDict"]
    assert "lid" in files["0/U"] and "uniform (1 0 0)" in files["0/U"]
    assert "nu              0.001;" in files["constant/transportProperties"]
    for text in files.values():
        assert text.count("{") == text.count("}")


def test_calculix_compiler():
    cid = C.create_case("cantilever")["case"]["case_id"]
    C.generate_mesh(cid)
    from novastudio import store
    from novastudio.store import case_dir
    mesh = dict(np.load(case_dir(cid) / "mesh" / "mesh.npz"))
    inp = external.compile_calculix(store.load(cid), mesh)
    assert "*ELEMENT, TYPE=C3D10" in inp and "*CLOAD" in inp and "*BOUNDARY" in inp
    loads = [float(l.split(",")[2]) for l in inp.split("*CLOAD")[1].split("*NODE FILE")[0].strip().splitlines()]
    assert sum(loads) == pytest.approx(-1000.0, rel=1e-9)        # consistent loads add up to the applied force


def test_range_and_labels():
    p = C.create_case("cantilever")
    cid, rev = p["case"]["case_id"], p["case"]["revision"]
    with pytest.raises(StudioError) as e:
        C.update_case(cid, rev, {"geometry.params.length": "-5 mm"})
    assert e.value.key == "err.range"
    lp = {x["path"]: x for x in p["ui"]["params"]}["geometry.params.length"]
    assert lp["min_si"] == pytest.approx(0.01) and lp["max_si"] == pytest.approx(5.0)
    cav = C.create_case("cavity", lang="zh")
    labels = [f["label"] for f in cav["ui"]["faces"]]
    assert len(set(labels)) == len(labels), labels


SAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "samples")


def test_thermal_block_exact():
    cid = C.create_case("thermal-block")["case"]["case_id"]
    r = C.run_simulation(cid, "preview", wait_s=300)
    assert r["results"]["gates"]["verified"] and abs(r["results"]["verification"]["error_pct"]) < 0.1


def test_import_bracket_and_cross_check():
    p = C.import_geometry("structural", "l_bracket.step", path=os.path.join(SAMPLES, "l_bracket.step"))
    faces = p["case"]["geometry"]["faces"]
    assert len(faces) == 9 and all(f["role"] == "free" for f in p["ui"]["faces"])
    bottom = min(faces, key=lambda f: f["centroid"][2]); top = max(faces, key=lambda f: f["centroid"][2])
    cid = p["case"]["case_id"]
    C.update_case(cid, p["case"]["revision"], {f"boundaries.{bottom['key']}.role": "fixed",
                                               f"boundaries.{top['key']}.role": "load",
                                               f"boundaries.{top['key']}.force": "500 N",
                                               f"boundaries.{top['key']}.direction": "-x"})
    a = C.run_simulation(cid, "preview", wait_s=300)["results"]
    assert a["gates"]["converged"] and not a["gates"]["verified"]     # no reference for an arbitrary shape
    from novastudio.config import find_calculix
    if find_calculix():
        b = C.run_simulation(cid, "final", wait_s=600)["results"]
        da = {c["key"]: c["value"] for c in a["cards"]}["max_disp"]
        db = {c["key"]: c["value"] for c in b["cards"]}["max_disp"]
        assert abs(da - db) / db < 1e-3                                # built-in and CalculiX agree


def test_import_stl_matches_step(tmp_path):
    """A triangulated STL in mm (e.g. from Blender) gives the same faces and answer as the STEP it came from."""
    import gmsh
    stl = str(tmp_path / "bracket.stl")
    gmsh.initialize(); gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
    gmsh.model.occ.importShapes(os.path.join(SAMPLES, "l_bracket.step")); gmsh.model.occ.synchronize()
    gmsh.option.setNumber("Mesh.MeshSizeMax", 1.0)
    gmsh.model.mesh.generate(2); gmsh.write(stl); gmsh.finalize()
    disp = []
    for name, path in (("l_bracket.step", os.path.join(SAMPLES, "l_bracket.step")), ("bracket.stl", stl)):
        p = C.import_geometry("structural", name, path=path)
        faces = p["case"]["geometry"]["faces"]
        assert len(faces) == 9
        bottom = min(faces, key=lambda f: f["centroid"][2]); top = max(faces, key=lambda f: f["centroid"][2])
        assert bottom["area"] == pytest.approx(3.1215e-3, rel=1e-3)
        C.update_case(p["case"]["case_id"], p["case"]["revision"], {f"boundaries.{bottom['key']}.role": "fixed",
                                                                    f"boundaries.{top['key']}.role": "load",
                                                                    f"boundaries.{top['key']}.force": "500 N",
                                                                    f"boundaries.{top['key']}.direction": "-x"})
        r = C.run_simulation(p["case"]["case_id"], "preview", wait_s=300)["results"]
        disp.append({c["key"]: c["value"] for c in r["cards"]}["max_disp"])
    # two different meshes of the same part (faceted holes, other node layout): agree within discretisation error
    assert abs(disp[1] - disp[0]) / disp[0] < 0.02
    # the STL mesh study really refines (surface remeshed per level) and keeps the case's face names
    r = C.check_convergence(p["case"]["case_id"], wait_s=900)["results"]
    n = [lv["elements"] for lv in r["convergence"]["levels"]]
    assert n[1] >= 1.3 * n[0] and n[2] >= 1.3 * n[1]
    assert r["convergence"]["pass"] and r["gates"]["verified"]


def test_lost_condition_face_stops_the_run():
    """A face that carries a load but is missing from the mesh must stop the run, not solve without the load."""
    from novastudio.run_worker import check_condition_faces
    tri = np.array([[0, 1, 2]])
    case = {"boundaries": {"f1": {"role": "load"}, "f2": {"role": "fixed"}, "f3": {"role": "free"}}}
    check_condition_faces(case, {"face_f1": tri, "face_f2": tri})              # f3 is passive: may be absent
    with pytest.raises(StudioError) as e:
        check_condition_faces(case, {"face_f2": tri})
    assert e.value.key == "err.face_lost" and e.value.kw["faces"] == "f1"


def test_folded_faces_found():
    """Two triangles folded flat onto each other across their shared edge are reported; a flat pair is not."""
    from novastudio.mesh_worker import folded_faces
    V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0.2, 0.6, 1e-3]], float)   # vertex 4 folds back over 0
    assert len(folded_faces(V, np.array([[0, 1, 2], [1, 3, 2]]))) == 0
    assert set(folded_faces(V, np.array([[0, 1, 2], [1, 4, 2]]))) == {0, 1}


def test_foam_workdir_is_unique_and_empty(tmp_path, monkeypatch):
    """Jobs in non-ASCII folders solve in an ASCII scratch folder: two convergence levels both called 'coarse' must
    not share it, and nothing from an earlier run may remain in it."""
    from novastudio.config import foam_workdir
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    a, b = tmp_path / "解析A" / "coarse", tmp_path / "解析B" / "coarse"
    a.mkdir(parents=True); b.mkdir(parents=True)
    wa = foam_workdir(a)
    (wa / "4000").mkdir()                                    # a time step left by a run
    assert foam_workdir(b) != wa
    assert foam_workdir(a) == wa and not (wa / "4000").exists()


def test_hollow_shell_import_keeps_inner_face_and_true_size(tmp_path):
    """Shape healing once dropped the inner face of a hollow shell (it became a full body), and the whole-model box
    of a revolved surface was read 1000x too long. A hollow sphere must keep both faces and its real size."""
    import gmsh
    path = str(tmp_path / "shell.brep")
    gmsh.initialize(); gmsh.option.setNumber("General.Terminal", 0)
    occ = gmsh.model.occ
    occ.cut([(3, occ.addSphere(0, 0, 0, 0.010))], [(3, occ.addSphere(0, 0, 0, 0.009))])
    occ.synchronize(); gmsh.write(path); gmsh.finalize()
    p = C.import_geometry("structural", "shell.brep", path=path)
    g = p["case"]["geometry"]
    assert len(g["faces"]) == 2
    (x0, y0, z0), (x1, y1, z1) = g["bbox"]
    assert abs((x1 - x0) - 0.020) < 1e-3 and abs((z1 - z0) - 0.020) < 1e-3


def test_faceted_step_is_rejected_quickly():
    """A STEP made of thousands of flat triangles is refused at once with a pointer to STL; a real CAD STEP is not."""
    C.faceted_step_check(open(os.path.join(SAMPLES, "l_bracket.step"), "rb").read())
    fake = b"".join(b"#%d=ADVANCED_FACE('',(#1),#%d,.T.);\n#%d=PLANE('',#2);\n" % (3 * i, 3 * i + 1, 3 * i + 1)
                    for i in range(2500))
    with pytest.raises(StudioError) as e:
        C.faceted_step_check(fake)
    assert e.value.key == "err.faceted_step"


def test_import_rejects_bad_type():
    with pytest.raises(StudioError) as e:
        C.import_geometry("structural", "x.obj", data=b"o x")
    assert e.value.key == "err.cad_type"


def test_role_value_rules():
    p = C.create_case("thermal-block")
    cid, rev = p["case"]["case_id"], p["case"]["revision"]
    with pytest.raises(StudioError):
        C.update_case(cid, rev, {"boundaries.y0.flux": "5 kW/m2"})     # y0 is insulated: no flux field
    u = C.update_case(cid, rev, {"boundaries.y0.role": "heat-flux", "boundaries.y0.flux": "5 kW/m2"})
    assert u["case"]["boundaries"]["y0"] == {"role": "heat-flux", "flux": {"value": 5.0, "unit": "kW/m2"}}


def _openfoam_ready():
    from novastudio.config import engines
    return engines()["openfoam"]["available"]


@pytest.mark.skipif(not _openfoam_ready(), reason="OpenFOAM + MS-MPI not installed")
def test_openfoam_channel_poiseuille():
    cid = C.create_case("channel")["case"]["case_id"]
    r = C.run_simulation(cid, "final", wait_s=600)["results"]
    assert r["gates"]["verified"] and abs(r["verification"]["error_pct"]) < 2.0


@pytest.mark.skipif(not _openfoam_ready(), reason="OpenFOAM + MS-MPI not installed")
def test_openfoam_imported_elbow_mass_balance():
    p = C.open_sample("pipe_elbow")
    cid, faces = p["case"]["case_id"], p["case"]["geometry"]["faces"]
    planes = [f for f in faces if f["type"] == "Plane"]
    inlet = min(planes, key=lambda f: abs(f["centroid"][0])); outlet = next(f for f in planes if f is not inlet)
    C.update_case(cid, p["case"]["revision"], {f"boundaries.{inlet['key']}.role": "inlet",
                                               f"boundaries.{inlet['key']}.speed": "0.05 m/s",
                                               f"boundaries.{outlet['key']}.role": "outlet", "mesh.size": "coarse"})
    r = C.run_simulation(cid, "final", wait_s=1800)["results"]
    from novastudio import results as R
    m = R.load(cid)[1]["metrics"]
    assert r["gates"]["converged"] and m["mass_balance"] < 0.02 and m["dp_pa"] > 0
    pr = C.probe_results(cid, faces=[inlet["key"], outlet["key"]])["faces"]
    q_in = m["flow_rate_m3s"]           # inlet speed x the meshed (polygonal) inlet area, a little under the circle's
    # inlets and outlets report OpenFOAM's own face fluxes
    assert pr[0]["flow_out_m3s"] == pytest.approx(-q_in, rel=0.005)     # into the fluid at the inlet
    assert abs(pr[0]["flow_out_m3s"] + pr[1]["flow_out_m3s"]) < 0.02 * q_in
    assert pr[0]["mean"]["p"] > pr[1]["mean"]["p"]


def test_probe_cantilever_points_line_faces():
    from novastudio import geometry, store
    cid = C.create_case("cantilever")["case"]["case_id"]
    res = C.run_simulation(cid, "preview", wait_s=120)["results"]
    tip = {c["key"]: c["value"] for c in res["cards"]}["tip_disp"]
    L, W, H = (x * 1e3 for x in geometry.dims(store.load(cid)))
    r = C.probe_results(cid, points=[[L - 1e-3, W / 2, H / 2], [L + 50, W / 2, H / 2]],
                        line={"from": [0, W / 2, H / 2], "to": [L, W / 2, H / 2], "n": 21}, faces=["x1", "x0"])
    p_tip, p_out = r["points"]
    assert p_tip["inside"] and abs(p_tip["values"]["uz"]) == pytest.approx(tip, rel=0.03)
    assert not p_out["inside"]
    uz = [abs(s["values"]["uz"]) for s in r["line"]["samples"]]
    assert r["line"]["inside_fraction"] == 1.0 and all(b >= a - 1e-9 for a, b in zip(uz, uz[1:]))
    x1, x0 = r["faces"]
    assert x1["area_mm2"] == pytest.approx(W * H, rel=1e-6) and x0["max"]["disp"] < 1e-9
    assert x1["mean"]["disp"] == pytest.approx(tip, rel=0.05)


def test_symmetry_planes_give_uniform_compression():
    """A block held only by symmetry planes x0, y0, z0 and pressed on x1: sigma_xx = -p everywhere, u_x = -pL/E."""
    from novastudio import geometry, store, units as U
    p = C.create_case("cantilever")
    cid = p["case"]["case_id"]
    ch = {f"boundaries.{k}.role": "symmetry" for k in ("x0", "y0", "z0")}
    ch.update({"boundaries.x1.role": "pressure", "boundaries.x1.pressure": "10 MPa"})
    C.update_case(cid, p["case"]["revision"], ch)
    res = C.run_simulation(cid, "preview", wait_s=120)["results"]
    assert res["gates"]["converged"]
    case = store.load(cid)
    L, W, H = (x * 1e3 for x in geometry.dims(case))
    E = U.to_si(case["materials"]["solid"]["E"])
    pt = C.probe_results(cid, points=[[L / 2, W / 2, H / 2], [L - 1e-3, W / 2, H / 2]])["points"]
    assert pt[0]["values"]["sxx"] == pytest.approx(-10.0, rel=1e-3)
    assert abs(pt[0]["values"]["syy"]) < 0.01 and abs(pt[0]["values"]["vm"] - 10.0) < 0.01
    assert pt[1]["values"]["ux"] == pytest.approx(-10e6 * L / E, rel=1e-3)
    C.update_case(cid, case["revision"], {"boundaries.z0.role": "free"})
    with pytest.raises(StudioError):                      # only two directions held: the block can still slide
        r = C.run_simulation(cid, "preview", wait_s=120)
        if r["done"] and not r["results"]:
            raise StudioError("err.symmetry_rbm")


def _two_block_step(path):
    """Two 100 x 50 x 50 mm blocks side by side along x, as one STEP (an assembly of two bodies)."""
    import gmsh
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.occ.addBox(0, 0, 0, 100, 50, 50)
    gmsh.model.occ.addBox(100, 0, 0, 100, 50, 50)
    gmsh.model.occ.synchronize()
    gmsh.write(str(path))
    gmsh.finalize()


def _assembly(tmp_path, physics, mats):
    step = tmp_path / "two_blocks.step"
    _two_block_step(step)
    p = C.import_geometry(physics, step.name, path=str(step))
    d = C.describe_case(p["case"]["case_id"])
    bodies = sorted(d["body_materials"], key=lambda b: d["body_materials"][b]["centroid_mm"][0])
    faces = p["case"]["geometry"]["faces"]
    x0 = min(faces, key=lambda f: f["centroid"][0])["key"]
    x1 = max(faces, key=lambda f: f["centroid"][0])["key"]
    ch = {f"body_materials.{b}": m for b, m in zip(bodies, mats)}
    return p, bodies, x0, x1, ch


def test_two_material_wall_series_conduction(tmp_path):
    p, bodies, x0, x1, ch = _assembly(tmp_path, "thermal", ["steel", "steel"])
    ch.update({f"body_props.{bodies[1]}.k": "5 W/mK", f"boundaries.{x0}.role": "temperature",
               f"boundaries.{x0}.temperature": "100 degC", f"boundaries.{x1}.role": "temperature",
               f"boundaries.{x1}.temperature": "0 degC"})
    cid = p["case"]["case_id"]
    C.update_case(cid, p["case"]["revision"], ch)
    res = C.run_simulation(cid, "preview", wait_s=300)["results"]
    assert res["gates"]["converged"]
    # series resistance: 0.1/(50*0.0025) + 0.1/(5*0.0025) = 0.8 + 8 K/W -> Q = 100 / 8.8 W, interface at 100 - Q*0.8
    q_ref = 100 / 8.8
    flows = __import__("novastudio.results", fromlist=["load"]).load(cid)[1]["metrics"]["face_flows_w"]
    assert flows[x0] == pytest.approx(q_ref, rel=1e-3)
    t_if = C.probe_results(cid, points=[[100, 25, 25]])["points"][0]["values"]["temp"]
    assert t_if == pytest.approx(100 - q_ref * 0.8, abs=0.05)
    from novastudio.config import find_calculix
    if find_calculix():                         # one material and section per body in the CalculiX deck too
        C.run_simulation(cid, "final", wait_s=600)
        flows = __import__("novastudio.results", fromlist=["load"]).load(cid)[1]["metrics"]["face_flows_w"]
        assert flows[x0] == pytest.approx(q_ref, rel=1e-3)


def test_two_material_bar_in_tension(tmp_path):
    p, bodies, x0, x1, ch = _assembly(tmp_path, "structural", ["steel", "aluminium"])
    # no Poisson contraction (sideways strain -nu*sigma/E differs between the materials): the bonded interface then
    # carries no sideways stress and the bar is exactly uniaxial
    ch.update({f"boundaries.{x0}.role": "symmetry", f"boundaries.{x1}.role": "pressure",
               f"boundaries.{x1}.pressure": "-10 MPa", f"body_props.{bodies[0]}.nu": 1e-6,
               f"body_props.{bodies[1]}.nu": 1e-6})
    faces = p["case"]["geometry"]["faces"]
    for axis in (1, 2):                     # y0 and z0 planes of both blocks hold the sideways motion
        for f in faces:
            if abs(f["centroid"][axis]) < 1e-9:
                ch[f"boundaries.{f['key']}.role"] = "symmetry"
    cid = p["case"]["case_id"]
    C.update_case(cid, p["case"]["revision"], ch)
    res = C.run_simulation(cid, "preview", wait_s=300)["results"]
    assert res["gates"]["converged"]
    # uniaxial stress 10 MPa: elongation = 10e6 * (0.1/205e9 + 0.1/69e9)
    du = C.probe_results(cid, points=[[199.999, 25, 25]])["points"][0]["values"]["ux"]
    assert du == pytest.approx(10e6 * (0.1 / 205e9 + 0.1 / 69e9) * 1e3, rel=2e-3)


def test_clone_and_sweep_scale_linearly():
    from novastudio import jobs
    p = C.create_case("cantilever")
    cid = p["case"]["case_id"]
    c = C.clone_case(cid, {"boundaries.x1.force": "50 N"}, "variant")
    assert c["case"]["case_id"] != cid and c["case"]["revision"] == 2
    assert C.describe_case(cid)["revision"] == p["case"]["revision"]          # the original is untouched
    s = C.run_sweep(cid, "boundaries.x1.force", ["100 N", "200 N"], mode="preview")
    tips = []
    for row in s["cases"]:
        assert jobs.wait(row["job_id"], 300)["state"] == "done"
        cards = {k["key"]: k["value"] for k in C.get_results(row["case_id"])["cards"]}
        tips.append(cards["tip_disp"])
    assert tips[1] / tips[0] == pytest.approx(2.0, rel=1e-3)
    rows = C.compare_runs([x["case_id"] for x in s["cases"]])["rows"]
    assert all(r["gates"]["ran"] for r in rows)
    with pytest.raises(StudioError):
        C.run_sweep(cid, "boundaries.x1.force", [f"{i} N" for i in range(1, 10)])


def test_plate_hole_heywood():
    cid = C.create_case("plate-hole")["case"]["case_id"]
    r = C.run_simulation(cid, "preview", wait_s=900)["results"]
    assert r["gates"]["verified"] and abs(r["verification"]["error_pct"]) < 5


def test_fin_theory():
    cid = C.create_case("fin")["case"]["case_id"]
    r = C.run_simulation(cid, "preview", wait_s=300)["results"]
    assert r["gates"]["verified"] and abs(r["verification"]["error_pct"]) < 1


def test_convergence_study_verifies_imported_heatsink():
    p = C.open_sample("heatsink")
    cid, fs = p["case"]["case_id"], p["case"]["geometry"]["faces"]
    b = min(fs, key=lambda f: f["centroid"][2])
    ch = {f"boundaries.{f['key']}.role": "convection" for f in fs if f["key"] != b["key"]}
    ch[f"boundaries.{b['key']}.role"] = "heat-flux"
    ch[f"boundaries.{b['key']}.flux"] = "10 kW/m2"
    C.update_case(cid, p["case"]["revision"], ch)
    r = C.check_convergence(cid, wait_s=900)["results"]
    c = r["convergence"]
    assert [l["size"] for l in c["levels"]] == ["coarse", "normal", "fine"]
    assert r["verification"]["kind"] == "convergence" and r["gates"]["verified"] == c["pass"]
    assert c["gci_pct"] < 5


def test_gci_formula():
    from novastudio.run_worker import gci
    # exact second-order data f = 1 + h^2 with h halving: GCI must recover p = 2 and f_ext = 1
    lv = [{"h": h, "value": 1 + h * h} for h in (0.4, 0.2, 0.1)]
    g = gci(lv)
    assert abs(g["p"] - 2) < 1e-9 and abs(g["f_ext"] - 1) < 1e-9


@pytest.mark.skipif(not _openfoam_ready(), reason="OpenFOAM + MS-MPI not installed")
def test_sphere_drag_schiller_naumann():
    p = C.create_case("sphere-drag")
    cid = p["case"]["case_id"]
    C.update_case(cid, p["case"]["revision"], {"mesh.size": "coarse"})
    r = C.run_simulation(cid, "final", wait_s=3600)["results"]
    assert r["gates"]["verified"] and abs(r["verification"]["error_pct"]) < 8
