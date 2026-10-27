# SPEC — Electromagnetics, first stage (Studio 0.3): electrostatics and DC current with Joule heating

Owner: Claude (spec, acceptance). Implementer: Codex. Branch `em-0.3` (git worktree `..\studio_em`).
Plan context: `docs/EXPANSION_PLAN.md` (stage 1). Same app, new physics family `electric`.

## 0. Ground rules

- Work only inside the worktree. Do not touch `release/`, `workspace/`, `marketing/`, `solvers/`, `.venv`.
- Match the surrounding code: comment density, naming, idioms (short "why" comments, SI inside, units only at the edges).
- Every user-visible string goes through i18n with **identical key sets in ja/en/zh** (backend `backend/novastudio/i18n/*.json`,
  frontend `frontend/src/i18n/*.json`). Japanese and Chinese must read naturally (not literal).
- Keep the existing physics working: the full test suite must still pass (`backend/tests`), plus the new tests in §8.
- No new runtime dependencies. Built-in solver only (numpy / scipy / pyamg already present).
- Run tests with a private lock dir: `$env:LOCALAPPDATA=<temp dir>` (the machine-wide solver lock is shared otherwise),
  python = `E:\03_サイト構築\NovaSolver\studio\.venv\Scripts\python.exe`, `PYTHONPATH=<worktree>\backend`.
- Commit in small logical commits on `em-0.3` with author `NovaSolver <info@novasolver.jp>` and the trailer
  `Co-Authored-By: Codex <noreply@openai.com>`. Do not push.

## 1. Physics and equations

One scalar FEM on tet10, the same kernel as `fem_tet10.solve_thermal` (generalise it, do not copy it):

| analysis (`physics.kind`) | unknown | equation | coefficient per element | natural BC |
|---|---|---|---|---|
| `electrostatic` | V [V] | −∇·(ε∇V) = 0 | ε = ε0 εr, ε0 = 8.8541878128e-12 F/m | D·n = 0 (no field leaves: symmetry plane or ignored fringe) |
| `dc-current` | V [V] | −∇·(σ∇V) = 0 | σ [S/m] | J·n = 0 (insulated surface) |

`dc-current` optionally (`physics.joule_heating`, default true) solves steady conduction afterwards with the volumetric
source q = σ|∇V|² [W/m³]. Evaluate q **at the Gauss points** from the computed V (not from nodal averages) and integrate
it with the tet10 shape functions, so that the total heat equals the electrical power to solver precision.
Add an optional volumetric source to the thermal kernel for this: `source` = per-element-per-Gauss-point values (E,4).

Derived fields (nodal, averaged like stress in `fem_tet10.solve`: Gauss → corners → node average, midsides = edge mean):
E = −∇V [V/m], |E|; for dc-current also |J| = σ|E| [A/m²] and q [W/m³]; T [K] when Joule heating is on.

## 2. Boundary roles

New role lists in `templates.py`:

- `ELECTROSTATIC_ROLES = ["open", "voltage", "surface-charge"]`
  - `voltage`: fixed potential `{"voltage": {"value": 0, "unit": "V"}}` (a grounded or driven electrode)
  - `surface-charge`: `{"charge": {"value": 1e-6, "unit": "C/m2"}}` (positive = into the body, like heat flux)
  - `open` (default): D·n = 0
- `CURRENT_ROLES = ["insulated", "voltage", "current"]`
  - `voltage` as above; `current`: total current into the face `{"current": {"value": 1, "unit": "A"}}`, uniform density
  - `insulated` (default)
- dc-current faces also carry a **thermal condition** for the Joule step, stored as
  `boundaries.<face>.thermal = {"role": <THERMAL_ROLES>, ...fields}` (default `{"role": "insulated"}`), edited through the
  same `update_case` paths (`boundaries.x0.thermal.role`, `boundaries.x0.thermal.temperature`, …). Validate exactly like
  thermal roles. When `joule_heating` is false the thermal part is ignored and hidden in the UI.
- `DEFAULT_ROLE`: `"electric": "open"` for electrostatic, `"insulated"` for dc-current (decide by analysis).
- Add to `ROLE_FIELDS`: `voltage`, `surface-charge`, `current`. Units: add `V`, `kV`, `mV`, `C/m2`, `A`, `mA`, `S/m`,
  `F`, `pF`, `nF`, `uF`, `ohm`, `mohm` to `units.py` (with their dimension checks) where missing.
- A case must have at least one `voltage` face (otherwise V is undetermined): validation error `err.no_voltage` (3 languages),
  raised in `validate_case` like the existing structural checks (`checks.py`).
- `current` faces need a voltage face elsewhere; the solver applies the current as a uniform normal flux.

## 3. Materials

