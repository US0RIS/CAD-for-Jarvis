# ForgeCAD

> **An AI-native, local-first physical engineering environment and physical-world substrate for Jarvis.**

ForgeCAD combines editable CAD, real purchased components, embedded software, assembly constraints, deterministic engineering analysis, design lineage, manufacturing preparation, physical evidence, external solvers, and a persistent model of deployed physical reality in one canonical engineering system.

The product objective is not “a chatbot attached to CAD.” It is an environment in which a user or Jarvis can describe a physical product or mechanism in natural language and carry the same engineering identity from requirements through architecture, real components, custom geometry, code, analysis, procurement, manufacturing, physical testing, and deployed state without losing provenance or silently replacing unknowns with guesses.

---

## Status

**Current release:** ForgeCAD **6.1.0**  
**Release branch:** `forgecad/6.1.0`  
**Desktop package version:** `6.1.0`

ForgeCAD 6.1.0 is the simulation release for the complete 6.x engineering environment. It preserves the validated 6.0/6.0.1 product substrate and makes constrained multibody motion, simulation provenance, viewport playback, and built-in multiphysics analysis first-class parts of the same canonical engineering model.

Release documentation:

- [`docs/RELEASE_6_1_0.md`](docs/RELEASE_6_1_0.md) — 6.1 simulation scope, fidelity/truth boundaries, native artifacts, and acceptance gates;
- [`docs/RELEASE_6_0_1.md`](docs/RELEASE_6_0_1.md) — preserved 6.0.1 UX/runtime substrate;
- [`docs/UX_AUDIT_6_0_1.md`](docs/UX_AUDIT_6_0_1.md) — desktop UX audit and information-architecture decisions;
- historical release documents under [`docs/`](docs/) remain the record for earlier milestones.

ForgeCAD 6.1.0 remains a **software engineering release**, not a claim that a particular physical device has been built, tested, certified, or made safe merely because the software passes its release gates.

---

# What ForgeCAD 6.1.0 adds

## Executable assembly motion

Canonical joints now drive complete rigid subtrees rather than isolated meshes. Supporting-body transforms and explicit joint actuation preserve downstream continuity, while unsupported topology fails closed. Time-domain sweeps produce sampled assembly poses, body kinematics, swept bounds, load-path evidence, and sampled exact-B-rep penetration checks.

The 3D viewport can play calculated sweep frames without mutating the canonical design. After playback, ForgeCAD restores the exact design pose. Interactive transforms of supporting bodies use the same continuity model.

## One simulation provenance model

Analyze exposes motion, gravity/load paths, structural FEA, rigid-body response, steady hydraulic networks, thermal analysis, and aerodynamic screening through the 6.1 simulation layer. Results are recorded against the exact design fingerprint and become stale when relevant canonical state changes.

Solver identity, version, grade, assumptions, limitations, and prediction-vs-observation boundaries remain explicit. Missing physics is not silently replaced with a plausible-looking answer.

## Thermal simulation at two scales

ForgeCAD 6.1.0 preserves the assembly transient thermal network for inter-part heat flow and adds a separate 3D transient thermal-field solver for supported unfeatured rectangular box solids. The field solver resolves internal conduction gradients with volumetric heat generation, convection, radiation, explicit numerical-stability control, field output, and energy-balance evidence. Unsupported geometry fails closed.

## Aerodynamic truth boundary

The built-in aerodynamic solver is an integrated coefficient-based engineering screening model. It is explicitly **not CFD**. Optional OpenFOAM availability remains separately reported and does not imply a validated automatic CAD-to-CFD case adapter.

For exact release scope and installer names, see [`docs/RELEASE_6_1_0.md`](docs/RELEASE_6_1_0.md).

---

# Preserved ForgeCAD 6.0.1 substrate

## 1. Natural-language engineering over canonical state

Engineering Copilot can inspect or modify the active design while operating against the same typed engineering model used by the CAD viewport, validation, history, branches, code workspaces, manufacturing, and physical evidence.

The desktop makes agent state explicit: task submission, planning, applying, analysis, verification, completion, failure, and cancellation are visible rather than implied. Offline local-AI state fails clearly and preserves the user's draft.

