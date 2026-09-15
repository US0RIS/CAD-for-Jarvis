# ForgeCAD

> **An AI-native, local-first physical engineering environment and physical-world substrate for Jarvis.**

ForgeCAD combines editable CAD, real purchased components, embedded software, assembly constraints, deterministic engineering analysis, design lineage, manufacturing preparation, physical evidence, external solvers, and a persistent model of deployed physical reality in one canonical engineering system.

The product objective is not “a chatbot attached to CAD.” It is an environment in which a user or Jarvis can describe a physical product or mechanism in natural language and carry the same engineering identity from requirements through architecture, real components, custom geometry, code, analysis, procurement, manufacturing, physical testing, and deployed state without losing provenance or silently replacing unknowns with guesses.

---

## Status

**Current release:** ForgeCAD **6.0.1**  
**Release branch:** `forgecad/6.0.1`  
**Desktop package version:** `6.0.1`

ForgeCAD 6.0.1 is the UX, interaction-correctness, and runtime-hardening release for the complete 6.0 engineering environment. It preserves the validated 6.0 capability substrate while making previously hidden or ambiguous workflows first-class desktop interactions.

Release documentation:

- [`docs/RELEASE_6_0_1.md`](docs/RELEASE_6_0_1.md) — release scope, truth boundaries, native artifacts, and acceptance gates;
- [`docs/UX_AUDIT_6_0_1.md`](docs/UX_AUDIT_6_0_1.md) — full desktop UX audit and information-architecture decisions;
- historical release documents under [`docs/`](docs/) remain the record for earlier milestones.

ForgeCAD 6.0.1 remains a **software engineering release**, not a claim that a particular physical device has been built, tested, certified, or made safe merely because the software passes its release gates.

---

# What ForgeCAD 6.0.1 is

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

The 6.0 assembly substrate includes:

- fixed and prismatic interface-frame constraints;
- constraint-rank and mobility analysis;
- geometry-backed mounting patterns;
- manufacturer mounting datums and registration;
- mount hardware realization;
- driver/access-envelope checks;
- kinematic sweeps and collision screening.

When topology or mounting truth is ambiguous, the system fails closed rather than inventing a plausible physical relationship.

## 4. Electrical, thermal, fluid, routing, safety, and kinematics share one model

The Analyze workspace exposes deterministic domain evidence from the active canonical branch:

- electrical nets, rail/current/logic compatibility and interface coverage;
- thermal nodes, heat/conductance networks, and temperature limits;
- fluid/hydraulic nodes, links, flow and routed-tube resistance;
- cable and tube routing, lengths, bend feasibility and clearance proxies;
- safety/failure modes, controls and current-design verification state;
- kinematics, joint limits, mechanism sweeps, and B-rep interference checks;
- structural, modal, tolerance, manufacturing, and requirement-gate validation.

A domain is shown as PASS only when the underlying analysis explicitly asserts a pass. Modeled-but-unasserted evidence remains modeled, and missing inputs remain missing.

## 5. Release-level assembly, solver, and evidence state is visible

ForgeCAD 6.0.1 adds an Analyze-side **Assembly, evidence & solver state** inspector so release-critical v6 capability is not buried behind APIs.

It exposes confirmed state for:

- assembly constraints, mates, geometry-backed mounts, and mount hardware;
- engineering repair trials;
- physical retest cycles and lineage;
- recorded test runs, specimens, metrology, and prediction residuals;
- external solver inventory and availability;
- chemistry studies/runs;
- release-stage and validation-truth boundaries.

The panel is deliberately an evidence inspector. It never converts a branch label, solver result, CI fixture, fabrication archive, or package hash into physical verification.

## 6. Branches preserve complete engineering state

ForgeCAD branches are not merely CAD geometry variants. A branch snapshots the canonical engineering state, including embedded code and the engineering identities needed by downstream analysis and evidence.

The 6.0.1 Design Lineage surface supports:

- creating an experimental branch from the active design;
- switching branches;
- marking a design **working**, **not working**, or **unverified**;
- comparing canonical differences against another branch;
- preserving independent physical-evidence state.

A “working” label is a design-management label only. It is not physical verification.

## 7. Embedded software belongs to the physical product

