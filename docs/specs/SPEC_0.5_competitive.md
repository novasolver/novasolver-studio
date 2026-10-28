# SPEC — Studio 0.5: the analyses and outputs people expect from a commercial tool

Owner: Claude (spec, acceptance). Implementer: Codex. Branch `v0.5` (git worktree `..\studio_05`).

**Why.** The 2026-10-28 review against SolidWorks/Fusion Simulation, Ansys Discovery and SimScale found that Studio
verifies answers better than they do, but cannot yet do several everyday things:

- natural frequencies
- thermal stress
- self-weight and rotation
- a torque or a bearing load on a hole
- a report or a file for ParaView
- a section view

The operator asked to close these gaps regardless of effort. Studio's rule stays: **every new analysis ships with a
template whose answer is known in closed form, and with a mesh-study quantity.**

## 0. Ground rules

Same as `SPEC_0.4_faces_undo.md` §0: worktree only, match the code, i18n ja/en/zh with identical keys, studio-ui
skill for visuals, no new runtime dependencies, old cases keep opening, full suite plus the new tests pass,
`npm run build` passes, and the same commit and test-environment rules.

Reuse the structure of the electric work (`SPEC_em_0.3.md`): a coupled thermal sub-condition per face
(`boundaries.<f>.thermal`) already exists for Joule heating. Thermal stress reuses that pattern.

## 1. Modal analysis (natural frequencies and mode shapes)

- **Case setting.** `physics.analysis = "modal"` for structural cases (templates and imports); `physics.modes`
  (default 6, 1–30).
- **Roles.** Fixed, symmetry and constraint as in static. Loads are ignored, and the GUI says so (a load face shows a
  note). No supports at all is allowed (free-free): skip the 6 rigid-body modes, i.e. report only frequencies above
  1e-3 of the first elastic one, and say so.
- **Solver.** Consistent tet10 mass matrix from `rho` (per element / per body like E).
  - Generalised eigenproblem K φ = ω² M φ.
  - Up to about 300k dofs: shift-invert `scipy.sparse.linalg.eigsh(K, M=M, k, sigma=σ)` with a direct factorisation.
    σ is a small negative shift, so that free-free works.
  - Above that: `scipy.sparse.linalg.lobpcg` preconditioned with the existing pyamg hierarchy.
  - Check memory with `fem_tet10.check_memory` (extend the estimate).
- **Results.**
  - A table of the modes: f [Hz], and the effective mass fraction in x/y/z when cheap (M-orthonormal φ:
    Γ = φᵀ M r, effective mass = Γ²).
  - The mode shape of the selected mode as a displacement field, normalised to max |u| = 1.
  - In the viewer, an animation toggle (sin(ωt) scaling, deformation scale slider shared with static).
- **Study.** The mesh-study quantity is f₁.
- **Template `cantilever-modal`.**
  - Steel, L = 200 mm, b = h = 10 mm, one end fixed.
  - Reference Euler–Bernoulli: f_n = (β_n² / 2π) √(EI/(ρAL⁴)), with β₁L = 1.8751 and β₂L = 4.6941, giving f₁ = 206.4 Hz and f₂ = 1293 Hz. The first two
    bending modes are degenerate pairs for a square section: compare f₁ to the lowest frequency and f₂ to the third.
  - Tolerance 2 % (the beam is slender enough for shear and rotary inertia to stay under that). The reference card
    must say "Euler–Bernoulli beam".
- **MCP.**
  - `get_results` lists the modes. `render_view(quantity="mode", mode=n)` renders mode n.
  - The `update_case` docs mention `physics.analysis` and `physics.modes`.
- **CalculiX final run.** `*FREQUENCY` step with the same BCs. Compare f₁ with the built-in solver in a test when
  CalculiX is present.

## 2. Thermal stress

- **Material.** `alpha` [1/K] (thermal expansion), in presets:
  - steel 12e-6, aluminium 23e-6, titanium 8.6e-6, copper 17e-6, alloy_steel 12e-6, pla 68e-6, petg 60e-6,
    abs 90e-6, concrete 10e-6, glass 9e-6, fr4 14e-6, silicon 2.6e-6, wood 5e-6, insulation 0
  - plus `body_props.<b>.alpha`; validate ≥ 0
  - `T_ref` [°C] (stress-free temperature, default 20 °C)
- **Two ways to set the temperature** (`physics.thermal_load`):
  - `uniform`: one temperature [°C] for the whole part.
  - `solve`: a steady thermal solve on the same mesh first, with each face's thermal sub-condition
    (`boundaries.<f>.thermal`, exactly like Joule heating), then the structural solve with that field.
- **Solver.**
  - Initial strain ε₀ = α (T − T_ref) I at the Gauss points.
  - Equivalent nodal forces f = ∫ Bᵀ D ε₀ dV.
  - Stresses σ = D (B u − ε₀).
  - Reactions must balance (imbalance check as in static).
- **Results.** Temperature (when solved), displacement, von Mises, and the existing peak-stress and singularity notes.
- **Templates with references.**
  - `thermal-bar-fixed`. A steel bar 100×10×10 mm, both ends fixed axially, lateral faces free, ΔT = +100 K.
    - |σ_x| = EαΔT = 246 MPa in the middle third.
    - Lateral expansion must not be blocked: use roller supports on the ends so that only u_x is constrained.
  - `thermal-bar-free`. The same bar, one end on rollers, ΔT = +100 K.
    - Elongation δ = αΔT L = 0.12 mm.
    - Stress ≈ 0, reported as max |σ| below 1 % of EαΔT.
- **Study.** Max displacement.
- **Readiness check.** `alpha = 0` everywhere with a temperature load gives a warning ("no thermal expansion").

