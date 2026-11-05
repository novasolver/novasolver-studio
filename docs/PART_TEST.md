# Part test: 0.7.6

Can Studio take a part it has never seen from import to a solved result? 246 STEP files that were not made for Studio went through `validation/corpus.py`: import, one end of the longest axis fixed, 1,000 N on the other end, automatic mesh at the coarse level, solve, and a check that the reactions balance the load. Each file ran in its own process, with a limit of 480 s and 3 files running at a time.

**197 of 246 (80 %) were solved.** Run on 2026-11-06, Windows, 8 CPU threads, 16 GB of memory.

| Result | Parts | Share |
|---|---:|---:|
| Solved, and the reactions balance the 1,000 N load within 1 % | 197 | 80 % |
| Refused with an explanation: a body has no support, or part of the model can move freely | 19 | 8 % |
| Refused with an explanation: the file contains no closed solid | 2 | 1 % |
| Failed: no valid mesh | 15 | 6 % |
| Failed: the solver stopped | 5 | 2 % |
| Failed: over the time limit | 8 | 3 % |

| Source | Parts | Solved |
|---|---:|---:|
| An even sample of the FreeCAD parts library | 220 | 175 |
| STEP test parts of the SolidCraft CAD project | 26 | 22 |

| Solids in the file | Parts | Solved | Refused | Failed |
|---|---:|---:|---:|---:|
| 1 solid | 150 | 144 | 0 | 6 |
| 2 to 5 solids | 43 | 28 | 4 | 11 |
| 6 or more solids | 51 | 25 | 15 | 11 |
| No solid | 2 | 0 | 2 | 0 |

## How to read this

- The 39 parts that failed on the first full run were run again after three more mesher retries were added. The other parts were not, because a part that meshes on an earlier attempt never reaches those retries. One part that ended without a result when the run was paused was also run again. 10 parts went from failed to solved. Some of those use a 0.1 mm tolerance between bodies, and the result then warns about it.
- It tests robustness, not accuracy. The supports and the load are chosen by a script and mean nothing physically, so this says nothing about whether a stress value is right. Accuracy is in [VALIDATION.en.md](VALIDATION.en.md).
- Many files are assemblies of loose parts, with screws, wires and enclosures. A refusal is often the right answer there, because a body that touches nothing cannot be solved under this script's supports.
- Only totals are given. The FreeCAD library's licence is not stated for every file, so the files are not redistributed here.
