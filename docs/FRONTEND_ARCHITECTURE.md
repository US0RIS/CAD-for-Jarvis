# ForgeCAD v2 Frontend Architecture

Status: **implementation architecture**

This architecture exists to make the reference UI reliable, fast, and testable. The previous prototype failed because rendering, AI availability, static asset loading, and engineering operations were too loosely coupled and insufficiently validated. v2 treats each as an explicit subsystem with contracts and health states.

## 1. Chosen stack

### Desktop shell

**Electron**

Why Electron instead of a system WebView:

- consistent bundled Chromium on macOS and Windows;
- predictable WebGL2 and GPU behavior;
- first-class ES modules and worker support;
- Monaco is a native fit;
- reliable DevTools during development;
- no dependency on whichever WebKit/WebView version happens to ship with the OS;
- mature packaging, crash reporting, protocol handling, deep links, menus, and updater ecosystem.

The extra bundle size is acceptable for an engineering workstation whose Python CAD/CAE runtime is already large.

### Renderer application

- React 19
- TypeScript with `strict: true`
- Vite
- Zustand for ephemeral client/UI state
- TanStack Query for backend/server state
- Zod for runtime validation at process/API boundaries
- Radix primitives only where they do not force a visual style; ForgeCAD owns the styling
- Monaco Editor
- Three.js directly through a dedicated scene controller
- `postprocessing` or Three.js EffectComposer for SSAO/outline/tone effects
- Lucide-style icon set with a small curated subset

The 3D viewport does **not** use React Three Fiber as the authoritative scene layer. React owns the canvas host and UI overlays; a dedicated imperative Three.js `SceneController` owns scene lifetime, geometry, selection, materials, camera, explode presentation, and animation. This avoids tying high-frequency CAD scene mutation to React reconciliation.

## 2. Process topology

```text
┌──────────────────────────────────────────────────────────────┐
│ Electron main process                                        │
│  • native menus/window                                       │
│  • lifecycle                                                 │
│  • launches Forge Engine                                     │
│  • owns ephemeral localhost auth token                       │
│  • file dialogs / OS integration                             │
└──────────────┬───────────────────────────────────────────────┘
               │ secure preload IPC
               ▼
┌──────────────────────────────────────────────────────────────┐
│ Electron renderer                                            │
│ React + TypeScript                                           │
│                                                              │
│ UI chrome   SceneController   Monaco   job/event clients      │
└──────────────┬───────────────────────────────┬───────────────┘
               │ HTTP                          │ WebSocket
               ▼                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Forge Engine (Python / FastAPI)                              │
│  canonical project model                                    │
│  CAD/OpenCascade                                             │
│  component registry                                         │
│  design lineage                                             │
│  code workspaces                                             │
│  simulation adapters                                        │
│  AI tool executor                                           │
│  job manager                                                 │
└──────────────┬───────────────────────────────────────────────┘
               │
      ┌────────┴────────┐
      ▼                 ▼
 Ollama local       external solvers
 qwen profile       Gmsh/CalculiX/OpenFOAM/etc.
```

The renderer never imports Python, shells out directly, or accesses the filesystem with Node APIs.

## 3. Repository layout

```text
CAD-for-Jarvis/
├── apps/
│   └── desktop/
│       ├── electron/
│       │   ├── main.ts
│       │   ├── preload.ts
│       │   ├── engineSupervisor.ts
│       │   ├── nativeMenus.ts
│       │   └── updater.ts
│       ├── src/
│       │   ├── app/
│       │   ├── components/
│       │   ├── features/
│       │   ├── scene/
│       │   ├── stores/
│       │   ├── api/
│       │   ├── styles/
│       │   └── test/
│       ├── index.html
│       ├── package.json
│       └── vite.config.ts
├── packages/
│   ├── contracts/       # generated/shared TS API contracts
│   ├── design-system/   # tokens and ForgeCAD UI primitives
│   └── scene-types/     # renderer-only geometry/selection types
├── services/
│   ├── forge-engine/    # Python canonical engineering service
│   └── ai-worker/       # optional separable worker process later
├── docs/
│   ├── PRODUCT_SPEC.md
│   ├── FRONTEND_ARCHITECTURE.md
│   ├── INTERACTION_CONTRACTS.md
│   └── reference/
└── e2e/
    └── playwright/
```