Add electrical properties to every entry of `MATERIALS_SOLID`: `eps_r` (relative permittivity, "-") and `sigma` (S/m).
Use textbook room-temperature values; insulators get σ ≤ 1e-12 S/m, metals: copper 5.96e7, aluminium 3.77e7, steel 6.99e6,
alloy_steel 4.0e6, titanium 2.38e6, silicon (intrinsic) 4.3e-4. Add presets useful for electrics:
`air` (εr 1.0006, k 0.026), `ptfe` (2.1), `alumina` (9.8), `epoxy` (3.6), `water_deionised` (80, σ 5.5e-6) with sensible
E / nu / rho / k so they also work in the other physics (state in a comment where values are nominal).
`BODY_PROPS` gains `eps_r` and `sigma` so multi-body imports can override per body. `solid_props` / `element_prop` serve them.
`store.apply_changes` range checks: `eps_r` finite and ≥ 1; `sigma` finite and > 0.

## 4. Templates (each with an analytic reference, as every template must have)

All three: `"physics": "electric"`, `"engines": ["builtin-fem"]`, mesh gmsh order 2, `fixed_roles` not set (users may edit).

1. `capacitor` — parallel-plate capacitor, `geometry.kind = "box"` (length 50 mm, width 50 mm, height = gap 2 mm),
   material `ptfe`, `physics.kind = electrostatic`; z0 voltage 0 V, z1 voltage 100 V, other faces open.
   Reference `parallel-plate-capacitance`: C = ε0 εr L W / d (exact here: open sides make the field 1D), tolerance 1 %.
   Pattern check: z0/z1 voltage faces, all others open; else `applicable: False` with a reason (like the other references).
   Params: length, width, height (gap), z1 voltage, `materials.solid.eps_r` (1 … 10000).
2. `coax` — coaxial cable, **new geometry kind `tube`**: params inner radius `a` 1 mm, outer radius `b` 3.5 mm, length
   100 mm; faces `inner`, `outer`, `z0`, `z1` (OCC cylinder minus cylinder along z, faces identified by type/bbox, like
   `plate_hole`). Material `ptfe`; inner voltage 1000 V, outer 0 V, ends open.
   Reference `coax-capacitance`: C = 2π ε0 εr L / ln(b/a), tolerance 1 %. Also report max |E| against the analytic
   V / (a ln(b/a)) at the inner conductor in the metrics.
   Mesh sizing for `tube`: element size from the wall thickness (b − a) / DIVS, with the curvature-following settings the
   CAD path already uses (midsides on the true surface).
3. `busbar` — copper bar, box 200 × 20 × 5 mm, `physics.kind = dc-current`, `joule_heating: true`;
   x0 voltage 2 mV, x1 voltage 0 V, sides insulated (electrically); thermal: x0 and x1 `temperature` 20 °C, sides insulated.
   Two analytic results (both reported in the metrics; the reference quantity is the second, which tests the coupling):
   - R = L / (σ W H) → current I = ΔV / R
   - with both ends held at T0 and insulated sides: T_max − T0 = σ ΔV² / (8 k) (independent of L), at mid-length.
   Reference `busbar-joule-rise`, quantity `t_rise`, tolerance 1 %. Pattern check accordingly.
   Params: length, width, height, x0 voltage, `materials.solid.sigma`, `materials.solid.k`.

Imports: `import-electrostatic` and `import-current` (like `import-thermal`), and `PHYSICS` in `commands.py` /
`import_geometry` (HTTP and MCP) accept `electrostatic` and `current`. Multi-body STEP with `body_materials` works
(a two-dielectric capacitor = two stacked boxes: the interface is shared and continuous; nothing special needed).

Template titles/descriptions in 3 languages (short, concrete: what it computes and against what).
`nova_tool` links: pick existing novasolver.jp tool pages if they exist (check `cae-archive/tools/` names for capacitor /
coaxial / joule); otherwise omit.

## 5. Solver and results

`run_worker.py`: engine `builtin-electric` (the router maps `builtin-fem` + physics `electric` to it, like thermal; also in
`run_study`). Results `kind`: `"electrostatic"` or `"current"`.

Metrics (SI in results.json):
- electrostatic: per voltage face its charge `face_charge_c` {face: Q} (the reaction "flow" of the fixed nodes, as
  `solve_thermal` returns heat for fixed faces); `capacitance_f` when exactly two distinct voltages exist
  (C = |Q_high| / ΔV; with more electrodes report the charges only, no capacitance); `energy_j` = ½∫ε|E|² (Gauss
  quadrature); `e_max_v_m` (max nodal |E|) and the location; `imbalance` = |ΣQ| / Σ|Q_in| (charge balance; must be
  < 1e-3 for `converged`, the same rule as heat balance) — careful: with surface-charge faces include them in the sum.
  Check C two ways in a test: from charge and from 2W/ΔV² (must agree to < 0.1 % on the capacitor template).
- current: `face_current_a` {face: I}, `current_a` (into the highest-voltage face), `resistance_ohm` when two voltages,
  `power_w` = ∫σ|E|² (and check equals ΣV_i I_i to < 0.1 %), `j_max_a_m2`, `imbalance` (current balance < 1e-3);
  with Joule heating also `t_max_k`, `t_min_k`, `q_joule_w` (∫q dV) and the thermal heat balance (both must hold for
  `converged`).
- Field store `results.npz`: `V`, `E` (n,3), plus `J` (n,3), `q`, `T` for current.

