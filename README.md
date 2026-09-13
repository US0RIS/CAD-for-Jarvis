# ForgeCAD

> **An AI-native, local-first engineering environment and physical-world substrate for Jarvis.**

ForgeCAD combines CAD, real components, embedded software, deterministic engineering analysis, design lineage, manufacturing preparation, physical evidence, autonomous design exploration, and a persistent model of physical reality in one system.

The long-term objective is not “a chatbot attached to CAD.” It is a system in which Jarvis can understand a real physical system, resolve the exact objects involved, reason against authoritative engineering state, predict consequences before acting, preserve evidence and provenance, and carry the result forward without losing the engineering thread.

---

## Status

**Current release:** ForgeCAD **3.0.0**  
**Release branch:** `forgecad/3.0.0`  
**Runtime-validated source SHA:** `a5ae8ad5ecc6622498df1e3c8c3688c31ded0afe`

ForgeCAD 3.0.0 is a functioning local desktop engineering system and the first release to ship the **Physical World Model (PWM)** as a supported product surface.

The complete 2.x engineering workstation remains intact. 3.0 adds the persistent identity, provenance, live-state, capability, event, and Jarvis-context substrate required to treat ForgeCAD as a model of real systems rather than only the design currently open in CAD.

The exact runtime source SHA above passed all four release gates:

- complete ForgeCAD 2.x + 3.0 backend regression;
- browser acceptance for the desktop SYSTEM physical-world surface;
- packaged Windows x64 install / installed-copy / desktop-launch validation;
- packaged macOS x64 and arm64 DMG / installed-copy validation.

Artifact hashes and workflow provenance are recorded in [`docs/RELEASE_3_0.md`](docs/RELEASE_3_0.md).

---

# What 3.0 adds

## Persistent Physical World Model

ForgeCAD now maintains a durable physical graph alongside the canonical project model:

```text
World
└── Site / Building
    └── Room / Zone
        └── Machine / Assembly / Tool
            └── Component / Device
                ├── Interfaces
                ├── Capabilities
                ├── Software
                ├── Live state
                └── Engineering design source
```

World entities have stable identity and may carry:

- semantic kind and name;
- parent/child hierarchy;
- coordinate frame and 6-DoF pose;
- capabilities;
- physical/software interfaces;
- live-state values;
- provenance and confidence;
- source links to ForgeCAD projects, objects, and component references;
- timestamps and revision metadata.

The critical invariant is:

```text
designed truth != observed state != inference
```

ForgeCAD does not silently collapse those classes of knowledge into one mutable value.

## Deterministic project projection

The active ForgeCAD design is projected into the world model as authoritative engineering state.

Projection includes:

- one world entity for the active project/assembly;
- one entity for each project object;
- deterministic world IDs;
- SI world-space pose derived explicitly from the project’s millimeter frame;
- component references and engineering roles;
- programmable-device capabilities;
- frozen component interfaces;
- canonical project connections as world relations;
- branch/revision provenance.

Repeated synchronization updates the same world identities instead of creating duplicates. Stale projected entities are removed when their source project objects disappear.

A world entity is design-addressable only when it carries an explicit `source_links.forgecad_object_id`. Jarvis cannot turn an arbitrary world ID into a CAD edit target by guesswork.

## Live observations and epistemic state

Perception systems, device bridges, humans, and later adapters can submit observations against known entities.

Each state sample preserves:

- value;
- unit where applicable;
- observation time;
- source class;
- source identity;
- confidence;
- metadata.

Observations update **live state**. They do not rewrite canonical CAD or component engineering truth.

Provenance distinguishes at least:

- authoritative ForgeCAD design state;
- human-declared state;
- direct sensor observations;
- Jarvis inference;
- imported external data.

Unknown remains unknown rather than being replaced with plausible text.

## Deterministic identity resolution

Jarvis-facing entity resolution is deterministic at the identity layer.

Resolution supports exact IDs, explicit source links, hierarchy paths, names where unambiguous, kind filters, and capability filters. Ambiguous names fail closed. Fuzzy similarity is not allowed to invent an authoritative entity binding.

This lets a request such as “inspect the Raspberry Pi in the current system” resolve to a stable world entity and, only where explicitly linked, to the underlying ForgeCAD object.

## World-aware engineering planner

The existing engineering planner now receives relevant physical-world context.

That context includes:

- resolved entities;
- hierarchy paths;
- capabilities;
- interfaces;
- live state;
- provenance;
- source links;
- design-addressability information;
- authority rules.

