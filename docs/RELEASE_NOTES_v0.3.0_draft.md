# NovaSolver Studio 0.3.0 — draft

Electrostatics and DC current now use the built-in quadratic tetrahedral FEM. The scalar diffusion kernel is shared
with steady heat conduction. Optional Joule heating integrates σ|∇V|² at the four Gauss points and feeds the same
integral into the thermal solve; electrical and thermal balances both determine convergence.

- Editable capacitor, coaxial cable and copper busbar templates, each with an analytic reference.
- Electrode potential, surface charge and total face current; independent thermal conditions for DC/Joule cases.
- STEP/IGES/BREP/STL imports for both analyses, with material presets and per-body electrical overrides.
- Potential, electric field, current density, Joule heating and temperature fields; electrode charge/current probes,
  mesh studies, PNG rendering and MCP access through the existing 21 tools.
- Japanese, English and Chinese UI, including an air-breakdown rule-of-thumb warning above 3 kV/mm.

## Verification

Measurements from `backend/tests/test_electric.py` (SPEC_em_0.3 §8), default preview meshes unless stated otherwise:

| Check | Computed | Reference | Relative error |
|---|---:|---:|---:|
| Parallel-plate capacitance | 23.2422430086 pF | 23.2422430086 pF | < 0.000001% |
| Capacitance from energy, 2W/ΔV² | 23.2422430086 pF | Charge-based capacitance | < 0.000001% |
| Centre field / potential | 49,999.9997318 V/m / 49.9999998059 V | 50,000 V/m / 50 V | < 0.000001% |
| Relative permittivity 4 | 44.270939064 pF | 44.270939064 pF (4/2.1 scaling) | < 0.000001% |
| Coax capacitance | 9.32836405296 pF | 9.32564729003 pF | 0.0291322% |
| Coax peak field | 805,459.041511 V/m | 798,235.600148 V/m | 0.904926% |
| Two dielectric layers (PTFE/alumina) | 1.53125365704 pF | 1.53125365704 pF | < 0.000001% |
| Dielectric interface potential | 82.3529411765 V | 82.3529411765 V | < 0.000001% |
| Busbar resistance | 33.5570469798 µΩ | 33.5570469799 µΩ | < 0.000001% |
| Busbar power / integrated Joule heat | 0.1192 W / 0.1192 W | ΣVᵢIᵢ = 0.1192 W | < 0.000001% |
| Busbar temperature rise | 0.0764102561059 K | 0.0764102564103 K | < 0.000001% |
| Prescribed 1 A, driven-face potential | 33.5570469798 µV | IR = 33.5570469799 µV | < 0.000001% |

The busbar's current imbalance was 3.57×10⁻¹² and heat imbalance 3.78×10⁻⁹ (limit 10⁻³).
Validation also checks the required voltage reference, invalid electrical material values and nested thermal roles.
The imported series capacitor uses a test-generated two-body STEP with a conformal shared interface.

The capacitor mesh study tracked **capacitance**, with 28,734 → 90,210 → 344,219 elements and
**GCI = 2.89255×10⁻¹⁴%** (limit 5%). All three levels converged. The near-zero GCI reflects the exact linear field
of this idealised open-sided parallel-plate model; it does not measure fringe-field modelling error.

The complete `backend/tests` run finished with **53 passed, 3 skipped, 0 failed** in 746.69 s. The skipped tests
require OpenFOAM, which is not installed in this worktree. The two warnings are existing FastAPI startup-event
deprecations. Both MCP import analyses passed, with the tool count unchanged at 21. The ja/en/zh key sets match:
**292 backend keys** and **357 frontend keys**.

## Verification environment and remaining release checks

Tests use the existing Studio Python environment, this worktree's backend on `PYTHONPATH`, and a private
`LOCALAPPDATA=.tmp` solver lock. BLAS/OMP threads are limited to one for the full suite on the shared machine.
No runtime dependencies were added. Scalar matrix assembly is performed in bounded blocks to keep the fine
capacitor mesh within memory.

`npm run build` completed with zero TypeScript errors. The restricted Windows environment cannot create Node's
usual subprocess pipes; an untracked local stdio transport adapter was used for the unchanged esbuild binary.
Dependencies were copied from the supplied shared folder into this worktree to keep Vite's cache writes local.

The studio-ui four-theme screenshot loop remains a release check: the computer-use helper timed out, and headless
Edge exited while creating its Windows IPC channel. PNG result rendering is covered by the solver acceptance tests.
