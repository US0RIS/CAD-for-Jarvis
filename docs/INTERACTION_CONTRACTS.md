# ForgeCAD v2 Interaction and State Contracts

This document translates the product specification into observable behavior. If an implementation cannot satisfy these contracts, the UI should expose an explicit unavailable/error state rather than imitate success.

## 1. Global runtime states

ForgeCAD has independent runtime channels. They must never be collapsed into one vague `online` indicator.

```ts
interface RuntimeState {
  engine: 'starting' | 'ready' | 'degraded' | 'offline' | 'failed';
  scene: 'starting' | 'ready' | 'degraded' | 'failed';
  ollama: 'checking' | 'warming' | 'ready' | 'offline' | 'failed';
  configuredModel: string;
  resolvedModel?: string;
  apiVersion?: string;
}
```

A healthy CAD engine with offline Ollama is still a usable CAD application.

## 2. Model-selection contract

- The selector displays only actually installed/available local model tags unless the user is in settings intentionally configuring a missing target.
- `configuredModel` and `resolvedModel` are both visible to diagnostics.
- The runtime may never silently resolve `qwen3:8b` to another model.
- If the configured model is absent, chat is disabled with a direct remediation state; CAD remains active.

## 3. Chat submission contract

On Send:

1. composer captures a stable copy of text/attachments/current selection/current branch;
2. local UI inserts the user's message immediately;
3. local UI inserts an agent job row in `queued` state within the same frame;
4. `POST /v2/jobs` creates the engineering job;
5. WebSocket events advance state;
6. streamed assistant language appears independently of command/application progress;
7. typed engineering operations are displayed as structured actions;
8. on completion, affected canonical queries are invalidated/refetched;
9. on failure, the job row becomes a durable error with Retry/Inspect details.

The send button may not appear to do nothing.

## 4. Apply-edits contract

When `Apply edits` is enabled, validated typed engineering commands may be executed automatically subject to backend protection rules.

When disabled, the agent may plan commands but the user must explicitly apply them.

The toggle does not bypass:

- protected physical baseline rules;
- destructive-operation confirmation;
- missing-data constraints;
- solver/analysis validity rules.

## 5. Protected design contract

If the active design is `physicalVerified && protected`, any mutating action returns one of:

- automatic child-branch proposal;
- explicit rejection if branching is impossible.

The frontend must not locally change canonical part/code/component state before this decision.

## 6. Branch interaction contract

Creating a branch:

- requires source commit/branch;
- returns the new branch summary and active head;
- never rewrites the source branch;
- refreshes lineage within one backend round-trip;
- retains camera/presentation state where possible.

Switching branches:

- checks dirty code buffers;
- resolves save/discard before switching;
- cancels or detaches branch-scoped jobs as defined by backend policy;
- reloads scene manifest by content hash;
- preserves camera if the scene bounds are compatible, otherwise fits automatically.

## 7. Design-status contract

States are exactly:

```text
working
not_working
unverified
```

`physicalVerified` is a separate boolean. A design cannot be treated as protected merely because status is `working`; the user must explicitly mark the physical verification state.

Changing physical verification creates a history event.

## 8. Compare-to-working contract

For a failed/unverified design, `Compare to working` resolves a candidate baseline by explicit selection or nearest verified working ancestor.

The comparison separates:

- geometry/parameter differences;
- material differences;
- component substitutions;
- joint/load/constraint differences;
- code/file differences;
- BOM/cost/mass/power differences;
- simulation result differences;
- requirements status differences.

UI wording is `differences` unless a dedicated analysis establishes causality.

## 9. Viewport selection contract

Selection source can be:

- 3D click;
- parts tree;
- component result after insertion;
- AI focus result;
- analysis result navigation.

All routes update one canonical client selection ID. Selection does not mutate project history.

Selected part drives:

- outline/highlight;
- Design rail context;
- AI contextual selection;
- floating part card;
- Code dock availability.

## 10. Explode contract

`explodePercent` ranges from 0 to 100 and is client presentation state.

Changing it:

