# ForgeCAD v2 Product Specification

Status: **canonical product contract**

Reference image: `docs/reference/forgecad-target-ui.png`

This document defines what ForgeCAD v2 must be. The reference image is not mood-board inspiration. It is the target desktop composition and visual hierarchy. Deviations require an explicit product reason, not convenience during implementation.

## 1. Product thesis

ForgeCAD is an AI-native physical engineering environment. The user should experience a product as a real assembly with geometry, mass, materials, heat, power, code, procurement, tolerances, dynamics, simulation results, and history attached to it.

The core loop is:

1. describe an engineering intent;
2. inspect/manipulate the physical design directly;
3. let the local engineering agent create or modify CAD, code, components, requirements, and analyses through typed tools;
4. branch alternatives rather than destroying a known-good design;
5. simulate and compare those alternatives;
6. mark physical outcomes as working, not working, or unverified;
7. use the difference between physical outcomes to guide the next design iteration.

ForgeCAD is local-first. Design data, code, model context, and engineering history remain on the machine by default.

## 2. Canonical desktop composition

Target reference resolution is 1586 × 992. The layout must remain proportionally equivalent from 1366 × 768 upward and should optimize around 1440–1728 logical-pixel desktop widths.

### 2.1 Global shell

The application uses a near-black engineering-workstation theme with thin cool-gray separators and a saturated mint/green accent. There are no large rounded consumer cards, oversized headings, decorative gradients, or excessive empty space.

The visual hierarchy is:

- native application menu / titlebar;
- project toolbar;
- left engineering-copilot rail;
- central design workspace;
- right engineering context rail;
- bottom multi-tool dock.

Recommended shell proportions at the reference width:

- left rail: 315–330 px;
- right rail: 360–375 px;
- center: remaining width;
- project toolbar: 50–56 px;
- design-lineage strip: 70–82 px;
- bottom dock: variable 36 px collapsed to roughly 275 px open.

Panels may be resizable, but their default arrangement must match the reference.

## 3. Visual system

### 3.1 Color tokens

Initial implementation tokens:

```css
--bg-app: #071016;
--bg-panel: #0b141b;
--bg-panel-raised: #101b23;
--bg-control: #111c24;
--bg-control-hover: #17242d;
--border-subtle: #22313b;
--border-strong: #34444f;
--text-primary: #eef5f6;
--text-secondary: #a7b5bd;
--text-muted: #6f808a;
--accent: #55f59a;
--accent-strong: #33e884;
--accent-dim: rgba(85, 245, 154, 0.12);
--danger: #ff6468;
--warning: #f1bf55;
--info: #63a8ff;
```

These values may be tuned against the reference image, but the theme must remain dark, restrained, and high contrast.

### 3.2 Typography

Use a modern system UI sans stack for chrome and a dedicated monospace stack for code and numerical output. Default UI text is compact: 12–14 px for most controls, 15–17 px for panel titles, 21–24 px for project/product headings.

### 3.3 Geometry

Controls use 6–9 px radii. Large panel radii should be rare. Borders are 1 px. Shadows are subtle and reserved for floating overlays and selected component cards.

## 4. Left rail: Local engineering copilot

The left rail is always the conversational entry point.

### 4.1 Header

Top area contains:

- ForgeCAD mark and wordmark;
- subtitle `AI Engineering Studio`;
- collapse control;
- clear online/offline/warming/error state for the local engineering model;
- model selector with an explicit `LOCAL` badge.

The model selector may only show models actually available through the configured local runtime. It must never display a phantom or silently substituted model.

### 4.2 Conversation

Messages are presented as compact engineering conversation blocks, not oversized chat bubbles. Agent responses may contain structured result rows for branch creation, selected components, completed analyses, stale simulations, and requirement status.

The conversation supports streamed tokens and streamed engineering progress independently. A long solver job must not make the chat appear frozen.

### 4.3 Suggested actions

Contextual pills such as `Explain selected part`, `Review design`, and `Next test` appear immediately above the composer when relevant.

