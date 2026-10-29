# Contact and nonlinear structures

Interfaces are bonded when `contacts` is absent. Set `contacts.<face>.type` to `frictionless`,
`frictional`, or `no-separation` to allow relative motion. This release supports touching bodies
that share an interface after CAD fragmentation. It does not search for contact between separate surfaces.
Changing contact settings reuses the CAD mesh; the run duplicates interface nodes on the higher-tag body.
Positive offset is interference; negative offset is an initial gap. No-separation permits normal tension.

Contact uses nodal traction unknowns and a semi-smooth Newton projection onto the Coulomb cone.
The active-set scaling is not a physical penalty: converged constraints and forces are checked independently.
Tributary areas use positive dual areas (A/12 at corners, A/4 at midsides for a flat tri6), normalized
by curved surface quadrature. The tri6 surface mass matrix integrates the nodal traction field into
bulk nodal forces. A corner can have positive pressure despite zero consistent corner force; the
Coulomb bound applies to pressure. Its integral equals the interface force. An unsupported rigid body gives
`err.contact_unstable`, rather than a nominally converged displacement.

Select Nonlinear to use incremental total-Lagrangian tet10 mechanics. The default material remains linear
elastic; large deformation uses Green strain and second Piola stress, transformed to Cauchy stress for results.
The small-strain elastoplastic model is J2 with isotropic hardening. `H` is the uniaxial post-yield tangent;
the plastic hardening modulus is `E H/(E-H)`. H = 0 is allowed. Finite-strain plasticity is explicitly refused.
Small-strain J2 uses an element pressure (B-bar volumetric projection) to avoid plastic incompressibility locking.
Neo-Hookean materials require large deformation. They use
`W = mu/2 (I1-3) - mu ln J + lambda/2 (ln J)^2`, with the volumetric logarithm projected to its element mean.
The tangent includes the coupling caused by this selective treatment. The homogeneous uniaxial reference
solves zero lateral stress, rather than assuming incompressibility.

Pressure follows the deformed face, including its changing area, with an analytic load tangent.
Force, moment, bearing, remote force, gravity and rotation remain dead loads in the reference configuration.
Thermal expansion combines with either analysis. Uniform temperatures may be overridden per body through
`physics.thermal_load.body_temperatures` (body key to temperature quantity). Heating a ring expands its bore;
cooling the ring, or heating the shaft, produces a shrink fit. The sign is never reversed to fit a reference.

The `displacement` face role accepts `ux`, `uy`, `uz` as length quantities; null means unconstrained.
The beam benchmarks use an explicit `beam-clamp` role: axial displacement is held over the end section;
transverse translations and torsion are held at neutral-axis points, leaving lateral strain free. This
matches the classical beam reference. A fully fixed 3D face additionally confines plastic flow and raises
the limit load; it is a different support model. Existing `fixed` faces retain their full constraint.
It also works in a static analysis. `physics.nonlinear.path` is an optional sequence of load fractions for
displacement reversal. Every accepted step commits its own plastic and friction history. Failed trial steps
are discarded and the increment is halved, at most eight times. If the target cannot be reached, results
retain the last converged step, report `err.nonlinear_diverged` and leave the converged gate false.
The plastic-bar template includes the zero-force unloading point before returning to zero displacement;
returning an already yielded bar to zero total strain causes reverse yielding, not stress-free unloading.

Results expose the curve, step fields, interface forces and status counts. Steps are one-based; omit `step`
to use the final accepted step. Large-deformation results default to true deformation scale. VTU export writes
one file per step and a PVD collection in the same directory; keep those files together. CSV exports the curve.
A collapse template can pass its limit-load comparison while its converged/verified gates stay false.

CalculiX decks support elastic large deformation, small-strain J2 plasticity and surface-to-surface contact
with an explicitly stated normal stiffness and clearance. Unsupported combinations are refused before launch.
In particular, CalculiX's compressible neo-Hookean energy differs from the built-in logarithmic law, so this
release refuses that final run; it also refuses no-separation contact, spring supports, reversal paths and
combined nonlinear/contact step output.

Constitutive and deck references:

- [FEBio neo-Hookean energy](https://febiosoftware.github.io/febio-docs/features/features/solid_material_neo-hookean/)
- [CalculiX contact pair](https://feacluster.com/CalculiX/ccx_2.18/doc/ccx/node236.html)
- [CalculiX clearance](https://www.feacluster.com/CalculiX/ccx_2.18/doc/ccx/node228.html)
- [CalculiX hyperelastic energy definitions](https://github.com/calculix/cae/blob/master/doc/HYPERELASTIC.html)
