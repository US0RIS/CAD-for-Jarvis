# ForgeCAD 6.0 Acceptance Contract

Status: **SOFTWARE SOURCE ACCEPTED — NATIVE INSTALLER VALIDATION PENDING**

Baseline: validated ForgeCAD 3.1.0 branch state at `a9d67726f97561e6f664529b44ca016fda012ff0`.

Current validated 6.0 source RC: `4a4b318cac65d2290a39d64a357c219da311de6e`.

Source release-candidate workflow: `ForgeCAD 6.0 release candidate`, run `34925058122` — **PASS**.

ForgeCAD 6.0 is the direct continuation of the original product goal: one AI-native physical-engineering environment in which CAD, purchased components, assemblies, electronics, software, requirements, analysis, manufacturing, chemistry, physical observations, deployed state, and Jarvis refer to the same canonical engineering identities.

The release invariant is:

```text
designed truth != observed state != inference
```

and autonomous engineering follows:

```text
declared engineering inputs -> deterministic canonical mutation -> explicit verification/evidence
```

## Maturity rubric

1. **Infrastructure** — schema/API/adapter exists.
2. **Controlled capability** — works in a narrow deterministic case.
3. **Realistic robustness** — works across a representative integrated product/failure path.
4. **External/physical validation** — checked against independent ground truth, industrial software, or real hardware as appropriate.

A software release may be complete without falsely claiming level-4 real-hardware validation. `/v6/health` exposes those states separately.

## Release-level acceptance target

The 6.0 software line must be able to keep one physical-product lineage coherent while it:

- derives/holds inspectable requirements and functional architecture;
- selects exact purchased components with immutable revision/provenance/interface identity;
- creates editable custom fabricated geometry;
- reasons over assembly constraints, mount geometry, hardware/access, electrical/software, thermal/fluid, tolerance, safety, manufacturing, and chemistry state;
- executes screening analysis and validated external solvers without fabricating unsupported results;
- keeps programmable hardware and its software on the same branch/revision lineage;
- generates fabrication/deployment packages tied to exact engineering state;
- records observations and physical test evidence without rewriting designed truth;
- compares revisions semantically, diagnoses failures, branches repairs, and re-verifies affected requirements;
- exposes the same semantic operations to Jarvis and the Physical World model rather than relying on GUI automation.

The final **release** gate additionally requires native install-and-run validation for Windows x64, macOS arm64, and macOS x64. Merely building archives is insufficient.

## Milestone 1 — Interface-Constrained Electromechanical Assembly

Status: **PASS — level 2**.

Validated implementation SHA: `4a94320d6fc6e264ebce4ff6b95834f57f35e3a7`.

Validation workflow run: `34907732526`.

Introduced typed mechanical mates, exact object/interface identity, deterministic rigid placement, interface occupancy, explicit mate DOF, residual validation, and canonical `joint` + `connection` storage. The fixture is a networked actuator module containing custom fabricated chassis/rail geometry, Raspberry Pi 5, MEAN WELL supply, Pololu regulator, Adafruit MOSFET driver/solenoid, electrical connectivity, software, requirements, DFM, structural screening, graph propagation, and fabrication output.

The featured chassis continues to fail closed in the legacy solid solver rather than being silently approximated. An unfeatured load-bearing reaction rail is solved through the validated engineering-iteration structural path.

## Milestone 2 — Geometry-Backed Assembly Truth

Status: **PASS — level 2**.

6.0 now uses complete right-handed mechanical interface frames where required rather than pretending a point + primary axis fully constrains arbitrary fixed orientation. It also adds explicit constraint-rank/mobility analysis, geometry-backed mount realization/audit, manufacturer mount truth with coordinates/datums/provenance, standards-backed mount hardware, and assembly-access envelopes.

Ambiguous mounting topology, occupied exclusive interfaces, impossible access, missing geometric realization, or contradictory constraints fail closed rather than being guessed.

## Milestone 3 — Evidence-Preserving Analysis Refresh/Repair

Status: **PASS — level 2**.

Analysis results are revision/fingerprint-bound. Geometry-changing repair invalidates affected solver evidence; the repair path must refresh analysis and requirement verification rather than reusing stale results. Engineering Graph evidence remains inspectable and stale state is explicit.

