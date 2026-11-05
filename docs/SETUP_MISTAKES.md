# Setup mistakes Studio points out — 0.7.6

We took three correct setups, broke each one in a single way, and recorded what Studio said. **26 of 34 mistakes were pointed out; 8 were not.** The list and the scoring were committed before the first run (`validation/mistakes.py`), and every miss is in the table below.

A mistake counts as pointed out when a message appears that the correct setup does not show in the same step: a value refused where it is typed in, a check before solving, a warning on the result, a failed gate, or a run that stops with an error. The comparison with a textbook answer is never counted, because your own part will not have one. Whether the message names the actual mistake is for you to judge: the table shows which message appeared.

Some mistakes cannot be seen from the model alone: a load pointing the wrong way or the wrong material gives a perfectly valid answer to a different question. Those are misses here, and no checker can catch them without knowing what you meant.

| Group | Pointed out |
|---|---|
| analysis | 5 of 5 |
| loads | 2 of 6 |
| materials | 3 of 5 |
| mesh | 3 of 3 |
| supports | 6 of 6 |
| units | 7 of 9 |

Our own reading: C10, L4 were pointed out only by a general warning about the peak stress (a singularity or a peak on a support). That warning does not say the support or the load is on the wrong face, so a user could easily miss the real cause. Counting those as misses gives 24 of 34.

## Correct setups

- **C**: Steel cantilever 200 x 20 x 20 mm, end fixed, 1000 N down on the free end. Messages on the correct setup: run:peak_on_support, study:peak_on_support.
- **L**: L-bracket (bundled STEP), back face fixed, 200 N down on the end of the other leg. Messages on the correct setup: run:peak_on_support, study:stress_singular, study:gate:mesh.
- **T**: Steel block 100 x 50 x 20 mm, 100 °C and 20 °C on opposite ends. Messages on the correct setup: none.

## Every mistake

| | Mistake | Pointed out | New messages |
|---|---|---|---|
| C1 | Load typed 1000 times too large (1 000 000 N) | yes | `run:large_deformation`, `run:yield`, `study:large_deformation`, `study:yield` |
| C2 | Load typed 1000 times too small (1 N) | **no** | — |
| C3 | Young's modulus in the wrong unit: 205 MPa for steel | yes | `run:large_deformation`, `study:large_deformation` |
| C4 | Young's modulus 1000 times too large: 205 000 GPa | yes | `input:err.range` |
| C5 | Dimensions in metres instead of millimetres (200 m long) | yes | `input:err.range` |
| C6 | Dimensions 1000 times too small (0.2 mm long) | yes | `input:err.range` |
| C7 | No support at all | yes | `error:no_fixed` |
| C8 | No load | yes | `error:no_load` |
| C9 | Load pointing the wrong way (up instead of down) | **no** | — |
| C10 | Support on the wrong face (a side face instead of the end) | yes | `study:stress_singular`, `study:gate:mesh` |
| C11 | Load on the wrong face (the top face instead of the free end) | **no** | — |
| C12 | Under-supported: only a symmetry plane at the end, so the beam can slide | yes | `run:stopped`, `study:stopped` |
| C13 | Wrong material picked (aluminium instead of steel) | **no** | — |
| C14 | Poisson's ratio 0.5 (incompressible) for steel | yes | `input:err.range` |
| C15 | Linear analysis far beyond yield (10 000 N) | yes | `run:yield`, `study:yield` |
| C16 | Linear analysis of a thin strip that bends a lot (2 mm thick, 20 N) | yes | `run:large_deformation`, `run:yield`, `study:stopped` |
| C17 | Coarse mesh | yes | `warn:coarse` |
| C18 | Vibration (modal) analysis with the load still set, expecting it to matter | yes | `warn:modal_loads_ignored` |
| C19 | Beam that is too short for beam theory (40 mm long, 20 mm high) | yes | `warn:slender`, `study:stress_singular` |
| L1 | Load typed 1000 times too large (200 000 N) | yes | `run:large_deformation`, `run:yield`, `study:large_deformation`, `study:yield` |
| L2 | Young's modulus in the wrong unit: 205 MPa for steel | yes | `run:large_deformation`, `study:large_deformation` |
| L3 | No support at all | yes | `error:no_fixed` |
| L4 | Support on the wrong face (bottom of the leg instead of the wall face) | yes | `study:peak_on_support` |
| L5 | Load on the wrong face (the bolt hole instead of the end) | **no** | — |
| L6 | Load pointing the wrong way | **no** | — |
| L7 | Wrong material picked (PLA instead of steel) | yes | `run:large_deformation`, `study:large_deformation` |
| L8 | Coarse mesh | yes | `warn:coarse` |
| L9 | Linear analysis far beyond yield (5000 N) | yes | `run:yield`, `study:yield` |
| T1 | No temperature set anywhere (both ends insulated) | yes | `error:no_temperature`, `warn:no_heat` |
| T2 | The same temperature on both ends | yes | `warn:uniform_temperature`, `run:gate:converged`, `study:gate:converged` |
| T3 | Temperature typed in kelvin instead of °C (100 K on the hot end) | **no** | — |
| T4 | Conductivity 1000 times too large (50 000 W/mK) | yes | `input:err.range` |
| T5 | Wrong material picked (aluminium instead of steel) | **no** | — |
| T6 | Coarse mesh | yes | `warn:coarse` |

Prefixes: `input` refused where typed in; `error`/`warn`/`info` the check before solving; `run` the default solve; `study` the solve with the mesh study. `gate:` a gate that failed.

Re-run: `python validation/mistakes.py` (about an hour on a laptop). Raw results: `validation/results/mistakes-0.7.6.json`.