The Python engineering implementation can initially be migrated from known-good pieces of the previous work, but the frontend code is clean-sheet.

## 4. Electron security and lifecycle

### Main process responsibilities

The Electron main process:

- chooses a free localhost port;
- creates a cryptographically random per-launch token;
- starts the packaged Forge Engine as a child process;
- passes `FORGECAD_PORT`, `FORGECAD_SESSION_TOKEN`, data root, and host model profile as environment variables;
- waits for `/v2/health` with a bounded startup deadline;
- loads the renderer only after the engine reports a valid API version;
- kills/restarts the engine on explicit user request or clean application shutdown;
- mediates native file dialogs and OS-level open/reveal operations.

`contextIsolation: true`, `nodeIntegration: false`, sandboxing enabled where compatible. The preload exposes a deliberately tiny typed surface.

### Engine failure behavior

If the engine fails to start, Electron presents a native recovery window with:

- exact failure stage;
- last engine log lines;
- Retry;
- Open logs;
- Reset runtime;
- Quit.

The user must never reach the normal ForgeCAD UI with a dead backend masquerading as healthy.

## 5. API contract strategy

FastAPI publishes OpenAPI. CI generates TypeScript contracts into `packages/contracts` with `openapi-typescript`. Critical event payloads are additionally validated by Zod because WebSocket payloads are long-lived runtime boundaries.

Version every public route under `/v2`.

Core endpoints:

```text
GET  /v2/health
GET  /v2/runtime
GET  /v2/project
POST /v2/project/commands
GET  /v2/designs
POST /v2/designs/branch
POST /v2/designs/status
GET  /v2/designs/{name}/diff
GET  /v2/history
GET  /v2/scene/manifest
GET  /v2/scene/assets/{asset_id}
GET  /v2/components/search
POST /v2/components/select
POST /v2/components/insert
GET  /v2/code/workspaces
GET  /v2/code/workspaces/{id}/files
PUT  /v2/code/workspaces/{id}/files/{path}
POST /v2/jobs
POST /v2/jobs/{id}/cancel
GET  /v2/jobs/{id}
WS   /v2/events
```

Long-running AI/solver/campaign actions are created through `POST /v2/jobs`. They are not synchronous request/response calls.

## 6. Job architecture

A job record contains:

```ts
export type JobState =
  | 'queued'
  | 'warming'
  | 'planning'
  | 'applying'
  | 'analyzing'
  | 'verifying'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface EngineeringJob {
  id: string;
  kind: 'agent' | 'simulation' | 'campaign' | 'component-search' | 'deploy';
  state: JobState;
  createdAt: string;
  progress?: number;
  message?: string;
  branch?: string;
  selectedObjectId?: string;
  error?: StructuredError;
}
```

`POST /v2/jobs` acknowledges immediately. Progress/events stream over one authenticated WebSocket.

The chat renderer distinguishes streamed **language output** from engineering **job state**. The model can be warming while the rest of the UI remains fully interactive.

## 7. Client state model

Use TanStack Query for canonical backend state and Zustand only for ephemeral presentation state.

### Query-backed canonical state

- project metadata;
- designs/branches;
- history;
- objects/parts;
- BOM;
- component search results;
- analyses;
- code file contents;
- requirements;
- runtime/model status.

### Zustand stores

`useShellStore`

- panel widths;
- collapsed/expanded dock;
- active right tab;
- active bottom tab;
- modal state.

`useSceneStore`

- camera mode;
- explode percentage;
- hidden IDs;
- isolated ID;
- transform mode;
- auto-rotate;
- hover ID;
- selected ID;
- temporary result overlay.

`useJobStore`

- live job progress cache;
- optimistic/pending chat entries;
- cancellation state.

`useEditorStore`

- open code tabs;
- dirty buffers;
- cursor/view state;
- output pane state.

Authoritative transforms, part geometry, branch status, or code contents are never stored only in Zustand.

## 8. Application component tree

