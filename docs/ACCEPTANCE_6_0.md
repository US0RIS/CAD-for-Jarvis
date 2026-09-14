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

Status: **IMPLEMENTED / CI VALIDATION PENDING**

Implementation commit: `8817b59486226b322e7bbea305e7abdf141d335a`.

This is dependency-critical because autonomous engineering cannot reliably design a product if component placement is still based on guessed transforms rather than declared physical interfaces.

Generic capabilities introduced by this milestone:

- typed fixed/revolute/prismatic/cylindrical/planar mate contracts;
- deterministic rigid placement from exact object/interface identity;
- explicit aligned/opposed-axis semantics;
- interface occupancy enforcement;
- mate degrees-of-freedom records;
- positional/angular residual validation;
- canonical project `joint` + `connection` records rather than a parallel assembly store;
- Engineering Graph propagation through the existing joint/connection projection.

### Automated acceptance fixture

The first fixture is a networked electromechanical actuator module built from:

- an editable fabricated chassis/deck;
- Raspberry Pi 5 compute;
- MEAN WELL LRS-75-12 power supply;
- Pololu D24V50F5 regulator;
- Adafruit MOSFET driver;
- Adafruit 12 V push-pull solenoid;
- branch-bound actuator software.

Acceptance requires, in one canonical revision:

1. purchased components retain exact registry identity and high-trust snapshots;
2. mounted components are positioned by interface constraints, not hand-authored transforms;
3. every constrained mechanical mate closes below configured positional/angular residual tolerances;
4. exclusive mechanical interfaces cannot be double-used;
5. explicit electrical interface connections exist from supply through conversion/control to the actuator;
6. programmable hardware has code in the same branch;
7. a canonical mass requirement verifies;
8. a real 3D solid structural screening solve executes with explicit solver grade;
9. FDM DFM screening executes against the fabricated part;
10. Engineering Graph contains CAD, catalog component, joint, electrical, software, BOM and requirement identities;
11. a fabrication archive preserves the exact graph revision, software and BOM;
12. the complete ForgeCAD 3.1 integration regression remains green.

Passing this milestone does **not** mean 6.0 is complete. It moves assembly placement from level 1/2 toward level 2 with a cross-domain acceptance fixture. External CAD/physical validation of mating accuracy remains later work.