`results.py`: `QUANTITIES` entries — electrostatic: `("v", "V", "sequential")`, `("emag", "kV/mm", "sequential")`;
current: `("v", "V", "sequential")`, `("jmag", "A/mm2", "sequential")`, `("q", "W/cm3", "sequential")` and
`("temp", "°C", "sequential")` when T exists (first entry of the list = default view: `temp` first when Joule heating is on).
Cards (`payload`): electrostatic → capacitance (pF/nF auto via existing unit formatting), charge, energy, max field;
current → current, resistance (mΩ / Ω), power, max temperature, max current density. Lead figure = the one compared with the
reference (C for capacitor/coax, temperature rise for busbar). Add field-strength **warning** when e_max exceeds 3 kV/mm in an
`air` body (breakdown of air; text explains it is a rule of thumb) — follow how the yield warning is produced.

`probe.py` `_fields`: `v`, `ex/ey/ez`, `emag`, and for current `jmag`, `q`, `temp`. Face statistics give the
charge / current through a face from the solver's own numbers when that face is an electrode (like `face_flux_m3s`).

Mesh convergence study (`primary_quantity`): electrostatic → `capacitance` if available else the largest |face charge|;
current → `t_rise` (T_max − min fixed T) when Joule heating is on, else `resistance` / current.

`verify_case`, gates, `stale` handling, `render_view` PNGs: must work for the new kinds (render uses the first quantity).

## 6. MCP server

`mcp_server.py`: `import_geometry` physics literal gains `electrostatic`, `current`; tool descriptions mention
electrostatics / DC current / Joule heating where they list physics; `describe_case` / `get_results` output readable for the
new kinds (units, n/a for missing). Keep the tool count (21) unless a new tool is unavoidable (it should not be).
Update the MCP server instructions text if it enumerates physics.

## 7. Frontend

Follow `studio/.claude/skills/studio-ui/SKILL.md` (tokens, no hard-coded colours, lucide icons stroke 1.5, sentence case).

- `StartScreen`: a new category **電磁気 / Electromagnetics / 电磁** with the three templates (same card layout as the others;
  physics label and icon: lucide `Zap`). Import dialog (`ImportCad`): physics options 静電場 / 電流・ジュール熱.
- `PropertiesPanel`: role choices per analysis; value inputs for voltage / charge / current with units; for dc-current a
  second compact section "熱の条件 / Thermal condition" under the electrical role (role select + its fields), shown only
  when Joule heating is on; a toggle for `physics.joule_heating` in the physics step. Material step shows εr (electrostatic)
  or σ and k (current) and lists the new presets.
- Results: quantity selector entries and colour bars with the units above; cards from the backend payload (no
  frontend physics). `types.ts` updated. `api/mock.ts`: add the capacitor template so the mock still renders.
- i18n keys in ja/en/zh for everything; key sets identical (check with a small script and say so in the report).
- `npm run build` in `frontend` must pass with zero TypeScript errors.

## 8. Tests (new file `backend/tests/test_electric.py`; each must fail if the feature is broken)

1. capacitor template, preview mesh: C within 0.5 % of ε0 εr A/d; C from charge vs 2W/ΔV² within 0.1 %;
   |E| at the centre (probe) within 0.5 % of ΔV/d; sign: V at mid-gap = 50 V.
2. capacitor with `materials.solid.eps_r = 4` → C exactly 4/2.1 times the ptfe result (± 0.1 %).
3. coax: C within 1 % of 2πε0εrL/ln(b/a); e_max within 3 % of V/(a ln(b/a)).
4. two-dielectric series capacitor (import a two-box STEP generated in the test with gmsh OCC, bodies ptfe and alumina,
   each 1 mm): C within 1 % of the series formula; the potential at the interface (probe) within 1 %.
5. busbar: R within 0.5 %; power = ΣV I within 0.1 %; q_joule = power within 0.5 %; T_max − T0 within 1 % of σΔV²/(8k);
   heat and current balances < 1e-3.
6. a `current` face (1 A into x0, x1 at 0 V): V at x0 ≈ I R within 0.5 %.
7. validation: no voltage face → `err.no_voltage`; εr = 0.5 → refused; σ = −1 → refused.
8. mesh convergence study on the capacitor passes (GCI ≤ 5 %) and tracks `capacitance`.
9. MCP: `import_geometry` accepts the new physics (call the function directly, as other tests do).
10. i18n key sets identical across ja/en/zh (backend and frontend).

## 9. Docs

- `docs/EXPANSION_PLAN.md`: mark stage 1 step 1 (electrostatics + DC/Joule) as implemented in 0.3 (one line).
- Short user-facing section in the repo README (what electrostatics / DC current can do now, the three templates and what
  each is verified against). Keep it brief; no marketing claims beyond the tests.
- `CHANGELOG` / release notes draft `docs/RELEASE_NOTES_v0.3.0_draft.md` (what changed, verification numbers from §8).

## 10. Report back

At the end print: the commits, a table of the §8 tests with the numbers obtained (computed vs reference, error %), the full
suite result, the i18n check result, `npm run build` result, and anything not done or doubtful. Do not claim a test passed
without running it.
