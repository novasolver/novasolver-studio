# NovaSolver Studio validation manual — 0.7.1

This document records how accurately Studio 0.7.1 solves problems with known answers. Anyone can re-run every problem with `validation/suite.py`. The numbers were produced on 2026-11-01 on the machine below; none were typed in by hand.

Machine: Windows-10-10.0.19045-SP0, Python 3.12.3, 8 CPU

## Summary

43 of 43 problems are within tolerance (failed 0, errors 0, no reference 0).

'Mesh-converged' means Studio itself checked that the answer does not change between a coarse, a normal and a fine mesh (GCI). 'One mesh' means only one level was solved, for memory or run time.

## Structural

| Problem | What it tests | Quantity | Studio | Reference | Error | Tolerance | Result | Mesh |
|---|---|---|---|---|---|---|---|---|
| Cantilever beam | A square bar fixed at one end with a load at the tip. Finds deflection and stress and compares them automatically with beam theory. | Tip deflection (beam theory with shear correction) | 0.9762 mm | 0.9831 mm | -0.70 % | ±3 % | pass | converged |
| Plate with a hole in tension | Pulls a plate with a central hole and compares the stress concentration at the hole edge with Heywood's formula. | Stress concentration Kt (Heywood) | 2.541 - | 2.512 - | +1.16 % | ±5 % | pass | converged |
| Cantilever natural frequencies | Steel beam modes compared with the Euler–Bernoulli beam solution. | Steel beam modes compared with the Euler–Bernoulli beam solution. | 206.5 Hz | 206.4 Hz | +0.04 % | ±2 % | pass | converged |
| Column buckling (fixed-free) | A slender square column with a compressive tip load; the critical load is compared with Euler's formula. | Euler critical load, fixed-free column. | 2638 N | 2634 N | +0.12 % | ±2 % | pass | converged |
| Column buckling (both ends clamped) | A square column clamped at both ends and shortened axially; the critical load is compared with Euler's formula. | Euler critical load, column clamped at both ends. | 4.196e+04 N | 4.215e+04 N | -0.46 % | ±2 % | pass | converged |
| Fatigue of a bar (Goodman) | A bar pulled repeatedly between 0 and 15 kN; the fatigue safety factor is compared with Goodman. | Goodman diagram n = 1/(σa/Se + σm/Su). | 1.778 - | 1.778 - | -0.00 % | ±1 % | pass | converged |
| Restrained heated bar | Axial restraint at both ends; compare thermal stress with EαΔT. | Axial restraint at both ends; compare thermal stress with EαΔT. | 246 MPa | 246 MPa | +0.00 % | ±2 % | pass | converged |
| Free thermal expansion | Allow lateral expansion and compare elongation with αΔTL. | Allow lateral expansion and compare elongation with αΔTL. | 0.12 mm | 0.12 mm | -0.00 % | ±1 % | pass | converged |
| Hanging bar under gravity | Verify self-weight stress and displacement against the one-dimensional solution. | Verify self-weight stress and displacement against the one-dimensional solution. | 1.878e-04 mm | 1.878e-04 mm | -0.00 % | ±2 % | pass | converged |
| Rotating disk | Quarter disk with half thickness; compare centre stress with the plane-stress solution. | Quarter disk with half thickness; compare centre stress with the plane-stress solution. | 35.54 MPa | 35.51 MPa | +0.07 % | ±2 % | pass | converged |
| Shaft torsion | Verify shear stress and twist of a steel shaft under torque. | Verify shear stress and twist of a steel shaft under torque. | 0.01615 rad | 0.01615 rad | +0.00 % | ±2 % | pass | not converged |
| Large cantilever | Inextensible Euler elastica, PL²/EI = 1; compare with the linear answer. The beam clamp permits lateral strain. | Inextensible Euler elastica, PL²/EI = 1; compare with the linear answer. The beam clamp permits lateral strain. | 60.22 mm | 60.34 mm | -0.20 % | ±2 % | pass | one mesh |
| Plastic bar | Uniaxial bilinear hardening: load to 1%, unload through zero force, then return to zero displacement. | Uniaxial bilinear hardening: load to 1%, unload through zero force, then return to zero displacement. | 268 MPa | 268 MPa | -0.00 % | ±1 % | pass | converged |
| Plastic beam collapse | Perfectly plastic rectangular cantilever; P = σy b h²/(4L), neglecting shear. A limit run ends without convergence. The beam clamp permits lateral strain. | Perfectly plastic rectangular cantilever; P = σy b h²/(4L), neglecting shear. A limit run ends without convergence. The beam clamp permits lateral strain. | 1280 N | 1250 N | +2.44 % | ±3 % | pass | one mesh |
| Rubber tension | Homogeneous compressible neo-Hookean tension, λ = 2 and zero lateral stress. | Homogeneous compressible neo-Hookean tension, λ = 2 and zero lateral stress. | 29.54 MPa | 29.54 MPa | +0.00 % | ±2 % | pass | converged |
| Press fit | Lamé thick cylinders, plane stress. Contact pressure and ring hoop stress. | Lamé thick cylinders, plane stress. Contact pressure and ring hoop stress. | 76.92 MPa | 76.88 MPa | +0.06 % | ±2 % | pass | converged |
| Stacked blocks | Uniform compression of two touching cubes; frictionless contact. | Uniform compression of two touching cubes; frictionless contact. | 4000 N | 4000 N | -0.00 % | ±0.5 % | pass | converged |
| Friction block | Coulomb stick/slip under normal pressure and shear, with a soft spring. This patch uses Poisson ratio 0. | Coulomb stick/slip under normal pressure and shear, with a soft spring. This patch uses Poisson ratio 0. | 400 N | 400 N | -0.00 % | ±1 % | pass | converged |
| Two blocks with a gap (contact) | Two blocks 0.05 mm apart are pressed together. They are meshed differently, and the contact force after the gap closes is compared with a hand calculation. | Uniform compression of two blocks in series: F = E (d − g) A / (2h). | 1.025e+05 N | 1.025e+05 N | -0.00 % | ±0.5 % | pass | converged |
| Tying separately meshed parts | Two blocks that share no nodes are bonded (tied) and pulled; the answer must equal that of one bar. | Uniform tension of one bar: F = E d A / (2h). | 1.025e+05 N | 1.025e+05 N | -0.00 % | ±0.5 % | pass | converged |
| NAFEMS LE1 elliptic membrane | curved boundary, symmetry planes, outward pressure | σyy at D | 92.8 MPa | 92.7 MPa | +0.11 % | ±2 % | pass | converged |
| NAFEMS LE10 thick plate | 3D bending, component supports, symmetry planes | σyy at D | -5.364 MPa | -5.38 MPa | -0.29 % | ±2 % | pass | one mesh |
| Closed thick cylinder under pressure (Lamé) | pressure on curved faces, curved quadratic elements, 1/8 symmetry | hoop stress, mid wall | 20 MPa | 19.99 MPa | +0.01 % | ±1 % | pass | not converged |
|  |  | axial stress, mid wall | 9.756 MPa | 9.756 MPa | +0.00 % | ±1 % | pass |  |
| Curved beam (Winkler–Bach) | combined bending and tension, curvature shifts the stress | inner fibre | 90.6 MPa | 89.41 MPa | +1.33 % | ±2 % | pass | converged |
|  |  | outer fibre | -51.92 MPa | -52.2 MPa | -0.54 % | ±2 % | pass |  |
| Steel and aluminium bar in series | per-part materials, component supports, bonded interface | tip displacement | 0.1934 mm | 0.1937 mm | -0.17 % | ±1 % | pass | converged |
| Thick sphere under internal pressure | three symmetry planes, pressure on a curved inner face | inner displacement | 0.00195 mm | 0.001951 mm | -0.07 % | ±1 % | pass | converged |
|  |  | hoop stress at the bore | 7.136 MPa | 7.143 MPa | -0.10 % | ±3 % | pass |  |
| Cylinder on a flat (Hertz contact) | A steel cylinder pressed onto a steel block; peak contact pressure and contact width are compared with Hertz (plane strain, quarter model). | Hertz line contact p0 = √(P E*/(πR)) and the contact half-width a. | 1407 MPa | 1408 MPa | -0.09 % | ±5 % | pass | converged |