World identity is kept separate from CAD object identity. The planner may reason broadly about intent, but canonical state changes still flow through deterministic ForgeCAD operations.

## Capability contract and physical-action boundary

3.0 defines a capability-oriented contract for physical systems rather than one-off device scripts.

Examples include:

```text
sensor.temperature
sensor.camera
sensor.contact
actuator.relay
actuator.pwm
motion.rotate
motion.translate
compute.execute
software.deploy
network.communicate
engineering.inspect
engineering.modify
engineering.simulate
```

The capability runtime is intentionally bounded. Consequential physical actions require explicit confirmation, arguments are validated against capability contracts, unbound actions fail closed, adapter execution is auditable, and pending physical confirmations are not treated as durable authorization across restart.

3.0 establishes this contract; it does not claim to ship a universal hardware-driver ecosystem.

## World event stream

The physical-world model maintains bounded timestamped change history for entity, relation, synchronization, and observation changes.

Jarvis can consume:

- incremental event history;
- event revision/cursor state;
- authenticated WebSocket push updates;
- deterministic catch-up from a previous event ID;
- explicit reset behavior when a cursor has expired.

This removes the need to continuously diff full world snapshots just to determine what changed.

## Desktop SYSTEM inspector

The desktop SYSTEM workspace exposes the physical-world model directly.

The current surface includes:

- world-model health;
- entity and relation counts;
- project synchronization state;
- selected entity identity;
- design source links;
- capabilities;
- interfaces;
- live state;
- provenance/confidence;
- connected relations.

The release browser gate verifies this against the real production-like engine, including a projected Raspberry Pi, its `compute.execute` / `software.deploy` capabilities, an ingested live temperature observation, deterministic identity resolution, and planner world context.

---

# The inherited engineering workstation

ForgeCAD 3.0 retains the 2.x engineering core rather than replacing it.

## Desktop

The client uses **Electron, React, TypeScript, Three.js, and Monaco** and provides:

- central 3D engineering workspace;
- selection, orbit, pan, zoom, move, rotate, isolate, hide/show, fit, standard views, and exploded presentation;
- component browsing and insertion;
- engineering copilot workflows;
- branch/history surfaces;
- embedded code workspaces;
- analysis surfaces;
- manufacturing and evidence workflows;
- SYSTEM physical-world inspection.

## Real component registry

The release regression verifies **1,439** component-registry entries spanning mechanical, electrical, compute, actuation, sensing, power, routing, and related engineering categories.

Component records may carry manufacturer/model identity, part number, geometry fidelity, dimensions, mass properties, interfaces, electrical limits, thermal data, supplier/procurement information, programmable-target metadata, datasheets, provenance, and confidence.

Manufacturer geometry is preferred where available. Derived or proxy geometry remains explicitly distinguishable from manufacturer-verified geometry.

## Canonical project state

ForgeCAD stores engineering state structurally rather than hiding it in UI state.

Canonical domains include:

- objects and assemblies;
- parameters and requirements;
- loads and constraints;
- joints;
- electrical connections and named nets;
- routes;
- fluid relationships;
- code workspaces;
- manufacturing intent;
- failure modes;
- physical evidence;
- design branches and history.

Undo/redo and branch history operate on project operations rather than merely the rendered interface.

## Git-like physical design lineage

Known-good physical designs can be protected while risky changes happen on experimental branches.

Branches may be marked working, not working, unverified, or physically verified where appropriate. Engineering diffs compare canonical design state rather than screenshots, including routes and safety/failure-mode state.

The system makes differences explicit; it does not claim that a diff alone proves causality.

## Hardware and software together

Programmable components can own code workspaces inside the same design lineage as the physical assembly.

A Raspberry Pi or similar compute target can therefore be inspected as a physical object, edited in CAD context, and associated with software without treating firmware/application code as an unrelated external artifact.

## `.focad` project format

ForgeCAD projects can be exchanged as `.focad` packages preserving reproducible project state rather than exporting only geometry.

3.0 remains backward-compatible with the existing `.focad` format and release gates exercise project export from the packaged engine.

---

# Engineering analysis

ForgeCAD intentionally combines multiple engineering domains in one project. These analyses are deterministic screening and design tools, not substitutes for every specialist sign-off workflow.

