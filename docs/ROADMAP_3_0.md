# ForgeCAD 3.0.0 — Physical World Model

Status: **active development target**

Branch: `forgecad/3.0.0`

ForgeCAD 2.0 established an AI-native engineering workstation: canonical CAD and component state, code attached to hardware, deterministic analysis, design branches, manufacturing preparation, evidence, and Jarvis-accessible engineering APIs.

ForgeCAD 3.0 changes the unit of abstraction.

The primary 3.0 objective is to make ForgeCAD the first practical version of **Jarvis's persistent model of physical reality** rather than only a model of the design currently open in a CAD project.

The release should make this statement materially true:

> Jarvis can refer to a physical thing by stable identity, know where it is in a hierarchy and coordinate frame, know what it can do and how it is connected, distinguish designed state from observed live state, preserve provenance/confidence, and use ForgeCAD engineering state as the authoritative digital twin for designed systems.

3.0 is not intended to complete the entire long-term JARVIS vision. It establishes the substrate on which perception, robotics, fabrication feedback, and persistent autonomous operation can be built without inventing a second incompatible representation of the physical world.

---

## 1. Release thesis

ForgeCAD 3.0 adds a canonical **Physical World Model (PWM)** alongside the existing project model.

The world model is a persistent graph:

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

A ForgeCAD design is projected into this graph as an authoritative designed system. Real observations can then update live state without rewriting design truth. Jarvis consumes the same graph rather than maintaining a separate ad-hoc device inventory.

The critical distinction is:

```text
designed truth != observed state != inference
```

ForgeCAD must preserve that distinction explicitly.

---

## 2. 3.0.0 committed scope

### 2.1 Persistent world entities

Every world entity has a stable identity and may carry:

- name and semantic kind;
- parent/child hierarchy;
- coordinate frame and 6-DoF pose;
- capabilities;
- physical/software interfaces;
- live state values;
- provenance and confidence;
- links back to ForgeCAD project/object/component identity;
- timestamps and revision metadata.

Initial semantic kinds include world, site, building, room, zone, machine, assembly, component, device, sensor, actuator, tool, fixture, material, and generic object. The schema remains extensible rather than enforcing a closed ontology prematurely.

### 2.2 Spatial hierarchy and coordinate frames

The PWM must support nested coordinate frames. A component's pose can be expressed relative to an assembly; an assembly can be expressed relative to a machine; a machine can be expressed relative to a room.

ForgeCAD project transforms are converted from the project's millimeter engineering frame into SI world coordinates when projected into the PWM. The original engineering transform remains represented by provenance/source metadata and is never silently replaced by a sensor estimate.

### 2.3 Capability and interface ontology

Jarvis should reason about what a device **can do**, not which one-off Python script controls it.

Initial capability naming follows composable names such as:

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

Capabilities may include constraints and metadata. Interfaces remain explicit physical/software connection points and retain exact source IDs when projected from ForgeCAD components.

3.0 defines this contract and makes it queryable. A large hardware-driver ecosystem is not required for 3.0, but future drivers must bind to this contract rather than bypass it.

### 2.4 Live state and observation ingestion

A perception system, device bridge, or human may submit an observation against a world entity.

Every state sample records:

- value;
- unit when applicable;
- observation time;
- source class and source identity;
- confidence;
- optional metadata.

Observations update **live state**, not canonical CAD or component engineering data.

This is the first perception-facing contract for future cameras, microphones, environmental sensors, robots, HomeKit/device telemetry, and vision pipelines.

### 2.5 Provenance and epistemic state

Unknown remains unknown.

The world model must distinguish at minimum:

- authoritative ForgeCAD design state;
- human-declared state;
- direct sensor observation;
- Jarvis inference;
- imported external data.

Confidence is explicit and bounded. Inference may not overwrite a more authoritative source merely because it is newer.

### 2.6 Automatic ForgeCAD project projection

The active ForgeCAD project is automatically projected into the world model.

At minimum, projection includes:

- one world entity for the active project/assembly;
- one entity for every project object;
- project hierarchy;
- object pose;
- programmable-device capabilities;
- frozen component interfaces;
- component references and engineering roles;
- canonical project connections as world relations;
- branch/revision provenance.

Project entities use deterministic IDs so project edits update the same world identities rather than producing duplicates.

Project mutation through existing `/v2` APIs must refresh this projection automatically.

### 2.7 Jarvis-facing world API

3.0 exposes deterministic APIs for:

- world snapshot;
- entity lookup;
- hierarchy traversal/filtering;
- capability filtering;
- relation lookup;
- live-state observation ingestion;
- explicit project-to-world synchronization;
- compact Jarvis context generation.

Jarvis authentication continues to use the existing bridge/session model.

### 2.8 Desktop world/system surface

Before 3.0 release, the desktop SYSTEM experience should expose at least:

- current world-model health;
- entity count and source breakdown;
- selected entity identity;
- design vs live state;
- capabilities/interfaces;
- provenance/confidence;
- connected relations;
- sync status with the active ForgeCAD design.

The desktop does not need to become a full GIS/SLAM application in 3.0.

### 2.9 World-aware engineering context

The engineering agent should be able to receive relevant world context when the user refers to a known real entity. A request such as "make the bench robot's gripper close faster" should be resolvable to a stable world entity and from there to its ForgeCAD design source where available.

This must remain deterministic at the identity-resolution layer. The model may reason about intent but must not invent entity IDs.

### 2.10 Event/change stream