## Heat transfer

| Problem | What it tests | Quantity | Studio | Reference | Error | Tolerance | Result | Mesh |
|---|---|---|---|---|---|---|---|---|
| Heat conduction block | Heat flowing through a block whose two ends are held at fixed temperatures. Compared automatically with Fourier's law (Q = kAΔT/L). | Heat flow through the block (Fourier's law) | 40 W | 40 W | +0.00 % | ±2 % | pass | converged |
| Cooling fin | A pin fin heated at its base and cooled by the surrounding air. The heat leaving the base is compared with the analytic fin solution. | Heat through the fin base (fin theory) | 5.064 W | 5.066 W | -0.05 % | ±2 % | pass | converged |
| NAFEMS T4 2D conduction with convection | fixed temperature with convection | T at E | 18.25 °C | 18.3 °C | -0.28 % | ±1 % | pass | converged |
| ISO 10211 Annex A, case 1 | thermal-bridge software validation (tolerance 0.1 K) | largest deviation of 28 points (at x 1 m, y 7 m) | 9.657 °C | 9.658 °C | -0.000693 °C | ±0.1 °C | pass | not converged |
| ISO 10211 Annex A, case 2 (four materials) | several materials, a thin aluminium profile, surface resistances | T at A | 7.065 °C | 7.1 °C | -0.035 °C | ±0.1 °C | pass | one mesh |
|  |  | T at B | 0.7613 °C | 0.8 °C | -0.0387 °C | ±0.1 °C | pass |  |
|  |  | T at C | 7.898 °C | 7.9 °C | -0.00191 °C | ±0.1 °C | pass |  |
|  |  | T at D | 6.272 °C | 6.3 °C | -0.0279 °C | ±0.1 °C | pass |  |
|  |  | T at E | 0.8275 °C | 0.8 °C | +0.0275 °C | ±0.1 °C | pass |  |
|  |  | T at F | 16.41 °C | 16.4 °C | +0.00842 °C | ±0.1 °C | pass |  |
|  |  | T at G | 16.33 °C | 16.3 °C | +0.0343 °C | ±0.1 °C | pass |  |
|  |  | T at H | 16.77 °C | 16.8 °C | -0.0329 °C | ±0.1 °C | pass |  |
|  |  | T at I | 18.33 °C | 18.3 °C | +0.0336 °C | ±0.1 °C | pass |  |
|  |  | heat flow | 9.492 W/m | 9.5 W/m | -0.00779 W/m | ±0.1 W/m | pass |  |
| Three-layer wall | per-part conductivity, temperature continuity at interfaces | T, first interface | 19.85 °C | 19.85 °C | -1.82e-12 °C | ±0.05 °C | pass | converged |
|  |  | T, second interface | 0.7634 °C | 0.7634 °C | -4.39e-12 °C | ±0.05 °C | pass |  |
|  |  | heat flow | 0.1527 W | 0.1527 W | +0.00 % | ±1 % | pass |  |
| Radial conduction through a tube | temperatures on curved faces, logarithmic profile | T at r = 15 mm | 53.21 °C | 53.2 °C | +0.00481 °C | ±0.05 °C | pass | converged |
|  |  | heat flow | 1813 W | 1813 W | +0.00 % | ±1 % | pass |  |

