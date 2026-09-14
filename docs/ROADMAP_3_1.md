# ForgeCAD 3.1.0 — Integration Release

ForgeCAD 3.1.0 is the release where the existing CAD, engineering, software, manufacturing, world-model, and hardware-control subsystems become one coherent engineering system.

The 3.0 line established the persistent Physical World Model and Jarvis-facing identity/action substrate. 3.1 moves the product from "many capable engineering subsystems" toward a single canonical engineering graph with deterministic propagation, verification, diagnosis, and closed-loop design behavior.

## Release thesis

A physical part, component, requirement, electrical device, software target, BOM line, simulation subject, manufacturing artifact, and deployed physical object must not become seven unrelated records. ForgeCAD 3.1 introduces a canonical engineering graph that gives those representations one stable engineering identity and explicit typed relationships.

Changing a motor, dimension, controller, route, requirement, or manufacturing process should deterministically identify the affected engineering records, mark stale evidence, re-evaluate constraints, and tell Jarvis what must be recomputed or repaired.

## 3.1 committed scope

### 1. Direct CAD editing
- feature-history records for sketches, extrusions, revolves, booleans, fillets, chamfers, patterns, holes, loft/sweep contracts, datum planes/axes, and transforms;
- stable feature IDs and topology references where supported;
- explicit unsupported/degraded states rather than silent approximation;
- edit/rollback semantics suitable for keyboard-first desktop use and Jarvis operations.

### 2. Assembly intelligence
- typed joints/mates, motion limits, bearings, fasteners, interfaces, service clearances, and interference relationships;
- explicit assembly connectivity graph;
- dependency and serviceability checks.

### 3. Unified engineering graph
Canonical nodes and edges spanning:
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

### 4. Closed-loop AI engineering
A bounded deterministic loop around the existing planner/campaign infrastructure:
`intent → requirements → architecture → candidates → CAD/electrical/software → verification → diagnosis → repair branch → re-verification`.

The AI may propose; canonical state mutation and verification remain deterministic and auditable.

### 5. Larger real-component ecosystem
- generalized component-family schema;
- compatibility/interface metadata;
- supplier/availability/cost hooks;
- geometry/spec confidence and provenance;
- deterministic candidate filters usable without an LLM.

### 6. Constraint-driven substitution
- replacement candidate search against interface, envelope, electrical, mechanical, thermal, software, availability, and cost constraints;
- impact report before mutation;
- deterministic propagation after an accepted replacement.

### 7. Higher-fidelity simulation
- solver-adapter contracts for structural FEA, thermal-field, CFD/hydraulics, dynamics, vibration/modal, fatigue, contact, motor/load curves, and tolerance analysis;
- existing deterministic local solvers remain available as screening solvers;
- external/high-fidelity solvers must report provenance, version, input fingerprint, assumptions, and validity limits.

### 8. Manufacturing-aware design
- process constraints for additive, CNC, sheet metal, and laser/waterjet classes;
- manufacturability findings bound to canonical geometry fingerprints;
- tool access, wall thickness, overhang/support, bend radius, hole/drill, stock, and process-envelope checks where data exists.

### 9. Fabrication package generation
A reproducible package manifest tying together geometry exports, drawings/notes, BOM, wiring, software/firmware, manufacturing resources, analysis evidence, and revision identity.

### 10. Physical-build feedback
- measurement/inspection records linked to canonical entities;
- expected-vs-observed comparison;
- deviation findings capable of invalidating stale assumptions/evidence;
- redesign feedback into branches/campaigns.

### 11. First-class requirements and verification
Requirements are typed canonical objects with target, comparator, unit, owner/scope, evidence, status, and confidence. Release readiness is derived from requirements rather than prose.

### 12. Deep provenance
Every derived decision/evidence record carries input fingerprints, source IDs, method, timestamp, confidence, assumptions, and invalidation reasons.

### 13. Failure diagnosis
A causal diagnostic layer traces failed requirements/analyses backward through the engineering graph, ranks likely causes, and proposes bounded repair actions with impacted-node previews.

### 14. Project-scale version control
- semantic graph/engineering diff;
- design branch comparison;
- working-vs-failed revision comparison;
- merge/conflict contracts for canonical engineering entities;
- protected physically verified baselines remain immutable without explicit branching.

### 15. Interaction/polish
- keyboard-first object manipulation and deletion;
- command palette and discoverable shortcuts;
- multi-select/context operations;
- deterministic selection and inspection;
- panel/tool state available through semantic commands as well as GUI interactions.

### 16. Performance architecture
- incremental graph projection;
- dirty-node propagation rather than whole-project recomputation;
- geometry/thumbnail cache separation;
- background/worker-ready task contracts and large-assembly summary APIs.

### 17. Recovery/durability
- transactional engineering-graph persistence;
- schema versioning/migration;
- autosave/recovery checkpoints;
- stale/corrupt derived evidence can be rebuilt from canonical state.

### 18. Jarvis-native semantic API
Jarvis operates the engineering model directly rather than automating UI controls. Every important 3.1 operation must have a typed API and audit trail.

### 19. Live hardware synchronization
- design/deployed-state comparison for programmable devices;
- software fingerprint, configuration, telemetry, capability, and health records;
- drift findings when physical/deployed state diverges from design intent.

### 20. World-model visualization
- engineering graph ↔ Physical World Model linkage exposed to the desktop;
- world entity, CAD entity, live state, evidence, and deployed-state relationships inspectable from the same selection context.

## Product Lab direction

ForgeCAD will also support a smaller-product workflow, provisionally called **Product Lab**. This is not a weaker engineering mode; it is a different workspace profile optimized for compact, tightly integrated devices such as wearables, wrist mechanisms, sensor gadgets, handheld electromechanical products, compact robotics, launchers, and experimental mechanisms.

Product Lab emphasizes:
- body/hand/wrist/garment envelopes and ergonomic keep-out zones;
- compact packaging and mass/center-of-mass budgets;
- batteries, embedded electronics, actuators, mechanisms, housings, and wiring in one enclosure-scale workflow;
- fast iteration among prototype manufacturing processes;
- energy, heat, pressure, stored-energy, pinch/impact, and human-contact safety budgets;
- test rigs and instrumented prototype evidence;
- small-part tolerances, fasteners, seals, flexible elements, cords/cables, and consumables;
- explicit separation between fictional inspiration and physically supportable engineering assumptions.

3.1 establishes the profile/ontology hooks so Product Lab can be expanded without forking the engineering model. A later release can make it a dedicated workspace/subsection if the UI deserves a separate experience.

## Release acceptance

3.1.0 is complete only when:
1. all existing 3.0 engineering/world/capability/browser regressions remain green;
2. the canonical engineering graph is persistent, deterministic, and reconstructable from project/world state;
3. requirements/evidence/provenance and invalidation work end-to-end;
4. component substitution produces a deterministic impact/propagation report;
5. failure diagnosis traces through graph dependencies;
6. fabrication and physical-feedback manifests bind to exact revision fingerprints;
7. Jarvis can inspect and invoke the new semantic surfaces without GUI automation;
8. Product Lab projects are represented by the same canonical graph with a compact-product profile;
9. packaged Windows and macOS builds pass installed-copy smoke tests.
