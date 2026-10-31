# SPEC: Studio 0.8 — shell elements (thin sheet metal, plates, thin-walled frames)

Owner: Claude (spec and acceptance). Implementer: a Claude agent in a separate worktree. Branch `v0.8-shells`.

## Why

Sheet-metal parts, plates, ducts, tanks and thin brackets are slow and inaccurate as solid tets: a 2 mm sheet over
500 mm needs hundreds of thousands of tet10 elements to get a few elements through the thickness, and coarse tets
lock in bending. Companies model these as shells. Studio has no shell element yet.

## Scope of this release

A built-in linear static shell solver (no CalculiX dependency, works in preview mode), templates with known answers,
and the results/MCP plumbing. Importing sheet bodies from STEP is phase 2 (section 6) and only if phase 1 is done.

## 0. Ground rules

- Read `CLAUDE.md` files are not needed; read the code. Old cases keep their behaviour exactly; the existing test
  suite (`backend/tests`, run with `..\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider` from
  `backend`) must still pass, except tool-count assertions you deliberately update.
- Match the surrounding code style (dense, few comments, comments say why). i18n keys must be identical in
  `backend/novastudio/i18n/{ja,en,zh}.json` and in `frontend/src/i18n/{ja,en,zh}.json`. Japanese and Chinese strings
  must be natural, not literal.
- `npm run build` in `frontend` must pass with zero TypeScript errors.
- Do not touch: updates.py, archive.py, examples.py, the release tooling, anything outside `studio/`.

## 1. Element

Flat facet 3-node triangle, 6 dof per node (ux, uy, uz, rx, ry, rz), linear, small displacement:
- membrane: constant-strain triangle (CST);
- bending: DKT (Discrete Kirchhoff Triangle, Batoz, Bathe & Ho 1980), thin plates, no shear locking;
- drilling: a small rotational stiffness k_rz = 1e-3 × (mean membrane diagonal) per node to remove the singularity
  of the drilling dof on flat regions (state it in a comment; it must not change the benchmark answers beyond 0.1 %).
- Local element frame (e1 along edge 12, e3 the normal), transform to global with the 18×18 rotation.
- Uniform thickness per case (`geometry.params.thickness`, later per face), isotropic E, nu from the existing
  material presets (`templates.solid_props`).
- Loads: pressure on the surface (normal, using the element normal orientation of the mesh), gravity
  (`physics.gravity`), nodal edge forces (force per edge distributed by length).
- Supports on edges: `fixed` (all 6 dof), `pinned` (translations), `simply-supported` (translation normal to the
  plate... for the templates: uz only, plus whatever in-plane holds are needed to stop rigid motion; make the role
  `constraint` with `components` among x, y, z, rx, ry, rz, which covers all of these), `symmetry` (normal translation
  and the two in-plane rotations about axes lying in the symmetry plane, for planes normal to x, y or z).
- Assembly in numpy/scipy (vectorised over elements like `fem_tet10.structural_system`), direct solve
  (`spsolve`) below 300k dof, AMG-CG above.

Stress output per node: membrane + bending at the top (+t/2) and bottom (−t/2) surfaces, von Mises of each, and the
max of both; displacement magnitude; uz.

## 2. Geometry and mesh

- New geometry kinds for templates: `plate` (rectangle length × width in the xy plane) and `cyl_roof`
  (cylindrical panel: radius R, length L along the axis, opening half-angle phi; axis along y).
- Mesh: gmsh 2D, linear triangles (order 1) on the surface, element size from `mesh.size`
  (coarse/normal/fine = length/12, /20, /32 for the plate; /12, /18, /28 for the roof); write `mesh.npz` with
  `nodes` (n,3), `tris` (e,3), `edge_<key>` (k,2 node pairs) for each named boundary edge, `face_surface` (the tris).
- Named edges: plate `x0`, `x1`, `y0`, `y1`; roof `straight_0`, `straight_1` (the free longitudinal edges),
  `curved_0`, `curved_1` (the end diaphragms).
- `geometry.dims`, `mesh_key`, `face_descriptors` must know the new kinds; the boundaries of a shell case are keyed
  by these edge names plus `surface`.

## 3. Templates (each with an exact or classic reference; put them in `templates.py`)

