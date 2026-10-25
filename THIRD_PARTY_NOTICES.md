# Third-party software

NovaSolver Studio is licensed under the GNU General Public License v3.0 (see `LICENSE`).
It calls the following programs as separate processes and uses the following libraries.

## Solvers and meshers (separate programs)

| Software | License | Source |
|---|---|---|
| OpenFOAM® v2606 (ESI / OpenCFD, Windows MinGW build) | GPL-3.0 | https://www.openfoam.com/ — source: https://sourceforge.net/projects/openfoam/files/v2606/ |
| CalculiX 2.23 (ccx) | GPL-2.0 | http://www.dhondt.de/ — source: http://www.dhondt.de/ccx_2.23.src.tar.bz2 |
| Gmsh 4.15 | GPL-2.0-or-later (with exceptions) | https://gmsh.info/ — source: https://gitlab.onelab.info/gmsh/gmsh |
| Microsoft MPI 10.1 runtime (msmpi.dll, conda-forge build) | MIT | https://github.com/microsoft/Microsoft-MPI |

### OpenFOAM trademark notice

This offering is not approved or endorsed by OpenCFD Limited, producer and distributor of the OpenFOAM software
via www.openfoam.com, and owner of the OPENFOAM® and OpenCFD® trade marks.

## Python libraries

| Library | License |
|---|---|
| NumPy, SciPy | BSD-3-Clause |
| Matplotlib | Matplotlib License (PSF-based) |
| FastAPI, Starlette, Uvicorn, Pydantic | MIT / BSD-3-Clause |
| MCP Python SDK | MIT |
| PyAMG | MIT |
| psutil | BSD-3-Clause |
| meshio | MIT |
| zstandard | BSD-3-Clause |
| gmsh (Python API, used only inside the separate mesh worker process) | GPL-2.0-or-later |

## Front-end libraries

| Library | License |
|---|---|
| React, React DOM | MIT |
| three.js | MIT |
| Tailwind CSS | MIT |
| lucide-react | ISC |
| Vite | MIT |
| Fontsource fonts: Inter, Noto Sans JP, Noto Sans SC | SIL Open Font License 1.1 |

## Reference data used for verification

- Ghia, Ghia & Shin (1982), J. Comput. Phys. 48, 387–411 — lid-driven cavity centre-line velocities (Re = 100).
- Schiller & Naumann (1933) drag correlation for a sphere.
- Heywood stress-concentration formula for a plate with a central hole.
- Classical beam theory (Euler–Bernoulli with Timoshenko shear correction), 1D fin theory, Fourier's law, Poiseuille flow.