## Electric

| Problem | What it tests | Quantity | Studio | Reference | Error | Tolerance | Result | Mesh |
|---|---|---|---|---|---|---|---|---|
| Parallel-plate capacitor | Finds potential and capacitance between plates; checked against C = εA/d. | Capacitance (parallel-plate solution) | 23.24 pF | 23.24 pF | -0.00 % | ±1 % | pass | converged |
| Coaxial cable | Finds coaxial capacitance and electric field; compared with the cylindrical analytic solution. | Capacitance (coaxial solution) | 0.9326 pF | 0.9326 pF | +0.00 % | ±1 % | pass | converged |
| Busbar Joule heating | Finds current and temperature rise in a copper bar; checked against resistance and conduction formulas. | Temperature rise (bar with cooled ends) | 7.641 K | 7.641 K | -0.00 % | ±1 % | pass | converged |

## Flow

| Problem | What it tests | Quantity | Studio | Reference | Error | Tolerance | Result | Mesh |
|---|---|---|---|---|---|---|---|---|
| Lid-driven cavity | Flow inside a square box whose lid slides. The classic CFD benchmark, compared with Ghia et al. reference data (Re = 100). | Mean error of centreline u (Ghia et al. 1982, Re = 100) | -0.2134 m/s | -0.2109 m/s | +0.15 % | ±3 % | pass | converged |
| Flow between parallel plates | Laminar flow between two plates. Checks that the developed velocity profile becomes a parabola (Poiseuille flow). | Outlet centre velocity (Poiseuille u_max = 1.5 U) | 0.01497 m/s | 0.015 m/s | -0.23 % | ±2 % | pass | one mesh |

