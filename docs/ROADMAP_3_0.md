# ForgeCAD 3.0.0 — Physical World Model

Status: **COMPLETE / release-validated**

Release branch: `forgecad/3.0.0`

Runtime-validated source SHA: `a5ae8ad5ecc6622498df1e3c8c3688c31ded0afe`

Release evidence: [`RELEASE_3_0.md`](RELEASE_3_0.md)

ForgeCAD 2.x established the AI-native engineering workstation: canonical CAD/component state, embedded code, deterministic analysis, branch lineage, manufacturing preparation, physical evidence, and Jarvis-accessible engineering APIs.

ForgeCAD 3.0 changes the unit of abstraction. It adds a persistent **Physical World Model (PWM)** so Jarvis and ForgeCAD can reason about stable real-world identity, hierarchy, pose, interfaces, capabilities, live observations, provenance, and authoritative engineering-source links through one shared representation.

The release makes this statement materially true:

> Jarvis can refer to a physical thing by stable identity, know where it is in a hierarchy and coordinate frame, know what it can do and how it is connected, distinguish designed state from observed live state, preserve provenance/confidence, and use ForgeCAD engineering state as the authoritative digital twin for designed systems.

The governing invariant is:

```text
designed truth != observed state != inference
```

---

## 1. Completed 3.0 scope

### 1.1 Persistent world entities — COMPLETE

The PWM stores persistent world entities with:

- stable IDs;
- name and semantic kind;
- parent/child hierarchy;
- coordinate frame and 6-DoF pose;
- capabilities;
- physical/software interfaces;
- live state;
- provenance and confidence;
- ForgeCAD project/object/component source links;
- timestamps and revision metadata.

Supported semantic kinds remain extensible and include world, site, building, room, zone, machine, assembly, component, device, sensor, actuator, tool, fixture, material, and generic object.

### 1.2 Spatial hierarchy and coordinate frames — COMPLETE

Nested coordinate frames are supported. ForgeCAD project transforms are projected from the engineering millimeter frame into SI world coordinates explicitly.

The authoritative engineering transform remains available through source metadata rather than being silently replaced by an observation.

Hierarchy-cycle rejection is deterministic and regression-tested.

### 1.3 Capability and interface ontology — COMPLETE

3.0 defines queryable capability contracts rather than one-off control scripts.

Implemented capability vocabulary includes composable names such as:

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

Interfaces remain explicit physical/software connection points and preserve source IDs when projected from ForgeCAD components.

### 1.4 Live state and observation ingestion — COMPLETE

World observations preserve:

- value;
- unit;
- observation time;
- source class;
- source identity;
- confidence;
- metadata.

Observations update live state only. They do not rewrite canonical CAD or component engineering data.

### 1.5 Provenance and epistemic state — COMPLETE

The world model distinguishes:

- authoritative ForgeCAD design state;
- human-declared state;
- direct sensor observations;
- Jarvis inference;
- imported external data.

Confidence is explicit and bounded. Unknown remains unknown.

### 1.6 Automatic ForgeCAD project projection — COMPLETE

The active ForgeCAD project projects into the PWM with:

- a project/assembly entity;
- one entity per project object;
- deterministic IDs;
- hierarchy and pose;
- programmable-device capabilities;
- frozen component interfaces;
- component references and engineering roles;
- canonical project connections as world relations;
- branch/revision provenance.

Repeated sync preserves identity. Project mutations refresh the projection automatically. Stale projected entities are removed when their source object is deleted.

### 1.7 Jarvis-facing world API — COMPLETE

Supported deterministic surfaces include world snapshot/entity/relation lookup, hierarchy and capability filtering, observations, explicit project sync, compact Jarvis context, deterministic identity resolution, event history, and authenticated event streaming.

Jarvis/session authentication remains at the existing ForgeCAD bridge boundary.

### 1.8 Desktop SYSTEM world inspector — COMPLETE

The desktop SYSTEM workspace exposes:

- world health;
- entity/relation counts;
- project-sync status;
- selected entity identity;
- design source links;
- capabilities;
- interfaces;
- live state;
- provenance/confidence;
- relations.

A dedicated production-like browser gate verifies this surface end-to-end.

### 1.9 World-aware engineering context — COMPLETE

The engineering planner can receive deterministic world context for resolved real entities.

The planner keeps world IDs separate from CAD IDs. A world entity can affect CAD only through an explicit `source_links.forgecad_object_id` bridge.

Identity resolution fails closed on ambiguity and does not invent authoritative IDs from fuzzy similarity.

### 1.10 Event/change subscriptions — COMPLETE

The PWM maintains bounded timestamped event history for entity, relation, sync, and observation changes.

3.0 includes:

- incremental event retrieval;
- revision/cursor state;
- authenticated WebSocket push;
- deterministic catch-up from a previous event ID;
- explicit reset behavior when a cursor is no longer retained.

### 1.11 Capability action safety runtime — COMPLETE

