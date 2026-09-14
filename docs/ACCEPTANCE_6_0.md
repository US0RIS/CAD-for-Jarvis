# ForgeCAD 6.0 Acceptance Contract

Status: **IN DEVELOPMENT — do not treat 6.0 as released**

Baseline: validated ForgeCAD 3.1.0 branch state at `a9d67726f97561e6f664529b44ca016fda012ff0`.

ForgeCAD 6.0 is the direct continuation of the original product goal: one AI-native physical-engineering environment in which CAD, purchased components, assemblies, electronics, software, requirements, analysis, manufacturing, physical observations, deployed state, and Jarvis all refer to the same canonical engineering identities.

The release invariant remains:

```text
designed truth != observed state != inference
```

and 6.0 adds:

```text
autonomous engineering action -> declared engineering inputs -> deterministic canonical mutation -> explicit verification
```

## Capability maturity rubric

Every material capability is tracked at one of four levels:

1. **Infrastructure** — schema/API/adapter exists.
2. **Controlled capability** — works in a narrow deterministic case.
3. **Realistic robustness** — works across representative real projects and failure modes.
4. **External validation** — checked against independent ground truth, industrial software, or real hardware.

A capability is never called complete merely because level 1 exists.

## Release-level acceptance target

6.0 is not complete until a user can state a physical-product goal and ForgeCAD can, within explicit authority boundaries:

- derive inspectable requirements and functional architecture;
- select exact real purchased components with immutable revision snapshots, provenance, interfaces, and procurement identity;
- create editable custom fabricated geometry where required;
- build and validate assembly, electrical, thermal/fluid, software, routing, manufacturing, safety and verification state in one canonical model;
- run appropriate screening analysis and invoke high-fidelity external solvers without fabricating solver results;
- keep hardware and software on the same design lineage;
- generate reproducible fabrication/deployment packages;
- ingest physical measurements, photos/observations and deployed-state evidence without silently rewriting design truth;
- compare working and failed physical revisions semantically;
- diagnose failures, create repair branches and re-verify them;
- expose the same semantic engineering operations to Jarvis without GUI automation;
- resolve sensed physical objects back to engineering identities with explicit confidence/provenance;
- provide a 3D-first desktop interaction model in which engineering context follows the physical object.

## Milestone 1 — Interface-Constrained Electromechanical Assembly

Status: **PASS — maturity level 2 controlled capability**

Validated implementation SHA: `4a94320d6fc6e264ebce4ff6b95834f57f35e3a7`

Validation workflow: `ForgeCAD 6.0 milestone 1 regression`, run `34907732526`

All four gates in that run passed:

1. ForgeCAD 6.0 interface-constrained electromechanical vertical slice;
2. complete ForgeCAD 3.1 integration regression;
3. complete pre-3.1/full-scope engineering regression;
4. independent existing 3D solid-FEA benchmark.

This milestone is dependency-critical because autonomous engineering cannot reliably design a product if component placement is still based on guessed transforms rather than declared physical interfaces.

Generic capabilities introduced by this milestone:

- typed fixed/revolute/prismatic/cylindrical/planar mate contracts;
- deterministic rigid placement from exact object/interface identity;
- explicit aligned/opposed-axis semantics;
- interface occupancy enforcement, including tested double-use rejection;
- mate degrees-of-freedom records;
- positional/angular residual validation;
- canonical project `joint` + `connection` records rather than a parallel assembly store;
- Engineering Graph propagation through the existing joint/connection projection;
- an additive `/v6` semantic API layered over the validated 3.1 substrate.

### Automated acceptance fixture

The accepted fixture is a networked electromechanical actuator module built from:

- an editable PETG fabricated chassis/deck with feature history and a harness pass-through slot;
- an editable CNC aluminum actuator reaction rail;
- Raspberry Pi 5 compute;
- MEAN WELL LRS-75-12 power supply;
- Pololu D24V50F5 regulator;
- Adafruit MOSFET driver;
- Adafruit 12 V push-pull solenoid;
- branch-bound actuator software.

The accepted canonical revision proves:

1. purchased components retain exact registry identity and high-trust snapshots;
2. five mechanical placements are solved from declared interfaces instead of hand-authored transforms;
3. every constrained mate closes below configured positional/angular residual tolerances;
4. a second use of an occupied exclusive mount is rejected without mutating canonical state;
5. explicit electrical connections exist from supply through conversion/control to the actuator;
6. programmable hardware has code in the same branch;
7. a canonical mass requirement verifies;
8. the featured chassis is explicitly rejected by the existing solid solver rather than being silently approximated;
9. the exact unfeatured load-bearing reaction rail completes a real 3D solid structural screening solve with `engineering_iteration` solver grade;
10. FDM DFM screening executes against the fabricated chassis;
11. the Engineering Graph contains CAD, catalog component, joint, connection, software, BOM and requirement identities;
12. a fabrication archive preserves the graph revision, software, BOM and both custom fabricated parts;
13. the complete ForgeCAD 3.1 and earlier engineering regressions remain green.

### Known limits after milestone 1

Milestone 1 is deliberately **not** maturity level 3 or 4.

- General featured B-rep solid FEA is still unsupported because ForgeCAD lacks a validated general-purpose volume/tetrahedral mesher. The milestone now tests that this case fails closed.
- The current mate solver reliably validates interface position and primary axis in the controlled slice. Arbitrary industrial fixed-mate orientation still needs a secondary rotational datum/full interface frame and broader multi-mate/overconstraint solving.
- A typed mounting interface does not yet prove that a fabricated part contains every required hole/fastener/insert feature implied by a purchased component's real mounting pattern. Geometry-backed interface synthesis/verification remains required.
- Real supplier/CAD ingestion still needs to move from the existing curated/high-trust registry toward a broad refreshable component ecosystem.
- No physical hardware has yet externally validated milestone-1 mating accuracy, fabrication fit, electrical operation, or deployment behavior.

Passing this milestone therefore means the first cross-domain 6.0 vertical slice genuinely works as a controlled software capability. It does **not** mean ForgeCAD 6.0 is released or that industrial assembly/CAE/physical closure is complete.

## Next dependency-critical work

The next milestone should deepen **geometry-backed assembly truth** rather than add unrelated surface area:

1. full interface frames with secondary rotational datums;
2. geometric mounting-pattern compatibility, not kind-only matching;
3. automatic synthesis/verification of mounting holes, fasteners, standoffs, inserts and clearances in custom fabricated parts;
4. multi-mate constraint solving and explicit under/over-constrained assembly state;
5. broad real-component ingestion with immutable source/revision provenance;
6. external CAD/geometry validation for representative purchased-component mounts.

This is the shortest path from milestone-1 controlled assembly toward a level-3 autonomous engineering substrate.