### 4.4 Composer

Bottom composer contains:

- multiline instruction field;
- optional attachment button;
- `Apply edits` toggle;
- high-contrast send button;
- cancel/stop button while a job is active.

Submitting must acknowledge within 100 ms with a local pending state. The UI must immediately show whether the request is queued, warming the model, reasoning, applying commands, running analysis, or awaiting confirmation.

## 5. Project toolbar

The project toolbar spans the center/right workspace and contains:

- current project name;
- active design branch selector;
- undo / redo;
- Import STEP;
- Project menu;
- Dynamics primary action.

Undo/redo applies to canonical project operations, not arbitrary DOM state.

## 6. Design lineage strip

Immediately below the project toolbar is the visible Git-like design lineage.

Each branch card shows:

- branch name;
- state: Working / Not working / Unverified;
- physical verification marker (`Works in real life`);
- protection marker for physically verified known-good baselines;
- commit count;
- active state.

Cards are connected visually in ancestry order. The user can create a new branch from the active design or from an earlier history node.

A physically verified working design is protected from direct mutation. Any AI or human engineering edit must branch first.

The strip also provides:

- status filter;
- Works in real life control;
- Compare to working action.

When a failed design is compared to a working design, the application must present differences as differences, not claim causal attribution without supporting analysis.

## 7. Central 3D workspace

The 3D viewport is the dominant visual object in the product.

### 7.1 Rendering standard

The renderer must support presentation-quality engineering visualization, not primitive CAD shading only:

- physically based materials;
- HDR environment lighting;
- tone mapping;
- anti-aliasing;
- contact shadows;
- screen-space ambient occlusion or equivalent;
- clean normals;
- realistic metallic, coated, polymer, PCB, rubber, glass, and fastener materials;
- smooth selected-part outlines;
- high-resolution component textures where available;
- deterministic LOD for large assemblies.

The normal editing viewport targets 60 fps on modern hardware. Photorealistic hero mode may trade frame rate for quality but must never block editing state.

### 7.2 Real components

A catalog component should use manufacturer CAD/mesh data when available. Envelope proxies are visibly labeled as proxies and may not be shown as if they were exact geometry.

Real components can include textures/appearance metadata. PCB-class components should look like PCBs; batteries, solenoids, motors, relays, fans, sensors, and fasteners should be recognizable at a glance.

### 7.3 View controls

Toolbar controls match the reference:

- Move;
- Rotate;
- Scale;
- Fit;
- Iso;
- Top;
- Front;
- Right;
- Auto rotate;
- Isolate;
- Hide;
- Show all.

Direct orbit/pan/zoom remain available.

### 7.4 Exploded view

Explode is a presentation transform only. It never mutates authoritative CAD transforms.

The slider updates continuously with its percentage and animates parts outward along stable assembly-aware directions. Entering/exiting exploded state should interpolate smoothly rather than jump.

### 7.5 Selection

Selecting a part updates:

- viewport highlight;
- right inspection context;
- AI context;
- optional floating part card;
- code workspace availability if programmable.

Selection must remain stable while camera and explode presentation state change.

## 8. Floating part card

When appropriate, selected components show a compact floating card in the viewport containing:

- real product image or rendered thumbnail;
- part name;
- semantic role;
- mass;
- power draw where relevant;
- source/provenance indicator;
- software workspace link for programmable components;
- close control.

The card must not obstruct the selected geometry by default.

## 9. Right rail

Top-level tabs are `Design`, `Components`, and `Analysis`.

### 9.1 Components tab

The real component library must visually resemble the reference and must not degrade into text rows.

It contains:

- search;
- filter control;
- category selector;
- electrical/mechanical constraints such as voltage;
- supplier selector;
- result count;
- ranking mode.

Each result card contains:

- actual component product image or trusted manufacturer/distributor image;
- manufacturer + model name;
- key specifications;
- price;
- supplier;
- compatibility / engineering match score;
- Add/Added state.