| Domain | Current capability | Important limitation |
|---|---|---|
| Structural | Solid FEA screening, project load cases, parameterized structural analysis | Not a universal replacement for validated specialist FEA |
| Modal / rigid body | Modal and rigid-body analysis support | Not a general high-fidelity multibody dynamics suite |
| Tolerances | Deterministic tolerance stacks | Depends on explicitly modeled dimensions and tolerances |
| Electrical | Named nets, interface compatibility, voltage/current/logic validation, conflicting-source detection, current budgets | Not a complete PCB/EMI/power-integrity toolchain |
| Thermal | Steady-state lumped multi-body thermal network, conductance, convection, sinks, limits, energy balance | Not CFD or transient conjugate heat transfer |
| Fluid | Steady-state incompressible networks, explicit resistance or Hagen–Poiseuille behavior, pressure/flow limits, Reynolds information | Not general CFD/compressible flow |
| Routing | Cable/wire/tube/hose/conduit paths, exact length, bend radius, clearance, obstacle screening | Conservative obstacle model; not a full routing optimizer |
| Route-coupled fluid | Canonical routed-tube length can drive hydraulic resistance | Accuracy depends on model assumptions and supplied properties |
| Kinematics | Revolute/prismatic joints, deterministic poses, sampled sweeps, B-rep intersection checks | Sampled motion rather than continuous general multibody dynamics |
| Safety / FMEA | Failure modes, severity/occurrence/detection, controls, verification, design-fingerprint evidence | Not regulatory certification or professional safety approval |

Simulation evidence remains separate from model-generated narrative and from physical verification.

---

# Manufacturing and physical evidence

ForgeCAD supports manufacturing preparation including:

- fabricated-vs-purchased identity;
- build-volume fit checks;
- orientation/packing checks;
- 3MF export;
- branch-safe oversized-part splitting;
- package fingerprints;
- manufacturing/test evidence records.

Evidence can be tied to an exact design/package fingerprint. A later design change can therefore invalidate stale verification instead of silently allowing an old test to “prove” a new object.

Autonomous multi-branch engineering campaigns preserve known-good baselines, generate experimental alternatives, run deterministic requirements/analyses, retain branch evidence, and surface feasible candidates without overwriting the verified design.

---

# Jarvis integration

ForgeCAD exposes deterministic local APIs so Jarvis can treat engineering and physical-world reasoning as structured capabilities rather than drive the application through brittle screen automation.

The supported division is:

### Jarvis

- natural-language interaction;
- long-lived goals and orchestration;
- memory;
- scheduling/monitoring;
- perception;
- user permissions and confirmation policy;
- deciding when physical engineering is required.

### ForgeCAD

- canonical engineering design state;
- persistent physical-world identity/state;
- geometry and component interfaces;
- deterministic engineering calculations;
- manufacturing state;
- branch lineage and evidence;
- physical capabilities and source links;
- typed engineering operations.

The model may reason. Deterministic systems own identity, canonical state, solver output, verification status, and action boundaries.

---

# 3.0 API surface

Core v3 surfaces include:

```text
GET    /v3/health
GET    /v3/world
GET    /v3/world/entities
GET    /v3/world/entities/{id}
GET    /v3/world/relations
GET    /v3/world/events
POST   /v3/world/entities
PUT    /v3/world/entities/{id}
DELETE /v3/world/entities/{id}
POST   /v3/world/observations
POST   /v3/world/sync-project
GET    /v3/jarvis/context
GET    /v3/jarvis/resolve
WS     /v3/world/stream
```

Mutation and Jarvis-facing surfaces remain behind the ForgeCAD session boundary.

---

# Safety and trust invariants

ForgeCAD 3.0 deliberately preserves the following boundaries:

1. **Canonical identity** — a model may not invent an authoritative ID for an existing entity.
2. **SI at the world boundary** — world-space physical state uses SI; engineering-source units are converted explicitly.
3. **No silent truth collapse** — designed state, observed state, human declarations, and inference remain distinguishable.
4. **Explicit CAD bridge** — a world entity affects CAD only through an explicit engineering source link.
5. **No agent self-certification** — Jarvis may propose, simulate, and infer, but cannot self-verify high-severity physical safety claims.
6. **Confirmation at physical boundaries** — consequential capability execution is confirmation-gated and audited.
7. **Local first** — world/model/project persistence remains useful without a cloud service.
8. **Backward compatibility** — the world model is additive to the existing engineering core.

---

# Release validation

ForgeCAD is not considered healthy merely because the UI renders or an installer can be produced.

The 3.0 release regression covers the inherited engineering stack plus:

