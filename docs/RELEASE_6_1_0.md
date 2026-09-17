# ForgeCAD 6.1.0

ForgeCAD 6.1.0 makes simulation an executable, first-class part of the canonical engineering environment. It does not replace the 6.0/6.0.1 product substrate; it extends the same branch-owned engineering model with constraint-preserving motion, multiphysics analysis, viewport playback, and simulation provenance.

## Release scope

### Constrained multibody motion

- Canonical rigid-joint graph for fixed, revolute, prismatic, cylindrical, and planar joints.
- A transform applied to a supporting body propagates through its complete downstream rigid subtree.
- Explicit joint actuation propagates through every descendant body rather than moving a single mesh independently.
- Closed kinematic loops and inconsistent topology fail closed where the built-in solver cannot establish a valid tree solution.
- Time-domain joint sweeps generate sampled poses, body velocities/accelerations, swept bounds, and support-load evidence.
- Exact B-rep penetration checks are evaluated at sampled sweep poses. A detected penetration is collision evidence; the built-in sweep does not claim an impact/contact-dynamics solution.

### Viewport simulation playback

- A completed joint sweep can play its calculated frames directly in the 3D viewport.
- Playback is a non-mutating preview: the canonical design pose is restored after playback.
- Sampled collision bodies are highlighted during playback.
- Interactive transforms of supporting bodies preserve modeled joint continuity in the viewport and backend commit path.

### Mechanical and fluid solvers

The Analyze workspace exposes the existing engineering solvers through one 6.1 simulation contract and one design-fingerprint provenance model:

- gravity and joint load paths;
- 3D linear-elastic solid FEA within its explicitly supported geometry/boundary-condition scope;
- rigid-body mass/inertia and constant-load response;
- steady incompressible hydraulic network analysis from explicit pressure boundaries, demands, and links.

Unsupported inputs remain unsupported rather than being silently approximated as a higher-fidelity solution.

### Thermal simulation

ForgeCAD 6.1.0 contains two complementary built-in thermal paths:

1. **Assembly transient thermal** — lumped thermal mass, explicit conduction links, convection, fixed-temperature boundaries, radiation where modeled, and temperature-limit evidence across the canonical assembly.
2. **3D thermal field** — transient finite-difference internal conduction for supported unfeatured rectangular box solids, including volumetric heat generation, all-surface convection/radiation, explicit numerical-stability control, temperature gradients, field output, and energy-balance evidence.

The 3D field solver fails closed outside its supported solid/material scope; it is not presented as a general arbitrary-B-rep thermal solver.

### Aerodynamic loads

The built-in aerodynamic path is a geometry-aware integral coefficient model for engineering screening loads. It is explicitly **not CFD**. OpenFOAM availability is reported separately and does not imply a validated ForgeCAD geometry-to-mesh-to-boundary-condition case adapter.

### Simulation provenance

- Simulation runs are recorded against the exact canonical design fingerprint.
- Canonical design mutations invalidate affected simulation evidence rather than leaving old predictions marked current.
- Current/stale state is visible in Analyze.
- Solver name, version, grade, assumptions, limitations, and prediction-vs-observation boundaries remain explicit.

## Acceptance gates

The 6.1 release gate verifies:

- multibody graph construction and descendant propagation;
- supporting-body transforms and explicit joint actuation;
- time-domain subtree motion;
- exact-geometry sampled collision detection;
- gravity load paths;
- transient assembly thermal behavior;
- integral aerodynamic load behavior and non-CFD labeling;
- 3D thermal-field spatial gradients, explicit stability control, energy conservation, and fail-closed unsupported geometry;
- preserved v2 physics solvers and 6.0.1 runtime hardening;
- live HTTP registration and execution of the 6.1 simulation endpoints;
- desktop typecheck/build;
- Chromium interaction acceptance covering joint sweep controls, viewport playback evidence, canonical-pose preservation, and the 3D thermal-field UI.

Native release validation additionally installs and launches the packaged Windows and macOS applications and executes 6.1 simulation/thermal runtime smoke tests from the bundled Forge Engine.

## Native artifacts

The published `v6.1.0` release contains:

- `ForgeCAD-Setup-6.1.0.exe` — Windows x64 NSIS installer;
- `ForgeCAD-6.1.0-arm64.dmg` — macOS Apple Silicon disk image;
- `ForgeCAD-6.1.0-x64.dmg` — macOS Intel disk image;
- `SHA256SUMS.txt` — SHA-256 manifest for the three installers.

The release tag and GitHub Release target are bound to the exact source SHA accepted by the native release workflow.

## Truth boundary

ForgeCAD simulation output is **prediction evidence**, not physical observation, hardware validation, certification, or a safety guarantee. A branch marked working is still a design-management label. CI fixtures, solver convergence, installer hashes, and successful native launch tests establish software/release integrity only; they do not establish that a physical product has been built or proven safe.
