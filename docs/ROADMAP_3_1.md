# ForgeCAD 3.1.0 — Integration Release

Status: **COMPLETE / release-validated**

Application implementation SHA: `dcfc9269c484629797672e046e9da729740d6e66`

Final macOS release-validation SHA: `cd2b3151f99f8762590b04a79df6004a21ead5af`

ForgeCAD 3.1.0 is the release where the existing CAD, engineering, software, manufacturing, world-model, and hardware-control subsystems become one coherent engineering system.

The 3.0 line established the persistent Physical World Model and Jarvis-facing identity/action substrate. 3.1 moves the product from "many capable engineering subsystems" toward a single canonical engineering graph with deterministic propagation, verification, diagnosis, and closed-loop design behavior.

## Release thesis

A physical part, component, requirement, electrical device, software target, BOM line, simulation subject, manufacturing artifact, and deployed physical object must not become seven unrelated records. ForgeCAD 3.1 introduces a canonical engineering graph that gives those representations one stable engineering identity and explicit typed relationships.

Changing a motor, dimension, controller, route, requirement, or manufacturing process deterministically identifies the affected engineering records, marks stale evidence, re-evaluates constraints, and tells Jarvis what must be recomputed or repaired.

## Completed 3.1 scope

### 1. Direct CAD editing
- feature-history records for sketches, extrusions, revolves, booleans, fillets, chamfers, patterns, holes, loft/sweep contracts, datum planes/axes, and transforms;
- stable feature IDs and topology references where supported;
- explicit unsupported/degraded states rather than silent approximation;
- edit/rollback semantics suitable for keyboard-first desktop use and Jarvis operations;
- desktop feature-stack editing with add, edit, suppress, duplicate, reorder, and delete operations.

### 2. Assembly intelligence
- typed joints/mates, motion limits, bearings, fasteners, interfaces, service clearances, and interference relationships;
- explicit assembly connectivity graph;
- dependency and serviceability checks.

### 3. Unified engineering graph
Canonical nodes and edges span:
- CAD objects/features;
- component catalog parts;
- BOM lines and procurement records;
- electrical devices/nets/rails;
- software workspaces and deployment targets;
- requirements and verification evidence;
- analyses and their input fingerprints;
- manufacturing resources/artifacts;
- physical-world entities and observations;
- device capabilities and live telemetry.

Graph rebuilds are deterministic, clean no-op rebuilds do not create false dirtiness, failed physical evidence survives reconstruction, and dirty/stale state is derived from unresolved engineering evidence rather than transient UI state.

### 4. Closed-loop AI engineering
A bounded deterministic loop now exists around the planner/campaign infrastructure:
`intent → requirements → architecture → candidates → CAD/electrical/software → verification → diagnosis → repair branch → re-verification`.

The AI may propose; canonical state mutation and verification remain deterministic and auditable. Arbitrary physical or geometry actions are not silently self-authorized.

### 5. Larger real-component ecosystem
- generalized component-family schema;
- compatibility/interface metadata;
- supplier/availability/cost hooks;
- geometry/spec confidence and provenance;
- deterministic candidate filters usable without an LLM;
- cross-vendor compatibility indexing.

### 6. Constraint-driven substitution
- replacement candidate search against interface, envelope, electrical, mechanical, thermal, software, availability, and cost constraints;
- impact report before mutation;
- deterministic propagation after an accepted replacement.

### 7. Higher-fidelity simulation
- solver-adapter contracts for structural FEA, thermal-field, CFD/hydraulics, dynamics, vibration/modal, fatigue, contact, motor/load curves, and tolerance analysis;
- existing deterministic local solvers remain available as screening solvers;
- external/high-fidelity solvers report provenance, version, input fingerprint, assumptions, and validity limits.

### 8. Manufacturing-aware design
- process constraints for additive, CNC, sheet metal, and laser/waterjet classes;
- manufacturability findings bound to canonical geometry fingerprints;
- tool access, wall thickness, overhang/support, bend radius, hole/drill, stock, and process-envelope checks where data exists.

### 9. Fabrication package generation
A reproducible fabrication archive ties together STEP/STL geometry, `.focad`, BOM, software, requirements, analysis/evidence hashes, manufacturing resources, and revision identity.