- persistent world schema/store behavior;
- hierarchy-cycle rejection;
- stable project-to-world identity;
- mm-to-m world projection;
- stale projected-entity cleanup;
- provenance/live-state persistence;
- deterministic entity resolution and ambiguity rejection;
- planner world-context injection;
- explicit CAD source-link enforcement;
- event catch-up and live WebSocket push;
- expired-cursor reset semantics;
- capability argument validation;
- confirmation requirements for physical actions;
- adapter binding and audit behavior;
- v3 HTTP/Jarvis surfaces;
- desktop SYSTEM browser behavior.

The Windows and macOS release workflows then build the bundled Forge Engine and test the **packaged / installed application**, not only the source tree.

See [`docs/RELEASE_3_0.md`](docs/RELEASE_3_0.md) for the exact workflow runs, artifact IDs, sizes, and SHA-256 digests used to close 3.0.0.

---

# Deliberate limitations

ForgeCAD 3.0.0 does **not** claim to provide:

- general-purpose visual SLAM;
- perfect object recognition or person identification;
- unrestricted autonomous robot control;
- arbitrary smart-home integration;
- universal hardware drivers;
- continuous building-scale digital-twin simulation;
- general CFD;
- continuous general multibody dynamics;
- universal PCB/electronics signoff;
- autonomous purchasing;
- autonomous fabrication without confirmation;
- regulatory certification;
- guaranteed manufacturing success;
- movie-style volumetric holography;
- technologies beyond contemporary physics and manufacturing.

These are later-system problems. 3.0 ships the identity/provenance/state/capability substrate required to approach them without inventing a second incompatible physical model.

---

# Architecture

## Desktop

**Stack:** Electron + React + TypeScript + Three.js + Monaco

Responsibilities include 3D visualization, engineering interaction, component browsing, code, history, analysis, manufacturing/evidence surfaces, and physical-world inspection.

## Forge Engine

**Stack:** Python 3.12+, FastAPI, Pydantic, CadQuery 2.6.1/OpenCascade, NumPy, SciPy

Responsibilities include canonical project state, the Physical World Model, deterministic operations, component registry, geometry, engineering solvers, validation, history, import/export, manufacturing evidence, Jarvis context, capability contracts, and local APIs.

## Local model runtime

Current development commonly uses **Ollama**. The configured model is an explicit host setting. Models propose reasoning/plans and use typed tools; they are not the canonical database or final authority for deterministic solver results.

---

# Repository layout

```text
CAD-for-Jarvis/
├── apps/
│   └── desktop/                 # Electron + React + TypeScript desktop
├── services/
│   └── forge-engine/            # Python engineering + physical-world service
├── packages/                    # Shared workspace packages/contracts
├── docs/
│   ├── PRODUCT_SPEC.md
│   ├── ROADMAP_3_0.md
│   ├── RELEASE_3_0.md
│   ├── FRONTEND_ARCHITECTURE.md
│   ├── INTERACTION_CONTRACTS.md
│   └── reference/
├── scripts/
├── .github/
│   └── workflows/
├── package.json
└── README.md
```

The 3.0 release contract and future trajectory are documented in [`docs/ROADMAP_3_0.md`](docs/ROADMAP_3_0.md).

---

# Development

## Requirements

- Node.js **22+**
- pnpm **10.15.1**
- Python **3.12+**
- supported local Ollama installation/model for AI-assisted workflows
- platform build dependencies required by Electron/CadQuery

## macOS

```bash
pnpm dev:macos
```

## Windows

```powershell
pnpm dev:windows
```

## Common workspace commands

```bash
pnpm dev
pnpm build
pnpm typecheck
pnpm test
pnpm lint
```

The Forge Engine can also be installed directly from `services/forge-engine` for backend development.

---

# Where this goes next

ForgeCAD 3.0 moves the project from “AI CAD” toward a shared physical intelligence substrate.

The next layers can now build on one authoritative representation instead of inventing parallel state:

```text
ForgeCAD 2.x
    engineering workstation
        ↓
ForgeCAD 3.0
    persistent physical world model
    deterministic identity/provenance/state/capabilities
        ↓
Perception + real device adapters
        ↓
Closed-loop autonomous engineering
        ↓
Fabrication/test feedback
        ↓
Spatial interfaces + persistent bounded autonomy
```

The functional benchmark remains:

> **Tell Jarvis what you want to accomplish in the physical world. Jarvis understands the relevant real environment, resolves the actual systems involved, uses ForgeCAD to design or modify what is necessary, predicts consequences before acting, asks for confirmation at meaningful boundaries, executes through typed capabilities, observes the result, and updates its model from evidence.**

ForgeCAD 3.0.0 is the first release in which that physical-world substrate is implemented rather than merely described.