Programmable components expose their embedded code directly inside ForgeCAD. The Code workspace is a real editor surface rather than an external-file shortcut.

Code saves are serialized, and branch/project mutations wait for pending editor writes before canonical state changes. This prevents a fast branch switch from silently placing code on the wrong design revision.

The 6.0.1 desktop expands Code at normal and minimum supported window sizes so it functions as a usable IDE workspace rather than a shallow tray.

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

ForgeCAD can integrate controlled external engineering solvers. The 6.0 release substrate includes a validated Cantera chemistry path plus capability reporting for optional tools such as CalculiX, OpenFOAM, and Gmsh.

Solver availability is reported truthfully. Missing solvers do not trigger invented physics or an unannounced lower-fidelity substitute, and the presence of an executable does not by itself mean ForgeCAD has a validated model-to-case adapter for every problem.

## 11. Physical World Model and Jarvis integration

ForgeCAD maintains a persistent physical graph alongside canonical design state. World entities can represent sites, rooms, machines, assemblies, components, devices, interfaces, capabilities, live state, software, and source links back to ForgeCAD engineering objects.

The key epistemic invariant is:

```text
designed truth != observed state != inference
```

Live observations update observed state. They do not rewrite supplier specifications or canonical CAD. Jarvis identity resolution fails closed when the physical entity or CAD source link is ambiguous.

The System workspace surfaces physical-world entities, relations, provenance, observation age, engineering-graph health, selected-object context, and workspace profile without becoming a second hidden CAD editor.

---

# Desktop information architecture

ForgeCAD 6.0.1 intentionally separates responsibilities:

- **Model / Copilot (left):** object tree, branch navigation, and natural-language engineering interaction.
- **3D canvas (center):** authoritative physical artifact view and object selection.
- **History / Code / Simulation / System (bottom):** contextual workspaces for chronology, programmable hardware, long-running engineering jobs, and deployed/physical state.
- **Properties (right):** selected-object identity, fabricated-part parametric CAD, design truth, and branch lineage.
- **Components (right):** real-world component sourcing and insertion.
- **Analyze (right):** deterministic validation, cross-domain evidence, autonomous variant campaigns, assembly/evidence/solver state.
- **Manufacture (right):** manufacturing-resource checks, print/build preparation, splitting, and redesign handoff.

At the packaged minimum desktop size of **1280×760**, core application chrome and the primary Code/System workspaces are explicitly covered by browser acceptance.

---

# Truth and safety boundaries

ForgeCAD 6.0.1 keeps these invariants non-negotiable:

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

# 6.0.1 release gates

The release branch is intended to publish only after all current-head gates succeed:

- Forge Engine 6.0.1 canonical-state selftest;
- full preserved 6.0 cross-domain release-candidate selftest;
- validated external chemistry gate;
- desktop TypeScript typecheck, unit tests, and production build;
- focused 6.0.1 browser UX regression;
- design-lineage acceptance;
- fabricated feature-history mutation acceptance, including renderer→engine `PATCH`;
- advanced assembly/evidence/solver inspector acceptance;
- 1280×760 packaged-minimum layout acceptance;
- keyboard and interaction safety acceptance;
- preserved 3.1 browser integration;
- native Windows x64 installed-copy/launch validation;
- native macOS arm64 and x64 installed-copy/launch validation;
- packaged Forge Engine runtime identity, Cantera data, chemistry smoke test, and desktop bundled-engine startup validation.

See [`docs/RELEASE_6_0_1.md`](docs/RELEASE_6_0_1.md) for the release record and artifact names.

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

The 6.0 architecture deliberately builds on the validated 3.1 substrate rather than rewriting previously proven behavior without equivalent or stronger acceptance coverage.

---

# Development

From the repository root, the desktop package supports the normal workspace commands:

```bash
pnpm install
pnpm --filter @forgecad/desktop typecheck
pnpm --filter @forgecad/desktop test
pnpm --filter @forgecad/desktop build
```

Forge Engine is developed from `services/forge-engine`. Release and acceptance workflows define the exact runtime environment used for 6.0.1 validation.

For the complete release-specific truth contract, do not infer from a successful local UI launch alone; use the release selftests and GitHub Actions gates recorded for the release branch.