```text
<AppRoot>
  <StartupGate />
  <ForgeShell>
    <TitleToolbar />
    <CopilotRail>
      <CopilotRuntimeStatus />
      <Conversation />
      <ContextActions />
      <PromptComposer />
    </CopilotRail>

    <CenterWorkspace>
      <ProjectToolbar />
      <DesignLineageStrip />
      <ViewportToolbar />
      <EngineeringViewport>
        <ThreeCanvas />
        <ViewportOverlays />
        <SelectedPartCard />
        <ExplodeControl />
      </EngineeringViewport>
      <BottomDock>
        <SimulationsPanel />
        <NotebookPanel />
        <DesignsPanel />
        <HistoryPanel />
        <CodePanel />
        <SystemPanel />
      </BottomDock>
    </CenterWorkspace>

    <EngineeringRail>
      <DesignPanel />
      <ComponentLibraryPanel />
      <AnalysisPanel />
    </EngineeringRail>
  </ForgeShell>
</AppRoot>
```

Heavy panels use code splitting, but shell bootstrap and scene dependency checks are part of the initial bundle and cannot silently fail.

## 9. Three.js SceneController

`SceneController` is an imperative class with a narrow event interface to React.

Responsibilities:

- renderer/canvas lifecycle;
- scene/camera/lights;
- HDR environment;
- GLB asset loading;
- PBR material normalization;
- object-ID ↔ scene-node mapping;
- selection raycasting;
- hover state;
- transform gizmos;
- presentation explode transforms;
- hide/isolate;
- result overlays;
- camera presets;
- animation loop;
- FPS/performance monitoring;
- GPU resource disposal.

Example interface:

```ts
interface SceneController {
  mount(canvas: HTMLCanvasElement): Promise<void>;
  loadManifest(manifest: SceneManifest): Promise<void>;
  select(id: string | null): void;
  setExplode(value: number): void;
  setVisibility(state: VisibilityState): void;
  setTransformMode(mode: 'move' | 'rotate' | 'scale'): void;
  setCameraPreset(preset: CameraPreset): Promise<void>;
  setResultOverlay(result: ResultOverlay | null): void;
  dispose(): void;
}
```

### Scene asset format

The backend remains authoritative for CAD. It tessellates/export-converts scene geometry into GLB assets plus a manifest.

`SceneManifest` contains stable semantic IDs, world transforms, material references, exact/proxy fidelity flags, source/provenance, bounds, explode grouping, selection metadata, and asset hashes.

GLB is preferred because it transports geometry, materials, textures, hierarchy, and optional mesh compression efficiently.

### Performance

- cache assets by content hash;
- use Meshopt/Draco where useful;
- use instancing for repeated fasteners/components;
- lazy-load hidden/LOD geometry;
- upload geometry off the critical React path;
- use workers for expensive mesh decoding where supported;
- cap DPR dynamically under sustained frame pressure.

## 10. Photorealistic rendering pipeline

Default editing pipeline:

1. WebGLRenderer with physically correct lighting;
2. ACES-like tone mapping;
3. HDR environment / PMREM;
4. directional/key lights as needed for deterministic product readability;
5. contact shadows;
6. SSAO/GTAO-equivalent pass;
7. selection outline pass;
8. optional subtle bloom only for selected/active indicators;
9. TAA/SMAA/FXAA strategy selected after performance testing.

Materials are semantic, not random colors. Catalog/manufacturer appearance data wins; otherwise ForgeCAD uses material-class defaults.

The renderer must support a separate `presentation` quality preset but the normal engineering view should already look polished.

## 11. Component imagery and assets

Component search results use a local `AssetCache` abstraction.

Priority:

1. manufacturer-provided product image;
2. trusted distributor image;
3. render generated from manufacturer CAD using ForgeCAD's thumbnail renderer;
4. category-specific fallback illustration.

Every image record includes source URL/provider, retrieval time, license/provenance metadata where known, local cache hash, and component revision.

UI cards never hotlink arbitrary external images during normal browsing once cached.

## 12. Design lineage frontend model

A branch is rendered from backend ancestry, not from local UI assumptions.

```ts
interface DesignBranchSummary {
  name: string;
  headCommit: string;
  parentBranch?: string;
  status: 'working' | 'not_working' | 'unverified';
  physicalVerified: boolean;
  protected: boolean;
  commitCount: number;
  active: boolean;
}
```