Image provenance is stored with the component. Images should be cached locally. Missing imagery uses a high-quality generated/rendered component thumbnail, never a generic broken-image icon.

### 9.2 Design tab

Provides selected-part structure, properties, materials, semantic role, geometry, manufacturing intent, joints, loads, constraints, requirements, BOM, and code attachment state.

### 9.3 Analysis tab

Provides analysis setup, job status, convergence, confidence/provenance, result overlays, stale-result status, and comparison against requirements.

## 10. Autonomous engineering campaign panel

The lower right rail exposes autonomous campaign capability as a first-class feature.

The campaign panel communicates that the system can:

- explore parameters/components/software choices;
- generate multiple branches;
- run appropriate analyses;
- reject failing variants;
- invoke an independent verifier;
- rank feasible candidates against objectives.

Starting a campaign opens a scoped objective editor before execution. The system must never silently mutate the known-good baseline.

## 11. Bottom multi-tool dock

Tabs exactly follow the reference concept:

- SIMULATIONS;
- NOTEBOOK;
- DESIGNS;
- HISTORY;
- CODE;
- SYSTEM.

The dock may collapse to a thin tab strip when not in use.

### 11.1 Code workspace

Selecting a programmable part exposes its attached software workspace. The code panel contains:

- target/device header;
- file tree;
- editor tabs;
- Monaco editor;
- language/runtime selector;
- Save;
- Check;
- Ask Qwen;
- Branch Code;
- Run/Deploy where supported;
- output/terminal pane.

Code is part of the design branch. Hardware and software branch together.

### 11.2 History

History displays content-addressed engineering commits and events with actor, time, branch, reason, physical status changes, analysis/deployment evidence, and code changes.

## 12. AI behavior and responsiveness

The renderer never waits synchronously for Ollama or an engineering solver.

All agent/solver operations use jobs with explicit state:

`queued → warming → planning → applying → analyzing → verifying → completed | failed | cancelled`

The UI receives job updates over WebSocket. HTTP requests create jobs and return immediately.

For multi-turn engineering conversations, the configured ForgeCAD engineering model receives the original engineering instruction and relevant design context directly. Jarvis may route a request into ForgeCAD, but should not compress away engineering nuance.

## 13. Component data requirements

Every real component record can contain:

- manufacturer;
- part number;
- category;
- product image(s);
- supplier listings;
- price and availability;
- exact or proxy CAD;
- mounting interfaces;
- envelope;
- mass and center of gravity;
- electrical properties;
- thermal properties;
- mechanical/performance curves;
- operating limits;
- software/firmware target metadata where applicable;
- datasheets;
- field-level provenance and confidence.

Unknown remains unknown. A required unknown property fails a hard engineering constraint rather than being hallucinated.

## 14. Empty/loading/error states

No primary panel is allowed to remain visually functional while its controlling runtime has failed.

Examples:

- renderer initialization failure: replace viewport with an explicit diagnostic state;
- Ollama unavailable: show offline state and remediation; other CAD controls remain active;
- model warming: chat remains interactive and displays warming progress;
- solver unavailable: analysis card explains which external dependency is missing;
- catalog image unavailable: show generated/local fallback thumbnail;
- backend disconnected: global banner and reconnect state; no edits presented as saved.

## 15. Acceptance criteria for the first vertical slice

A v2 vertical slice is accepted only when an automated desktop test can:

1. launch the packaged Electron app;
2. verify backend health;
3. verify the exact configured Ollama model is detected;
4. render a multi-part PBR assembly;
5. orbit the camera;
6. move the explode slider and observe geometry + percentage change;
7. select a component and display its real thumbnail + metadata;
8. switch all bottom tabs;
9. create a design branch;
10. submit an AI request and receive streamed job state;
11. apply a typed CAD edit;
12. open a programmable component's Monaco workspace;
13. save a code change and see it appear in design history;
14. quit and relaunch with state preserved.

A build that fails any of these tests is not a release candidate.