## Flow

| Problem | What it tests | Quantity | Studio | Reference | Error | Tolerance | Result | Mesh |
|---|---|---|---|---|---|---|---|---|
| Laminar pipe flow (Hagen–Poiseuille) | wall friction and pressure gradient in internal flow | pressure gradient, developed flow | 5.115 Pa/m | 5.11 Pa/m | +0.10 % | ±2 % | pass | converged |
| Sudden expansion loss (Borda–Carnot) | turbulence, separation and reattachment, wall layers | loss coefficient K | 0.5592 - | 0.5625 - | -0.59 % | ±5 % | pass | one mesh |
| Turbulent pipe friction (Blasius) | turbulent wall friction (wall functions, wall layers) | pressure gradient, developed flow | 5541 Pa/m | 5304 Pa/m | +4.48 % | ±10 % | pass | one mesh |

## External flow

| Problem | What it tests | Quantity | Studio | Reference | Error | Tolerance | Result | Mesh |
|---|---|---|---|---|---|---|---|---|
| Flow past a sphere (drag) | Finds the drag coefficient of a sphere in uniform flow and compares it with the Schiller-Naumann correlation (Re = 100). The standard external-flow benchmark. | Drag coefficient (Schiller-Naumann) | 1.1 - | 1.092 - | +0.79 % | ±8 % | pass | converged |

## Known limits

- Turbulent wall friction (pipe friction factor) depends strongly on the mesh next to the wall. Check the Blasius row before relying on it.
- Stress at the corner of a fixed face or a sharp re-entrant corner is infinite in theory (a singularity). Studio warns and does not use it for comparison.
- NAFEMS LE10 on the fine mesh needs more than 16 GB, so its value comes from the normal mesh only.
- Contact, buckling and fatigue are checked by the basic problems in the tables (blocks in series, Hertz contact, Euler buckling, Goodman). Explicit crash and shell elements are not part of this version's validation.

## Sources

