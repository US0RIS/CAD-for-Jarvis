# ForgeCAD 6.0.1

ForgeCAD 6.0.1 is the correctness, UX, and interaction-hardening release on top of the validated 6.0.0 engineering substrate. It does not expand ForgeCAD's physical-validation claims. Its purpose is to make the shipped desktop behave consistently with the canonical design, branch, code, job, assembly, solver, manufacturing, and evidence invariants already established by 6.0.0.

## Release identity

- Release: `6.0.1`
- Branch: `forgecad/6.0.1`
- Desktop package version: `6.0.1`
- Forge Engine milestone version: `6.0.1`
- Product claim: software engineering release; **not** hardware certification

The full desktop UX audit is recorded in [`UX_AUDIT_6_0_1.md`](UX_AUDIT_6_0_1.md).

## What changed

### Canonical job, branch, and code correctness

- Embedded component-code saves are serialized and project/branch mutations wait for pending editor writes before replacing canonical state.
- Every queued engineering job is pinned to the exact source branch and project revision. A plan/result that becomes stale fails closed before it can mutate or record against a different design.
- Simulation, campaign, component-search, and deployment work executes as a canonical branch/revision transaction rather than racing the globally active project.
- Non-interruptible worker phases can no longer be reported as cancelled while their underlying calculation continues.
- Copilot and engineering jobs are tracked independently so a simulation/campaign cannot overwrite the visible state of an active agent task.
- Branch activation waits on canonical engineering work without blocking the asyncio event loop.
- Human branch-status labels preserve evidence-owned `physical_verified` state server-side; a transient client read or `physical_verified:false` status payload cannot erase recorded evidence.

### Design lineage is now a first-class desktop workflow

The main shell now exposes a dedicated Design Lineage surface rather than only a branch picker.

Users can:

- create an experimental branch from the active canonical design;
- switch active branches;
- mark a design `working`, `not_working`, or `unverified`;
- compare the active branch against another branch using canonical engineering state;
- see physical-evidence status separately from the human design label.

The UI explicitly states that a working/not-working label is not physical verification. Physical verification remains revision-bound recorded evidence.

### Fabricated CAD editing is reachable and purchased geometry remains protected

ForgeCAD already had a parametric feature-history engine, but the desktop shell had orphaned the editor. 6.0.1 exposes **PARAMETRIC CAD** directly in Object Properties for fabricated/imported custom parts.

Supported feature-history interactions include creation/editing of feature parameters plus suppression, reorder, duplication, and deletion where supported by the underlying feature model.

The renderer uses HTTP `PATCH` for feature parameter edits. The desktop entrypoint now explicitly permits `PATCH` through the renderer→Forge Engine CORS boundary, fixing a path where feature creation could work while editing an existing feature could fail.

Purchased supplier-backed components do **not** expose this custom-geometry editor. A second hidden Feature History instance in the System/Engineering Graph inspector was removed so purchased hardware cannot acquire an accidental backdoor geometry-editing path.

### Code and System are real workspaces

The generic shallow bottom tray was insufficient for programming and physical/deployed-state inspection.

6.0.1 now gives:

- Code: at least 310 px / 44vh at normal desktop heights, with a 250 px / 42vh fallback at the packaged 760 px minimum height;
- System: at least 280 px / 38vh for world, provenance, live-state, relation, and engineering-graph inspection.

The packaged desktop minimum of `1280×760` is now an explicit browser acceptance target. Core chrome, side panels, Code, System, and document-level horizontal overflow are checked at that size.

### Release-level v6 engineering state is visible in Analyze

6.0 contains assembly, physical-evidence, repair-lineage, external-solver, and chemistry capabilities that were substantially easier to reach through APIs than through the desktop.

6.0.1 adds an Analyze-side **Assembly, evidence & solver state** inspector covering confirmed state for:

- assembly constraints and mates;
- geometry-backed mount count;
- mount-hardware realization count;
- constraint-rank/mobility state where asserted;
- engineering repair trials;
- physical retest cycles and lineage;
- test runs, specimens, metrology records, and prediction residuals;
- external solver inventory and availability;
- chemistry studies and runs;
- release stage and hardware-validation truth.