Agent and non-agent engineering jobs are tracked independently so a simulation or variant campaign cannot overwrite the visible status of an active Copilot task.

## 2. Real components plus custom editable CAD

The component library represents real purchased hardware with manufacturer/model identity, specifications, provenance, geometry fidelity, pricing where known, and engineering interfaces.

Purchased component identity and supplier-backed geometry are treated as engineering truth, not disposable starter meshes. ForgeCAD does not silently turn a purchased Raspberry Pi, motor, sensor, fastener, or other sourced component into arbitrary editable custom geometry.

Fabricated and imported custom parts expose **Parametric CAD** in Object Properties. Their feature history supports editable operations such as holes, slots, fillets, chamfers, shelling, suppression, reorder, duplication, and deletion through the canonical Forge Engine feature model.

## 3. Assemblies are engineering constraints, not visual grouping

ForgeCAD models explicit mechanical interfaces, full interface-frame mates, joints, mobility, redundant constraints, mounting geometry, mounting hardware, access envelopes, and collision/interference evidence.

The 6.0 assembly substrate includes fixed and prismatic interface-frame constraints, constraint-rank and mobility analysis, geometry-backed mounting patterns, manufacturer mounting datums and registration, mount hardware realization, driver/access-envelope checks, and kinematic/collision screening.

When topology or mounting truth is ambiguous, the system fails closed rather than inventing a plausible physical relationship.

## 4. Electrical, thermal, fluid, routing, safety, and kinematics share one model

The Analyze workspace exposes deterministic domain evidence from the active canonical branch: electrical nets and compatibility; thermal networks; hydraulic pressure/flow networks; cable/tube routing; safety/failure modes; kinematics and interference; and structural, tolerance, manufacturing, and requirement-gate evidence.

A domain is shown as PASS only when the underlying analysis explicitly asserts a pass. Modeled-but-unasserted evidence remains modeled, and missing inputs remain missing.

## 5. Release-level assembly, solver, and evidence state is visible

The Analyze-side **Assembly, evidence & solver state** inspector exposes confirmed state for assembly constraints and mounts, engineering repair trials, physical retest lineage, test runs and metrology, external solver inventory, chemistry studies/runs, and release-stage truth boundaries.

The panel is deliberately an evidence inspector. It never converts a branch label, solver result, CI fixture, fabrication archive, or package hash into physical verification.

## 6. Branches preserve complete engineering state

ForgeCAD branches are not merely CAD geometry variants. A branch snapshots the canonical engineering state, including embedded code and the engineering identities needed by downstream analysis and evidence.

Design Lineage supports creating experimental branches, switching branches, marking a design working/not working/unverified, comparing canonical differences, and preserving independent physical-evidence state. A “working” label is a design-management label only. It is not physical verification.

## 7. Embedded software belongs to the physical product

Programmable components expose their embedded code directly inside ForgeCAD. Code saves are serialized, and branch/project mutations wait for pending editor writes before canonical state changes, preventing a fast branch switch from silently placing code on the wrong design revision.

## 8. Manufacturing remains connected to design intent

Manufacturing preparation is part of the same engineering thread. ForgeCAD can screen parts against manufacturing resources, inspect print/build-volume constraints, orientation, wall-thickness and support implications, split oversized geometry, and hand problematic parts back to Copilot for redesign while preserving the part's functional role and interfaces.

Manufacturing files and hashes establish digital package identity. They do not establish physical specimen authenticity by themselves.

## 9. Physical testing is revision-bound evidence

ForgeCAD models physical retest cycles, artifact contracts, metrology contracts, specimen identity, fabrication-package lineage, test-run execution, prediction residuals, and requirement-scoped completion.

The governing rule is strict:

```text
physical evidence applies only to the exact engineering fingerprint that was actually tested
```

A passing retest verifies only its scoped requirement. It does not silently mark the whole design physically verified.

## 10. External solvers fail closed

ForgeCAD can integrate controlled external engineering solvers. The 6.0 substrate includes a validated Cantera chemistry path plus capability reporting for optional tools such as CalculiX, OpenFOAM, and Gmsh.