- **Busbar Joule heating**: Temperature rise (bar with cooled ends)
- **Cantilever beam**: Tip deflection (beam theory with shear correction)
- **Cantilever natural frequencies**: Steel beam modes compared with the Euler–Bernoulli beam solution.
- **Closed thick cylinder under pressure (Lamé)**: Lamé solution, e.g. Timoshenko & Goodier, Theory of Elasticity, §28
- **Coaxial cable**: Capacitance (coaxial solution)
- **Column buckling (both ends clamped)**: Euler critical load, column clamped at both ends.
- **Column buckling (fixed-free)**: Euler critical load, fixed-free column.
- **Cooling fin**: Heat through the fin base (fin theory)
- **Curved beam (Winkler–Bach)**: Winkler–Bach curved-beam formula, e.g. Roark's Formulas for Stress and Strain, 8th ed., §9.1
- **Cylinder on a flat (Hertz contact)**: Hertz line contact p0 = √(P E*/(πR)) and the contact half-width a.
- **Fatigue of a bar (Goodman)**: Goodman diagram n = 1/(σa/Se + σm/Su).
- **Flow between parallel plates**: Outlet centre velocity (Poiseuille u_max = 1.5 U)
- **Flow past a sphere (drag)**: Drag coefficient (Schiller-Naumann)
- **Free thermal expansion**: Allow lateral expansion and compare elongation with αΔTL.
- **Friction block**: Coulomb stick/slip under normal pressure and shear, with a soft spring. This patch uses Poisson ratio 0.
- **Hanging bar under gravity**: Verify self-weight stress and displacement against the one-dimensional solution.
- **Heat conduction block**: Heat flow through the block (Fourier's law)
- **ISO 10211 Annex A, case 1**: ISO 10211:2017 Annex A, case 1 (28 grid points; exact series solution)
- **ISO 10211 Annex A, case 2 (four materials)**: ISO 10211:2017 Annex A, case 2: nine temperatures (±0.1 K) and 9.5 W/m (±0.1 W/m)
- **Laminar pipe flow (Hagen–Poiseuille)**: Hagen–Poiseuille: dp/dx = 32 μ U / d²
- **Large cantilever**: Inextensible Euler elastica, PL²/EI = 1; compare with the linear answer. The beam clamp permits lateral strain.
- **Lid-driven cavity**: Mean error of centreline u (Ghia et al. 1982, Re = 100)
- **NAFEMS LE1 elliptic membrane**: NAFEMS, The Standard NAFEMS Benchmarks, TNSB Rev. 3 (1990), LE1: σyy at D = 92.7 MPa
- **NAFEMS LE10 thick plate**: NAFEMS TNSB Rev. 3, LE10: σyy at D = −5.38 MPa
- **NAFEMS T4 2D conduction with convection**: NAFEMS TNSB Rev. 3, T4: T at E = 18.3 °C
- **Parallel-plate capacitor**: Capacitance (parallel-plate solution)
- **Plastic bar**: Uniaxial bilinear hardening: load to 1%, unload through zero force, then return to zero displacement.
- **Plastic beam collapse**: Perfectly plastic rectangular cantilever; P = σy b h²/(4L), neglecting shear. A limit run ends without convergence. The beam clamp permits lateral strain.
- **Plate with a hole in tension**: Stress concentration Kt (Heywood)
- **Press fit**: Lamé thick cylinders, plane stress. Contact pressure and ring hoop stress.
- **Radial conduction through a tube**: Hand calculation: Q = 2πkLΔT / ln(b/a)
- **Restrained heated bar**: Axial restraint at both ends; compare thermal stress with EαΔT.
- **Rotating disk**: Quarter disk with half thickness; compare centre stress with the plane-stress solution.
- **Rubber tension**: Homogeneous compressible neo-Hookean tension, λ = 2 and zero lateral stress.
- **Shaft torsion**: Verify shear stress and twist of a steel shaft under torque.
- **Stacked blocks**: Uniform compression of two touching cubes; frictionless contact.
- **Steel and aluminium bar in series**: Hand calculation: u = F/A (L1/E1 + L2/E2)
- **Sudden expansion loss (Borda–Carnot)**: Borda–Carnot: K = (1 − A1/A2)² = 0.5625; turbulent, Re 10,000, k-ω SST
- **Thick sphere under internal pressure**: Lamé solution for a thick sphere, Timoshenko & Goodier §141
- **Three-layer wall**: Hand calculation: series thermal resistances
- **Turbulent pipe friction (Blasius)**: Blasius: f = 0.316 Re^−0.25 (Re 20,000), dp/dx = f/d · ρU²/2
- **Two blocks with a gap (contact)**: Uniform compression of two blocks in series: F = E (d − g) A / (2h).
- **Tying separately meshed parts**: Uniform tension of one bar: F = E d A / (2h).

## How to reproduce

With the Windows zip or `pip install novasolver-studio`, clone the repository and run:

```
python validation/suite.py
python validation/report.py validation/results/<version>.json
```
