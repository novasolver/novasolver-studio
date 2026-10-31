# SPEC: Studio 0.9 — mechanism (multibody) analysis

Owner: Claude (spec and acceptance). Implementer: a Claude agent in a separate worktree. Branch `v0.9-mechanisms`,
started from the commit that contains 0.8 (shells).

## Why

Designers of machines want to know how an assembly moves and what forces its joints and parts carry, then check the
parts for strength and fatigue under those forces. Free tools rarely connect the two. Studio already has the strength
and fatigue side; this release adds the motion side and the hand-over between them.

## Solver

Exudyn (University of Innsbruck), Python wheels for Windows/macOS/Linux, `pip install exudyn`.
- Licence: EXUDYN General License 1.0 = BSD-3-Clause wording (checked 2026-10-31 in the 1.13.6 wheel). Compatible
  with Studio's GPL v3; add it, and the third-party licences it lists, to THIRD_PARTY_NOTICES.md.
- Optional dependency (`novasolver-studio[mechanisms]` and bundled in the Windows zip); Studio starts without it and
  says plainly that mechanism analysis needs it.
- Prototype notes (Claude, 2026-10-31, exudyn 1.13.6): `ObjectJointPrismatic2D` needs `MarkerBodyRigid` on both
  sides (MarkerBodyPosition is rejected at Assemble). Driving the crank with a `CoordinateConstraint` on coordinate 2
  of a `NodeRigidBody2D` (offsetUserFunction, or a pre-step function setting `offset`) did not move the system in a
  quick trial: find the supported way to prescribe a joint motion (e.g. `ObjectKinematicTree` with prescribed joint
  coordinates, a `CoordinateSpringDamper` drive, or `ObjectConnectorCoordinate` with a user function) and record it.
  Scratch prototype: not kept; start fresh.

## 1. Case data

New physics kind `mechanism` (template group "Motion"):
- `bodies.<b>`: each body of an imported assembly (STEP with several solids) or of a template; mass properties
  computed from the geometry and material density (volume, centre of mass, inertia tensor about it; use the tet mesh
  or gmsh OCC mass properties). A body can be `ground`.
- `joints.<name>` = `{type: revolute | prismatic | spherical | fixed | planar-revolute?, bodies: [a, b], point_mm,
  axis}`; for imports the point/axis can be picked from a cylindrical face (axis of the face) — offer that as the
  default when two bodies share a cylindrical pin/hole pair.
- `drives.<name>` = `{joint, type: angle | displacement | velocity | torque | force, value or table (t, value)}`.
- `loads`: gravity, constant or tabulated forces/torques on bodies at a point.
- `analysis`: `kinematic` (positions, velocities, accelerations only) or `dynamic` (forces with inertia),
  end time, number of output frames.

## 2. Results

- Animation of the assembly (positions of every body per frame) in the viewer, played like the modal/buckling mode
  animation; body colours as in the boundaries step.
- Time plots: any body's position/velocity/acceleration, any joint's reaction force and moment, drive torque/force.
- Cards: peak joint reaction (and which joint), peak drive torque/force, cycle time.
- "Send to strength analysis": for a chosen body and time (default: the time of its largest joint load), create a
  structural case of that body alone with the joint reactions as bearing/remote-force loads and inertia as body
  forces (d'Alembert), ready to run; the link back to the mechanism case is stored. Fatigue on that case can use the
  min/max of the joint loads over the cycle (ratio R).

## 3. Templates (each with a closed-form reference)

1. `slider-crank`: crank r = 50 mm, rod l = 150 mm, 10 rev/s, 1 kN gas force on the piston, light links.
   Reference: piston position x(θ) = r cos θ + sqrt(l² − r² sin² θ) (tolerance 1e-6 relative) and the drive torque
   T(θ) = F dx/dθ (virtual work, massless links; tolerance 0.5 %).
2. `pendulum`: a steel bar pinned at one end, released from horizontal under gravity. Reference: the period of
   small oscillations 2π sqrt(2L/(3g)) for a start at 5°, and the pin reaction at the bottom of a release from
   horizontal (5/2 m g for a uniform bar). Tolerance 0.5 %.
3. `four-bar`: a Grashof crank-rocker. Reference: the output angle from Freudenstein's equation over a full turn.
   Tolerance 1e-5 rad.

## 4. MCP

New tools: `define_joint`, `define_drive` (or via `update_case` paths `joints.*`, `drives.*` — prefer paths and no new
tools if that stays clear), `get_motion` (time series of a body or joint, decimated), `send_to_structural`.
Update the tool-count tests if tools are added.

## 5. Tests

1. Each template within tolerance; the kinematic and dynamic modes agree on positions.
2. Mass properties of an imported body match gmsh/OCC to 1e-6.
3. A redundant or under-constrained mechanism gives a clear error (degrees of freedom count shown), not a hang.
4. Send-to-structural creates a case whose load resultant equals the joint reactions (and inertia) to 1e-9.
5. Missing exudyn: a clear error and the rest of Studio works.
6. i18n keys identical in ja/en/zh (backend and frontend); `npm run build` clean.

## 6. Report

`reviews/v0.9_mechanisms_report.md`: files changed, tests, template results vs references, run times, what was left
out. Commits with author `NovaSolver <info@novasolver.jp>` and the trailer
`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