When a protected baseline is active and a mutation is requested, the frontend presents the branch operation returned by the backend; it never overrides protection locally.

## 13. Component library frontend model

The library is virtualized and filterable. Search may query offline, provider-backed, and cached records simultaneously.

Result cards use a normalized `ComponentCandidate` with:

- component identity;
- display image;
- manufacturer/model;
- top specs selected by category;
- supplier/price;
- stock freshness;
- fit score;
- reason summary;
- unknown required fields;
- exact/proxy geometry state;
- add state.

A 95% match badge means a deterministic selector score, not an LLM opinion.

## 14. Monaco/code integration

Monaco is lazy-loaded only when `CODE` is first activated or a programmable component is selected.

The editor operates on workspace/file IDs, not arbitrary host filesystem paths. Writes go through the Forge Engine so they participate in branch protection, history, undo semantics, and device-target validation.

Dirty buffers are explicit. Branch switching with dirty files requires save/discard/stash-like resolution.

Agent code edits arrive as patches/diffs and are reviewable before application when `Apply edits` is disabled.

## 15. Error boundaries and startup gates

There are three independent startup gates:

1. **Shell gate** — React bundle mounted.
2. **Engine gate** — `/v2/health` and API version valid.
3. **Scene gate** — Three.js renderer initialized and required GPU features available.

Chat/model readiness is **not** a launch gate; CAD remains usable without Ollama.

Each major feature area has an error boundary. A component-library rendering error cannot destroy the viewport; a viewport failure cannot make the chat composer silently inert.

Global `window.onerror`, `unhandledrejection`, React error boundaries, engine process stderr, and WebSocket disconnects all feed a structured diagnostic recorder.

## 16. Testing strategy

### Unit

Vitest for stores, reducers, formatting, selection math, component-score presentation, and job-state transitions.

### Component

React Testing Library for rails, branch cards, component cards, composer, dock tabs, status states, and error boundaries.

### Renderer

Headed Chromium tests instantiate `SceneController` with fixture GLBs and assert:

- canvas initialized;
- part selection;
- explode transforms;
- visibility/isolation;
- camera presets;
- transform controls;
- resource cleanup.

### Desktop E2E

Playwright Electron tests run against the packaged/development desktop app with a deterministic fixture Forge Engine and a fake Ollama server.

Critical E2E suite follows the acceptance criteria in `PRODUCT_SPEC.md`. Release CI additionally runs a real backend smoke suite on macOS and Windows runners.

Screenshots are captured for visual-regression comparison against approved baselines.

## 17. Performance budgets

Initial budgets on target hardware:

- Electron shell visible: < 1.5 s after backend-ready signal;
- immediate UI response to click/input: < 50 ms;
- send acknowledgement: < 100 ms;
- bottom-tab switch: < 100 ms excluding first Monaco lazy load;
- explode slider visual response: same animation frame;
- 3D interaction: 60 fps target, 30 fps minimum under large-assembly pressure;
- component search first cached results: < 250 ms;
- backend disconnect indication: < 2 s;
- model warmup never blocks renderer input.

## 18. Packaging

Development uses pnpm workspaces.

Release uses Electron Builder (or Electron Forge if CI proves cleaner) with:

- signed/notarized `.dmg` for macOS;
- signed installer for Windows;
- packaged Python engineering runtime or an explicitly versioned managed runtime;
- no network dependency for core UI runtime assets;
- all Three.js/Monaco assets bundled at build time;
- startup self-checks before presenting the normal workspace.

Production packaging must not download JavaScript framework files at first launch.

## 19. Implementation order

The frontend should be built as a vertical slice rather than panel-by-panel mocks:

1. Electron shell + engine supervision + startup gate;
2. exact three-column/top-lineage/bottom-dock layout;
3. SceneController with one photorealistic fixture assembly;
4. branch lineage interactions;
5. component cards with real fixture imagery;
6. async chat job flow with fake/local Ollama;
7. Monaco workspace linked to a programmable fixture component;
8. connect the slice to the real Forge Engine contracts;
9. expand analysis/design panels;
10. packaging and visual/E2E release gates.

No later subsystem should be used to justify postponing frontend reliability. The vertical slice must be genuinely interactive before scope expands.