The inspector fails closed when a status endpoint is unavailable and explicitly refuses to infer missing evidence. It is an evidence inspector, not a second design editor.

### Copilot and interaction UX hardening

Focused browser coverage proves:

- normal Enter-to-send and Shift+Enter newline behavior;
- local-AI-offline draft preservation;
- clear active-task and cancellation state;
- concurrent agent/engineering-job UI isolation;
- optimistic object deletion with canonical rollback on failure;
- undo after deletion;
- dirty embedded-code persistence across an immediate branch switch;
- keyboard guards and shortcut discoverability.

### Terminology and accessibility

- The model browser now calls canonical variants **BRANCHES** consistently instead of mixing branch and “design” terminology.
- Important selectors and inputs have explicit accessible names for keyboard/assistive navigation and stable acceptance testing.
- The repository README is reconciled to 6.0.1 and no longer identifies 3.0.0 as the current release.

## Acceptance gates

The release candidate is accepted only when the current release source passes the relevant gates below.

### Engine / source gates

- `python -m forge_engine.v601_selftest`
  - branch-persistent embedded code;
  - stale-job rejection;
  - evidence preservation;
  - cross-branch job rejection;
  - truthful non-interruptible cancellation.
- preserved full 6.0 cross-domain release-candidate selftest;
- preserved validated external chemistry/Cantera gate.

### Desktop source gates

- TypeScript typecheck;
- desktop unit tests;
- production desktop build.

### Focused browser UX gates

The 6.0.1 UX workflow runs stateful tests serially against one canonical Forge Engine project and covers:

- core Copilot/interaction regression;
- design-lineage creation/status/comparison;
- fabricated feature-history creation and real renderer→engine `PATCH` editing;
- advanced assembly/evidence/solver inspector truth boundaries;
- packaged minimum `1280×760` layout;
- keyboard shortcuts and interaction guards;
- preserved 3.1 browser integration.

### Native release gates

The native workflow validates source, installed package, and desktop launch on all supported release targets:

- Windows x64;
- macOS arm64;
- macOS x64.

Installed-runtime validation confirms the bundled Forge Engine through its public HTTP surface, 6.0.1 runtime identity/truth contract, packaged Cantera data, validated chemistry smoke study, and desktop startup of the bundled engine.

## Native artifacts

The release is published only after the native gates succeed. Expected release files are:

- `ForgeCAD-Setup-6.0.1.exe` — Windows x64 NSIS installer;
- `ForgeCAD-6.0.1-arm64.dmg` — native Apple Silicon macOS image;
- `ForgeCAD-6.0.1-x64.dmg` — native Intel macOS image;
- `SHA256SUMS.txt` — SHA-256 hashes generated from the exact published binaries.

Do not treat a local or intermediate installer as a final 6.0.1 release artifact unless it is produced by the passing native release workflow for the accepted source revision.

## Compatibility

6.0.1 preserves the validated 3.1 browser/integration substrate and the complete 6.0.0 engineering capability set. This patch release hardens and exposes that substrate rather than replacing it.

The release branch remains `forgecad/6.0.1`; release completion does not imply an automatic merge into `main`.

## Truth boundaries

The principal epistemic invariant remains:

```text
designed truth != observed state != inference
```

Additional release invariants:

- purchased component engineering data remains immutable inside a design revision;
- branch status is not physical verification;
- physical evidence applies only to the exact engineering fingerprint actually tested;
- a passing physical retest verifies only its scoped requirement;
- stale simulation/solver evidence cannot silently survive the mutation that made it stale;
- missing external solvers fail closed rather than silently returning invented physics;
- solver availability does not prove a given ForgeCAD model has a validated adapter/case;
- a fabrication-package hash proves package byte identity, not physical specimen authenticity;
- CI physical fixtures remain synthetic contract tests;
- software/native-installer success is not physical-product certification.

ForgeCAD 6.0.1 therefore makes the complete engineering environment materially more usable without weakening the distinction between what the software models, what a solver predicts, what a person labels, and what has actually been observed or physically tested.