1. `plate-simply-supported`: square plate a = 1 m, t = 10 mm, steel, uniform pressure q = 10 kPa on `surface`,
   all four edges simply supported (uz held, plus in-plane holds at x0 (ux) and y0 (uy) only, so membrane stays free).
   Navier: w_max = 0.00406 q a^4 / D, D = E t^3 / (12 (1 − nu^2)) (nu = 0.3). Tolerance 2 %.
   Also report the centre moment check: sigma_x,max = 6 × 0.0479 q a^2 / t^2. Tolerance 3 %.
2. `plate-clamped`: the same plate with all edges fixed: w_max = 0.00126 q a^4 / D. Tolerance 3 %.
3. `scordelis-lo`: the MacNeal–Harder shell obstacle course roof: R = 25, L = 50, phi = 40°, t = 0.25, E = 4.32e8,
   nu = 0, gravity load 90 per unit area (use SI-consistent equivalent: keep the classic numbers as metres, Pa and
   N/m^2 and use a surface load of 90 Pa downward instead of gravity), ends on rigid diaphragms (ux = uz = 0 on the
   curved edges), straight edges free. Reference: vertical displacement at the midpoint of the free edge = 0.3024 m.
   Tolerance 3 % on the normal mesh (flat facet triangles converge slowly; if normal misses, use a finer default and
   say so in the template comment). Use symmetry (quarter model) if that makes it cheaper.
- Each template: `reference` in `structural.py`-style comparison dict with `formula`, `tolerance_pct`, routed so that
  `results.payload` shows the verification line. A mesh study (check_convergence) must work: add the study quantity
  in `run_worker` (the max displacement for the plates, the free-edge deflection for the roof).

## 4. Results, viewer, MCP

- `run_worker`: a `run_shell` path chosen when `case['geometry']['kind'] in ('plate', 'cyl_roof')` (or a
  `physics.element == 'shell'` flag; your call, document it). Save `results.npz` with `u` (n,3), `rot` (n,3),
  `vm_top`, `vm_bottom`, `vm` (max of both), `s_top` (n,6), `s_bottom` (n,6).
- `results.py`: kind `shell`; cards (max displacement, max von Mises, reaction, nodes, elements, and the template's
  reference quantity first); quantities vm, vm_top, vm_bottom, disp, uz; `field()` must return the surface
  triangles directly (the mesh is the surface) with displacement for the deformed view.
- `probe.py` / `sections.py` / `exports.py` (CSV of nodal values, VTU with triangles): handle kind `shell` or refuse
  with a clear StudioError (a section through a shell can be refused in this release).
- `checks.py`: errors for a missing thickness or a non-positive one, no support, no load.
- MCP: `create_case` with the new templates works unchanged; `describe_case` shows the thickness; document
  `geometry.params.thickness` in the update_case docstring. No new tool is required.
- Frontend: the boundaries step lists the edges by name (the viewer may not highlight edges yet; a list is enough).
  The thickness appears as an ordinary template parameter. Results render the surface like other structural results.

## 5. Tests (`backend/tests/test_v08_shells.py`)

1. Element patch tests on a distorted mesh: uniform membrane tension and uniform bending moment reproduced exactly
   (1e-8 relative).
2. Rigid-body motions give zero strain energy (6 modes) for a single element and a small mesh.
3. Each template within its tolerance; the plate deflection converges from coarse to fine (monotonic).
4. Rotating the whole plate model by an arbitrary rotation gives the same deflection magnitude (frame
   transformation check).
5. Symmetry: the quarter-model roof equals the full model to 0.5 % if you implement both.
6. MCP round trip: create `plate-simply-supported`, run, get_results shows the verification line.

## 6. Phase 2 (only if phase 1 passes): shells from STEP sheet bodies

`import_geometry` of a STEP that contains only faces (no solids): mesh those faces as a shell, thickness from the
user. Faces are pressure-loadable; free CAD edges become named edges `e1`, `e2`, ... with their length and centroid
in the descriptors. Skip if time is short; say so in the report.

## 7. Report

Write `reviews/v0.8_shells_report.md`: files changed, test results, template results vs references (with mesh
sizes and times), what was left out and why. Commit on branch `v0.8-shells` with author `NovaSolver
<info@novasolver.jp>` and the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