## 3. Body loads: gravity and rotation

- **Settings.**
  - `physics.gravity = {"enabled", "g": {"value": 9.81, "unit": "m/s2"}, "direction": "-z"}`: directions ±x/±y/±z
    or a vector.
  - `physics.rotation = {"enabled", "rpm", "axis": "z", "axis_point": [0, 0, 0] mm}`: centrifugal body force
    ρω²r, with r the distance from the axis. No Coriolis term: static.
- **Combination.** Both combine with surface loads and with the thermal load.
- **Templates with references.**
  - `hanging-bar`. Steel 1000×20×20 mm hanging from its top face under gravity.
    - Top stress σ = ρgL = 77.0 kPa.
    - Tip displacement δ = ρgL²/(2E) = 1.88e-7 m.
  - `rotating-disk`. Solid steel disk R = 100 mm, t = 5 mm, 10,000 rpm.
    - Plane stress, centre σ_r = σ_θ = (3+ν)/8 · ρω²R² = 35.5 MPa (ν = 0.3, ω = 1047.2 rad/s).
    - Constraint: a single point on the axis, fixed through symmetry planes. Make it a quarter model with two
      symmetry planes plus a z-constraint on the mid-plane, so that no artificial stress appears.
    - Tolerance 2 %.
- **MCP.** `update_case` paths are documented in the tool descriptions.

## 4. Torque, remote force and bearing load on faces

- **`moment` role** on a face: torque vector T (N·m) about an axis through the face centroid, or a given point.
  - Apply it as tractions linear in the distance from the axis, t = (T × r)/J_face, with J_face the polar moment of
    the face area about that axis.
  - The resultant force is zero, and the resultant moment equals T to 1e-6.
- **`bearing` role** on a cylindrical face: radial force F (N, a direction ⊥ axis).
  - Distribute it as p(θ) = p₀ cos θ on the half facing F, zero on the other half.
  - The resultant equals F to 1e-6.
  - Needs the cylinder axis from the 0.4 descriptors. Refuse a non-cylindrical face, or an old case without axis
    data, with a clear message.
- **`remote-force` role.** Force F at a point P, transferred to the face as uniform traction F/A plus the moment
  (P − c) × F distributed as for `moment`.
- **Template `shaft-torsion`.** Steel shaft d = 20 mm, L = 200 mm, one end fixed, a 100 N·m torque on the other end.
  - τ_max = 16T/(πd³) = 63.7 MPa, checked as von Mises/√3 at the surface in the middle third.
  - Twist φ = TL/(GJ) = 0.0161 rad (G = E/2(1+ν) = 78.8 GPa, J = πd⁴/32), from the rotation of surface points.
  - Tolerance 2 %.
- **Verification tests** for `bearing` and `remote-force`: force and moment balance of the reactions.
- **GUI.** Value fields with units and a direction picker, matching the existing load role. Draw arrows for the
  moment (curved) and the bearing load (distribution glyphs) using the viewer's existing load-arrow code.

## 5. Results views

- **Section view.**
  - A clipping plane through the result (x/y/z normal or the camera direction, with a position slider) in the results step.
  - The cut face is coloured by the field: draw the cap with a stencil, or compute it from the tet mesh. Pick what
    stays under the Intel HD 630 budget in `studio-ui`.
  - Probing on the cut face works.
- **Deformed shape.** Deformation scale (auto / ×1 / custom) for structural results, already partly present; and the
  mode animation of §1.
- **Line plot.** The existing probe line, in a small chart panel with CSV download.

## 6. Export and report

- **`export_results(case_id, format)`.** Command, API and MCP tool (tool 24).
  - `vtu`: a VTK XML unstructured grid with the tet10 mesh (`VTK_QUADRATIC_TETRA`) and every result field. It must
    open in ParaView; validate the XML structure in a test and read it back with `meshio`, which is installed.
  - `csv`: nodal fields; for modal, the frequency table.
  - `report`: one self-contained HTML file, printable to PDF from the browser. It contains:
    - title and date (no personal names)
    - the geometry picture from `render_view(quantity="faces")` and the boundary-condition table with face labels
    - materials and mesh statistics
    - the result cards and a field picture
    - the verification gates (ran, converged, verified) with the reference or GCI and what they mean
    - the Studio version
  - Files go to `workspace/<case>/exports/`; the tool returns the path. The GUI has an "Export" menu in the results
    step (VTU / CSV / report) that downloads the file.

## 7. Tests (`backend/tests/test_v05.py`; each must fail if the feature is broken)

1. Cantilever modal f₁ and f₂ within 2 %. Free-free reports no rigid modes. M-orthonormality of the returned modes
   to 1e-8.
2. Fixed bar thermal stress within 2 %, free bar elongation within 1 % with near-zero stress. The coupled `solve`
   mode on a bar with 0 °C and 100 °C ends matches the linear temperature field (to 1e-6) and its free expansion
   (mean ΔT).
3. Hanging bar stress and tip displacement within 2 %. Rotating disk centre stress within 2 %.
4. Shaft torsion τ and φ within 2 %. For `moment`, `bearing` and `remote-force`, the resultant force/moment equals
   the input to 1e-6, and the reactions balance.
5. `export_results`: VTU read back by meshio with the right point and cell counts and field names. CSV header and
   row count. The report HTML contains the gates, the reference and an embedded PNG, and contains no absolute path
   of the user's home.
6. Every new template appears in `list_templates` in three languages, and its verification card passes on the
   default preview mesh.
7. The MCP tool count is 24. Update the existing assertion.

## 8. Report back

`reviews/v0.5_codex_report.md`, as in previous specs: what was done per section, test counts and time, what is
not done, guesses, commits.