## Milestone 4 — Bounded Autonomous Repair

Status: **PASS — level 2**.

ForgeCAD may choose only among explicitly authorized repair strategies. Candidate branches are evaluated against canonical requirements/evidence, and selection is bounded by the allowed strategy set rather than open-ended mutation. Failed candidates do not overwrite the known-working lineage.

## Milestone 5 — Revision-Bound Physical Feedback

Status: **PASS — level 2 software contract; real-hardware validation remains false**.

The physical-feedback stack now includes exact design fingerprints, artifacts, metrology/calibration/uncertainty contracts, repeated-run and multi-specimen evidence, conservative aggregation, prediction-vs-observation residuals, scoped requirement retests, and semantic revision comparison.

CI exercises these contracts with synthetic evidence. Synthetic CI evidence is never labeled as a real fabricated specimen or real-hardware validation.

## Milestone 6 — External Solvers and Chemistry

Status: **PASS — level 2 external-solver capability**.

Validated runtime checkpoint: workflow run `34924195243` — **PASS**.

6.0 adds a fail-closed external-solver inventory. Cantera is the validated release solver for:

- thermochemistry;
- chemical equilibrium;
- reaction kinetics;
- homogeneous zero-dimensional reactor networks.

Chemistry studies are canonical engineering records tied to an exact physical object and design fingerprint. Packaged Cantera YAML mechanisms carry SHA-256 provenance. Equilibrium and time-dependent reactor results are written back as prediction evidence, never as physical measurements. Unsafe/arbitrary mechanism paths, stale design contracts, unavailable solvers, and invalid species fail closed.

CalculiX, Gmsh, and OpenFOAM may be detected as optional tools; availability alone is explicitly not treated as proof that a production case generator/mesher exists for arbitrary ForgeCAD models.

## Cross-domain 6.0 release candidate

Status: **PASS — integrated software maturity level 3**.

Validated SHA: `4a4b318cac65d2290a39d64a357c219da311de6e`.

Validation workflow run: `34925058122` — all steps passed.

One canonical project lineage carries:

- the M1 real-component actuator rig;
- custom CAD and fabrication output;
- mechanical/electrical/software state;
- structural analysis;
- rail-attached thermal and low-pressure liquid-loop models;
- tolerance-stack and safety state;
- bounded branch/redesign/retest behavior;
- an externally solved Cantera chemistry characterization cell;
- Engineering Graph evidence;
- Jarvis semantic context;
- Physical World identity.

The run also independently reran Milestone 6, the complete Milestone 5 physical-feedback stack, Milestones 4–1, ForgeCAD 3.1, the historical full-scope regression, and the existing structural FEA benchmark.

## Native release gate

The staged `6.0.0` source identity is **not published** until all of the following pass on binaries built from that source:

1. Windows x64 Forge Engine packaging includes v600 and Cantera data/binaries.
2. The standalone packaged Windows engine reports `/v6/health` as `6.0.0`, reports Cantera available, resolves packaged `gri30.yaml`, and executes a chemistry study.
3. The Windows NSIS installer installs cleanly; the installed engine repeats that runtime validation; the Electron desktop launches its bundled engine; uninstall succeeds.
4. Native macOS arm64 and x64 Forge Engine builds contain the expected architecture and Cantera runtime.
5. Each DMG mounts, copies, passes bundle-version/codesign checks, and the installed engine repeats the packaged chemistry validation.
6. Each installed macOS desktop launches its bundled 6.0 engine.
7. Only after all native jobs pass may `RELEASE_COMPLETE` become true and the final binaries be rebuilt from that exact source.
8. The publish job creates/updates GitHub release `v6.0.0` and emits SHA-256 hashes for all three installers.

## Truth boundaries retained in 6.0.0

Even after the software release is complete:

- `physical_hardware_validation` remains false until real hardware evidence exists for a specific project/revision;
- general arbitrary featured-B-rep tetrahedral meshing/solver support is not invented where unsupported;
- optional external solver presence is not equivalent to a validated adapter for every case;
- Cantera does not imply multidimensional reacting-flow CFD;
- a fabrication archive hash proves archive byte identity, not that a physical specimen was manufactured from it;
- passing a scoped physical retest verifies only the requirement/evidence scope actually tested.

These are product guarantees, not missing marketing claims.