### 10. Physical-build feedback
- measurement/inspection records linked to canonical entities;
- expected-vs-observed comparison;
- deviation findings that invalidate stale assumptions/evidence;
- failed physical evidence persists across graph reconstruction and restart;
- redesign feedback into branches/campaigns.

### 11. First-class requirements and verification
Requirements are typed canonical objects with target, comparator, unit, owner/scope, evidence, status, and confidence. Release readiness derives from requirements rather than prose.

### 12. Deep provenance
Derived decisions/evidence carry input fingerprints, source IDs, method, timestamp, confidence, assumptions, and invalidation reasons.

### 13. Failure diagnosis
A causal diagnostic layer traces failed requirements/analyses backward through the engineering graph, ranks likely causes, and proposes bounded repair actions with impacted-node previews.

### 14. Project-scale version control
- semantic graph/engineering diff;
- design branch comparison;
- working-vs-failed revision comparison;
- semantic three-way merge and conflict contracts for canonical engineering entities;
- protected physically verified baselines remain immutable without explicit branching.

### 15. Interaction/polish
- click/select + Backspace/Delete object deletion;
- keyboard-first manipulation and history actions;
- discoverable shortcut palette;
- deterministic selection and inspection;
- direct feature-history UI;
- panel/tool state through semantic commands as well as GUI interactions.

### 16. Performance architecture
- incremental graph projection;
- dirty-node propagation rather than whole-project recomputation;
- geometry/thumbnail cache separation;
- background/worker-ready task contracts and large-assembly summary APIs.

### 17. Recovery/durability
- transactional engineering-graph persistence;
- schema versioning/migration;
- recoverable multi-branch checkpoints;
- stale/corrupt derived evidence can be rebuilt from canonical state.

### 18. Jarvis-native semantic API
Jarvis operates the engineering model directly rather than automating UI controls. The `/v3.1/jarvis/context` surface exposes the unified engineering state, graph revision, Product Lab state, evidence, and relevant world/design identity.

### 19. Live hardware synchronization
- design/deployed-state comparison for programmable devices;
- software fingerprint, configuration, telemetry, capability, and health records;
- drift findings when physical/deployed state diverges from design intent.

### 20. World-model visualization
- Engineering Graph ↔ Physical World Model linkage is exposed to the desktop SYSTEM workspace;
- world entity, CAD entity, live state, evidence, deployed-state relationships, graph health, dirty state, and selected-object impact/evidence are inspectable from the same context.

## Product Lab

3.1 establishes **Product Lab** as a first-class workspace profile using the same canonical engineering model. It is intended for compact integrated products such as wearables, wrist mechanisms, sensor gadgets, handheld electromechanical products, compact robotics, launchers, and experimental mechanisms.

Product Lab includes profile hooks for body/hand/wrist/garment envelopes, compact packaging, mass budgets, human contact, stored-energy limits, surface-temperature limits, ergonomic keep-outs, embedded electronics/actuators, and preferred prototype processes. It remains the same engineering truth model rather than a separate weaker CAD system.

A later release may expand Product Lab into a dedicated workspace/subsection if its interaction model warrants it; that is explicitly outside the 3.1.0 release scope.

## Release acceptance — PASS

All committed 3.1.0 acceptance criteria are satisfied:

1. **PASS** — existing engineering, 3.0 world, identity, planner, event-stream, capability, and browser regressions remain green;
2. **PASS** — the canonical Engineering Graph is persistent, deterministic, reconstructable, and does not create false dirty state on a clean rebuild;
3. **PASS** — requirements/evidence/provenance and invalidation work end-to-end;
4. **PASS** — component substitution produces deterministic compatibility and impact/propagation results;
5. **PASS** — failure diagnosis traces graph dependencies and bounded repair actions;
6. **PASS** — fabrication and physical-feedback records bind to exact revision/fingerprint state;
7. **PASS** — Jarvis can inspect the new semantic surfaces without GUI automation;
8. **PASS** — Product Lab uses the same canonical graph with its compact-product profile;
9. **PASS** — packaged Windows x64 and macOS arm64/x64 builds pass installed-copy and desktop-launch validation.

Exact workflow and artifact provenance is recorded in `docs/RELEASE_3_1.md`.