The 3.0 capability runtime enforces:

- explicit adapter binding;
- argument contracts;
- fail-closed behavior for unbound actions;
- confirmation boundaries for consequential physical actions;
- rejection of missing or incorrect confirmations;
- expiry of pending physical confirmation across restart;
- persistent action audit state.

This is a safety/control substrate, not a universal device-driver ecosystem.

---

## 2. Release acceptance — COMPLETE

Every committed 3.0 release criterion is satisfied.

- **Existing engineering regression:** PASS
- **PWM persistence and invariants:** PASS
- **Stable project projection:** PASS
- **Automatic project-to-world refresh:** PASS
- **Deterministic Jarvis identity/capability/state lookup:** PASS
- **Live state cannot overwrite canonical design truth:** PASS
- **World persistence across restart:** PASS
- **Desktop SYSTEM world inspection:** PASS
- **`.focad` backward compatibility:** PASS
- **Windows packaged v3 validation:** PASS
- **macOS x64 packaged v3 validation:** PASS
- **macOS arm64 packaged v3 validation:** PASS
- **Release documentation distinguishes implemented behavior from later ambitions:** PASS

Exact workflow runs and installer digests are recorded in [`RELEASE_3_0.md`](RELEASE_3_0.md).

---

## 3. Regression invariants

The release is guarded by deterministic self-tests covering:

- world persistence;
- hierarchy-cycle rejection;
- deterministic project identity;
- mm-to-m projection;
- stale projected-entity cleanup;
- observation persistence;
- exact/source-link/hierarchy identity resolution;
- ambiguity and fuzzy-match fail-closed behavior;
- planner world-context injection;
- explicit engineering source-link enforcement;
- WebSocket authentication;
- event catch-up/live push;
- expired-cursor reset semantics;
- capability confirmation policy;
- action argument validation;
- unbound-action rejection;
- audit persistence;
- v3 API behavior;
- desktop browser acceptance.

The complete inherited ForgeCAD engineering regression remains part of the same release gate.

---

## 4. Explicitly not claimed by 3.0

ForgeCAD 3.0.0 does not claim:

- general-purpose visual SLAM;
- perfect object recognition or person identification;
- unrestricted autonomous robot control;
- arbitrary smart-home integration;
- universal device drivers;
- continuous multibody/digital-twin simulation of an entire building;
- autonomous purchasing;
- autonomous fabrication without confirmation;
- regulatory or safety certification;
- movie-style volumetric holography.

3.0 establishes the stable identity, provenance, capability, state, and engineering-source contracts needed to build those later layers coherently.

---

## 5. Architectural invariants

### Canonical identity

A model does not generate a free-form authoritative ID when an authoritative entity already exists. Deterministic source mappings own identity.

### SI at the world boundary

The PWM uses SI units for world-space physical state. Existing CAD/project units remain valid in the engineering source and are converted explicitly at projection boundaries.

### No silent truth collapse

Designed state, measured state, human input, and inferred state remain distinguishable.

### Explicit design bridge

A world entity is design-addressable only through an explicit engineering source link. World identity is not silently reused as CAD identity.

### No agent self-certification

Jarvis/ForgeCAD may propose, simulate, and infer. Physical verification and high-severity safety verification remain separate evidence classes.

### Bounded physical execution

Consequential capability execution remains confirmation-gated, typed, and auditable.

### Local-first persistence

The world model persists locally by default and remains useful without a cloud service.

### Backward compatibility

Existing ForgeCAD 2.x project and `.focad` contracts remain usable. The PWM is additive rather than a rewrite of the engineering core.

---

## 6. Post-3.0 trajectory

The following are deliberately future work rather than hidden 3.0 scope:

1. real device adapters for Raspberry Pi / ESP32 / local services;
2. camera/perception adapters producing world observations;
3. explicit uncertainty/staleness policy by state type;
4. non-CAD world overlays in the 3D scene;
5. world-aware autonomous campaign objectives;
6. deployment state for programmable devices;
7. closed-loop tests where live evidence invalidates a design assumption and proposes a revision;
8. fabrication and calibration feedback;
9. spatial/AR interfaces;
10. persistent bounded autonomous operation.

The architectural progression is now:

```text
ForgeCAD 2.x
    engineering workstation
        ↓
ForgeCAD 3.0
    persistent physical world model
    + deterministic identity/provenance/state/capabilities
        ↓
Perception + real device control
        ↓
Closed-loop autonomous engineering
        ↓
Fabrication/test feedback
        ↓
Spatial interfaces + persistent bounded autonomy
```

The long-term benchmark remains:

> A user describes a physical objective. Jarvis understands the relevant real environment, resolves the actual systems involved, uses ForgeCAD to design or modify what is necessary, predicts consequences before acting, asks for confirmation at meaningful boundaries, executes through typed capabilities, observes the result, and updates its model from evidence.

ForgeCAD 3.0.0 is the release where the persistent physical-world substrate required for that architecture became implemented and release-validated.