- updates the displayed percentage on the same animation frame;
- smoothly updates scene presentation transforms;
- never sends transform commands to the canonical CAD backend;
- never creates history/undo entries;
- survives non-geometric panel changes;
- resets/recomputes cleanly when branch scene topology changes.

## 11. Hide/isolate contract

Hide/isolate are presentation state unless the user explicitly creates a saved view. They do not mutate canonical part visibility/manufacturing state.

`Show all` clears temporary hidden/isolate presentation state.

## 12. Component search contract

Search is cancellable and debounced. Result records expose source freshness.

A card must not show a fit score unless the selector has evaluated it against the active engineering constraints.

`Add` creates a backend component insertion command. A successful insertion returns:

- canonical object/part ID;
- component record ID;
- geometry fidelity state (`exact`, `manufacturer_mesh`, `proxy`);
- updated BOM state;
- provenance snapshot.

The frontend then focuses the inserted part.

## 13. Component imagery contract

Image display state is one of:

```text
manufacturer
supplier
cad_render
fallback
loading
failed
```

The image source is inspectable in component details. UI never implies a generated fallback image is a manufacturer photograph.

## 14. Scene fidelity contract

Each visible real component carries a geometry fidelity marker internally:

- `exact` — trusted exact manufacturer/imported CAD;
- `manufacturer_mesh` — trusted visual mesh, not guaranteed exact B-rep;
- `proxy` — envelope/representative geometry.

Engineering calculations must know which geometry level they consume. Presentation may render all three attractively, but inspection exposes the fidelity.

## 15. Bottom dock contract

Tabs `SIMULATIONS`, `NOTEBOOK`, `DESIGNS`, `HISTORY`, `CODE`, `SYSTEM` are always switchable while the engine is ready, regardless of Ollama state.

The first switch to CODE may lazy-load Monaco and may show a loading state, but the tab click itself acknowledges instantly.

## 16. Code workspace contract

A workspace belongs to a programmable component ID and current design branch.

File writes go through the backend. A successful write:

- updates file revision/hash;
- produces design history;
- invalidates relevant build/test state;
- remains branch-local.

AI code changes use the same contract as human edits.

## 17. Run/deploy contract

Run/build/deploy is job-based. The UI displays:

- target;
- command/toolchain chosen by the backend adapter;
- state/progress;
- stdout/stderr stream;
- resulting evidence/telemetry attachments;
- whether the result is branch-valid or stale.

No arbitrary model-generated host shell command is executed directly by the renderer.

## 18. Simulation contract

Each analysis result includes:

- branch commit/revision;
- analysis type;
- solver and version;
- assumptions;
- mesh/model settings;
- input provenance;
- result summary;
- convergence state where applicable;
- confidence/reality metadata;
- stale/current status.

Changing relevant canonical state marks affected results stale rather than deleting them.

## 19. Campaign contract

Starting an autonomous campaign requires:

- objective(s);
- hard constraints;
- allowed mutation classes;
- budget limits such as variants/time;
- source branch;
- whether code changes are permitted.

The campaign creates child branches and cannot mutate a protected baseline.

Progress exposes candidate branches and phases. Completion returns ranked candidates plus rejected branches/reasons and verifier findings.

## 20. Startup contract

The normal project shell is shown only after:

- React mounted;
- Forge Engine API version validated;
- scene runtime initialized.

Ollama readiness is asynchronous and not a shell gate.

A failure in any gate renders a named diagnostic state. The application must never show a normal interactive-looking control whose backing JavaScript did not initialize.

## 21. Persistence contract

Persistent project data lives in the Forge Engine data root and is content/version aware. Electron renderer local storage is limited to disposable UI preferences such as panel sizes and recent view preferences.

No canonical engineering state exists only in browser localStorage.

## 22. Jarvis contract

Jarvis interacts with ForgeCAD through the same typed engineering API/job layer, not through UI automation.

Remote mutating requests:

- preserve the verbatim engineering request;
- enter the ForgeCAD engineering model context;
- branch before mutation when policy requires;
- produce the same history/audit records as local edits;
- return a voice-suitable summary plus unresolved risks/verification needs.