The PWM maintains a bounded, timestamped event history for entity, relation, sync, and observation changes. Jarvis should be able to determine what changed without diffing entire world snapshots continuously.

---

## 3. 3.0 stretch scope

These items belong in 3.0 only if the committed scope is solid and regression-tested:

- pluggable device adapters that execute capability operations against Raspberry Pi/ESP32/local services;
- camera/perception adapters producing object observations;
- explicit uncertainty/staleness policy by state type;
- scene overlay showing world entities that are not native CAD parts;
- world-aware autonomous campaign objectives;
- deployment state for programmable devices;
- first closed-loop prototype test where a live measurement invalidates a design assumption and creates a proposed revision.

They are not allowed to weaken the canonical world model in order to ship faster.

---

## 4. Explicitly not required for 3.0

ForgeCAD 3.0 does **not** claim to provide:

- general-purpose visual SLAM;
- perfect object recognition or person identification;
- unrestricted autonomous robot control;
- arbitrary smart-home integration;
- continuous multibody/digital-twin simulation of an entire building;
- autonomous purchasing;
- autonomous fabrication without confirmation;
- movie-style holography;
- safety certification;
- a universal robotics stack.

Those become tractable only after stable identity, provenance, capability, state, and engineering-source contracts exist.

---

## 5. Architectural invariants

### Canonical identity

World identity is never a model-generated free-form string when an authoritative entity already exists. Deterministic source mappings own identity.

### SI at the world boundary

The PWM uses SI units for world-space physical state. Existing CAD/project units remain valid inside their engineering source and are converted explicitly at projection boundaries.

### No silent truth collapse

Designed state, measured state, human input, and inferred state remain distinguishable.

### No agent self-certification

Jarvis/ForgeCAD may propose, simulate, and infer. Physical verification, high-severity safety verification, and authoritative human declarations remain separate evidence classes.

### Local-first persistence

The world model persists locally by default and must remain useful without a cloud service.

### Backward compatibility

Existing ForgeCAD 2.x project and `.focad` contracts remain usable. The PWM is additive; it does not rewrite the entire 2.x engineering core.

---

## 6. Initial 3.0 API contract

The first vertical slice targets:

```text
GET    /v3/health
GET    /v3/world
GET    /v3/world/entities
GET    /v3/world/entities/{id}
POST   /v3/world/entities
PUT    /v3/world/entities/{id}
DELETE /v3/world/entities/{id}
POST   /v3/world/observations
POST   /v3/world/sync-project
GET    /v3/jarvis/context
```

All mutation endpoints use the existing ForgeCAD/Jarvis session boundary.

---

## 7. First vertical-slice acceptance test

The first 3.0 engineering test must prove, without an LLM, that ForgeCAD can:

1. create a persistent physical world;
2. create a room and machine hierarchy;
3. reject hierarchy cycles;
4. ingest a timestamped sensor observation with confidence and provenance;
5. project the deterministic ForgeCAD acceptance assembly into the world;
6. preserve stable world IDs across repeated project synchronization;
7. convert project millimeter transforms into world meters;
8. expose Raspberry Pi compute/software capabilities;
9. expose canonical component interfaces;
10. translate ForgeCAD connections into world relations;
11. remove stale projected entities when a project object is removed;
12. persist and reload the complete graph without identity loss.

This test becomes part of the 3.0 regression gate.

---

## 8. 3.0 release acceptance

ForgeCAD 3.0.0 is not complete until all of the following are true:

- every ForgeCAD 2.0 engineering regression remains green;
- PWM persistence and invariants are deterministic and green on Windows/macOS;
- project projection updates automatically after project mutations;
- Jarvis can query stable entity identity/capabilities/state through the supported bridge;
- live observations cannot overwrite canonical design truth;
- world state survives restart;
- desktop SYSTEM UI exposes useful world-model state;
- `.focad` import/export continues to behave correctly;
- packaged Windows and macOS applications exercise the v3 health/world surface;
- the release README clearly distinguishes implemented 3.0 behavior from later JARVIS ambitions.

---

## 9. Development order

The planned implementation sequence is:

1. **PWM schema + persistent store + deterministic self-test**
2. **ForgeCAD project projection + canonical relation projection**
3. **v3 HTTP/Jarvis surface + automatic project synchronization**
4. **capability/device contract**
5. **desktop SYSTEM world inspector**
6. **world-aware Jarvis/engineering context resolution**
7. **event/change subscriptions**
8. **packaged cross-platform release gates**
9. stretch integrations only after the above are stable

---

## 10. The larger trajectory

ForgeCAD 3.0 is the bridge between "AI CAD" and the larger Jarvis architecture.

The intended progression after 3.0 is:

```text
ForgeCAD 2.x
    engineering workstation
        ↓
ForgeCAD 3.x
    persistent physical world model + Jarvis identity/capability/state substrate
        ↓
Perception + universal device control
        ↓
Closed-loop autonomous engineering
        ↓
Fabrication/test feedback
        ↓
Spatial/AR interfaces + persistent autonomous operation
```

The long-term benchmark remains simple to state even if difficult to achieve:

> A user describes a physical objective. Jarvis understands the relevant real environment, resolves the real systems involved, uses ForgeCAD to design or modify what is necessary, predicts consequences before acting, asks for confirmation at meaningful boundaries, executes through typed capabilities, observes the result, and updates its model from evidence.

ForgeCAD 3.0 is where that stops being merely a product vision and starts becoming a concrete system architecture.