Solver availability is reported truthfully. Missing solvers do not trigger invented physics or an unannounced lower-fidelity substitute, and the presence of an executable does not by itself mean ForgeCAD has a validated model-to-case adapter for every problem.

## 11. Physical World Model and Jarvis integration

ForgeCAD maintains a persistent physical graph alongside canonical design state. World entities can represent sites, rooms, machines, assemblies, components, devices, interfaces, capabilities, live state, software, and source links back to ForgeCAD engineering objects.

The key epistemic invariant is:

```text
designed truth != observed state != inference
```

Live observations update observed state. They do not rewrite supplier specifications or canonical CAD. Jarvis identity resolution fails closed when the physical entity or CAD source link is ambiguous.

---

# Desktop information architecture

ForgeCAD separates responsibilities:

- **Model / Copilot (left):** object tree, branch navigation, and natural-language engineering interaction.
- **3D canvas (center):** authoritative physical artifact view, selection, constrained editing, and simulation playback.
- **History / Code / Simulation / System (bottom):** chronology, programmable hardware, long-running engineering jobs, and deployed/physical state.
- **Properties (right):** object identity, fabricated-part parametric CAD, design truth, and branch lineage.
- **Components (right):** real-world component sourcing and insertion.
- **Analyze (right):** simulation, deterministic validation, cross-domain evidence, variant campaigns, and solver state.
- **Manufacture (right):** manufacturing-resource checks, build preparation, splitting, and redesign handoff.

At the packaged minimum desktop size of **1280×760**, core application chrome and the primary Code/System workspaces are covered by browser acceptance.

---

# Truth and safety boundaries

ForgeCAD 6.1.0 keeps these invariants non-negotiable:

1. Purchased component engineering data remains immutable inside a design revision.
2. Unknown engineering input remains unknown.
3. Designed truth, observed state, and inference remain distinct.
4. Branch status is not physical verification.
5. Physical evidence is revision/fingerprint bound.
6. Simulation and external-solver evidence cannot silently survive a mutation that makes it stale.
7. Unsupported or missing physics fails closed.
8. A fabrication-package hash proves digital package identity, not physical specimen identity.
9. CI physical fixtures are synthetic contract tests, not real-hardware validation.
10. Software release success is not certification of a physical product.

---

# 6.1.0 release gates

The release branch publishes only after all current-head gates succeed:

- ForgeCAD 6.1 multibody/multiphysics source acceptance;
- deterministic 3D thermal-field acceptance;
- preserved v2 physics and 6.0.1 runtime-hardening regressions;
- HTTP-level execution of 6.1 simulation endpoints;
- desktop TypeScript typecheck, unit tests, and production build;
- Chromium acceptance for joint controls, viewport playback, canonical-pose preservation, and 3D thermal-field UI;
- preserved 6.0 cross-domain and external chemistry gates in native release validation;
- native Windows x64 installed-copy/launch validation;
- native macOS arm64 and x64 installed-copy/launch validation;
- packaged Forge Engine 6.1 simulation identity, Cantera availability, and 3D thermal-field runtime validation;
- SHA-256 manifest and exact release-tag/source binding.

See [`docs/RELEASE_6_1_0.md`](docs/RELEASE_6_1_0.md) for the release record and artifact names.

---

# Repository layout

```text
apps/desktop/                         Electron + React ForgeCAD desktop
services/forge-engine/               Canonical local engineering runtime
services/forge-engine/forge_engine/  Versioned engineering capability layers
packages/                             Shared packages where applicable
docs/                                 Release, engineering, and validation records
.github/workflows/                    Browser, regression, and native release gates
```

The 6.x architecture deliberately builds on the validated 3.1 substrate rather than rewriting previously proven behavior without equivalent or stronger acceptance coverage.

---

# Development

From the repository root:

```bash
pnpm install
pnpm --filter @forgecad/desktop typecheck
pnpm --filter @forgecad/desktop test
pnpm --filter @forgecad/desktop build
```

Forge Engine is developed from `services/forge-engine`. Release and acceptance workflows define the exact runtime environment used for 6.1.0 validation.

For the complete release-specific truth contract, do not infer from a successful local UI launch alone; use the release selftests and GitHub Actions gates recorded for the release branch.
