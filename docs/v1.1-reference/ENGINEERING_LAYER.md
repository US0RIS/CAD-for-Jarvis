# ForgeCAD v1.1

ForgeCAD is a local-first, AI-native mechanical/electromechanical engineering workbench. One canonical project model is shared by the 3D UI, local Qwen engineering agent, embedded-code editor, analysis tools, component registry, and Jarvis bridge. Humans and agents call the same deterministic operations; UI state is never the engineering source of truth.

## What v1.1 changes

v1.0 introduced real-component browsing. v1.1 makes purchased hardware first-class engineering data rather than decorated boxes.

- **Persistent Component Registry.** Component identity, manufacturer/MPN/revision, specifications, provenance, trust score, procurement, geometry fidelity/assets, keepouts, semantic interfaces and software capability are normalized under a versioned schema. The legacy catalog remains available through this model, while manufacturer-sourced entries carry higher trust.
- **Frozen project snapshots.** A project records the exact component definition it was designed against. Registry updates do not silently change a design; synchronization is explicit.
- **Real CAD authority.** Vendor STEP can be imported as reusable catalog hardware. CAD assets are content-addressed, hashed and portable instead of referenced by machine-specific absolute paths. Where an authoritative STEP is unavailable, category-specific deterministic parametric geometry is used and its lower fidelity remains visible.
- **Physical mating and connectivity.** Purchased components expose typed interfaces such as mounting patterns, shafts/bores, power rails, switched loads, GPIO/PWM and airflow. ForgeCAD can validate interface compatibility, mate geometry, and preserve mechanical/electrical connections in the canonical graph.
- **Constraint-aware selection.** Registry queries and the local agent can rank exact components against engineering requirements such as dimensions, voltage/current, torque, geometry fidelity and trust. The planner must use real registry IDs rather than inventing part numbers.
- **System validation.** The connection graph is screened for missing required interfaces, incompatible directions/types, voltage/current mismatches, driver/source limits, logic-level compatibility and duplicate inputs. These checks are deterministic engineering screening, not SPICE or certification.
- **Collision and clearance screening.** Transformed OpenCascade geometry is broad-phase screened and candidate collisions are confirmed with boolean intersection where possible. Semantic keepouts and low-clearance conditions are also reported.
- **Mounting automation that refuses to invent.** ForgeCAD generates hole patterns only when frozen component metadata actually defines the centers. Ambiguous/non-four-hole spacing remains unresolved. Metric fasteners can be selected from the registry by grip and engagement requirements and added to the BOM.
- **Portable projects.** `.forgecad.zip` bundles contain canonical project JSON, frozen component definitions and required geometry assets so the design can be moved to another computer without losing purchased-part geometry.
- **Component-aware BOM lifecycle.** Add/replace/delete operations synchronize purchased-part BOM quantities. Purchased hardware cannot be casually stretched, drilled or mutated as though it were fabricated geometry.
- **Real-system acceptance template.** `/api/templates/v1.1-acceptance` builds a deterministic six-object electromechanical assembly: a fabricated mounting plate plus Raspberry Pi 5, MEAN WELL 12 V supply, Pololu 12→5 V regulator, Adafruit MOSFET driver and Adafruit 12 V solenoid. Its power/control graph, mounting decisions, BOM, geometry clearance and system checks are exercised in CI without relying on an LLM.

The v1.0 capabilities remain: exact CadQuery B-rep primitives and features, STEP import/export, STL export, design branching/history, protected physically verified baselines, embedded programmable-component workspaces, structural/modal/thermal screening, optimization, manufacturing checks, local Ollama/Qwen integration, loopback Jarvis integration, and native pywebview desktop shells.

## Canonical architecture

Key modules:

- `core.py` — project state, exact geometry, project upgrades, history/branches, purchased-component invariants and typed commands.
- `component_registry.py` — persistent schema, provenance/trust, catalog normalization, search/selection, asset resolution and project snapshots.
- `curated_catalog.py` — manufacturer-sourced seed components used where actual electrical/mechanical values matter.
- `component_importers.py` — JSON/ZIP catalog ingestion and vendor STEP → reusable component ingestion.
- `physical_components.py` — deterministic purchased-part geometry, semantic interfaces, mating and connection compatibility.
- `mounting.py` — evidence-based mounting-hole planning and metric fastener selection.
- `system_validation.py` — electrical/control graph screening.
- `assembly_validation.py` — collision, clearance and keepout screening against actual transformed geometry.
- `project_bundle.py` — self-contained `.forgecad.zip` export/import with frozen registry records and assets.
- `acceptance_design.py` — deterministic v1.1 real-system acceptance assembly/template.
- `software.py` — embedded device code workspaces and validation.
- `analysis.py` — transparent design-iteration analysis and optimization.
- `agents.py` — local Ollama planning/review/chat with registry-aware component candidates.
- `jarvis_bridge.py` — loopback discovery/token boundary.
- `server.py` — FastAPI protocol shared by UI, AI and Jarvis.
- `desktop.py` — macOS/Windows desktop host and local engine.
- `static/` — 3D UI, design tabs, registry browser, provenance/fidelity display, analysis and code docks.

## Component trust and geometry fidelity

Component data should be read according to its provenance. Manufacturer-sourced dimensions/specifications can carry high trust; normalized legacy values and generic parametric geometry are intentionally lower-confidence. `component_snapshot` freezes the definition used by a project. `geometry.fidelity` distinguishes authoritative imported CAD from detailed parametric models and envelope proxies.

A purchased component is not editable stock. If a design needs a modified bracket, housing or machined derivative, model that fabricated object separately rather than modifying the purchased component in place.

## Engineering trust boundary

ForgeCAD distinguishes exact CAD geometry, deterministic screening, and physical verification. B-rep construction and boolean collision calculations can be geometrically exact within kernel tolerance, but structural/modal/thermal analyses, system rules, mounting heuristics and clearance rules remain design-iteration screening. Safety-critical, fatigue-sensitive, nonlinear/contact, fluid, high-voltage, regulatory or expensive decisions require appropriate validated engineering workflows and physical testing.

## Development and acceptance

Python 3.12 is the reference environment.

```bash
python -m pip install -r requirements.txt scipy numpy 'httpx>=0.28,<1'
python prepare_frontend.py
python -m compileall -q .
python smoke_test.py
python api_test.py
python acceptance_test.py
python acceptance_api_test.py
python server.py
```

Open `http://127.0.0.1:8765` when running the development server. The OpenAPI contract is available at `/openapi.json` and interactive docs at `/docs`.

The acceptance tests verify exact purchased-part identity, manufacturer-trust snapshots, the 12 V/5 V/control connection graph, system validation, collision-free physical layout, evidence-based mounting, M2.5 fastener selection, STEP export, portable bundle round-trip, and the public acceptance-template API.

## Important v1.1 API surfaces

- `GET /api/components`, `/api/components/schema`, `/api/components/stats`
- `POST /api/components/search`, `/api/components/select`, `/api/components/add/{component_id}`
- `POST /api/components/import`, `/api/components/import-pack`, `/api/components/import-step`
- `POST /api/components/mate`, `/api/components/connect`
- `GET /api/system-check`, `/api/assembly/check`
- `GET /api/mounting/plan/{plate_id}`
- `GET|POST /api/templates/v1.1-acceptance`
- `GET /api/project/bundle`, `POST /api/project/import-bundle`

## Windows release candidate

Run `windows/build.ps1` from this directory. The build derives the application version from `core.APP_VERSION`, runs the full v1.1 regression/acceptance suite, builds the PyInstaller app, self-tests it, and compiles an Inno Setup installer:

- `dist/ForgeCAD/`
- `dist/installer/ForgeCAD-Setup.exe`

The repository workflow `v110-windows-rc.yml` performs the same build on Windows Server 2025 and then installs/smoke-tests the resulting installer.

## macOS release candidate

Run `macos/build.sh` on Apple Silicon macOS. It derives the version from `core.APP_VERSION`, runs the full v1.1 regression/acceptance suite, builds an ad-hoc-signed app, self-tests it, and creates:

- `dist/ForgeCAD-v<version>-macOS-arm64.dmg`
- `dist/ForgeCAD-v<version>-macOS-arm64-app.zip`

The repository workflow `v110-macos-rc.yml` performs this on an Apple Silicon macOS runner. Because the current release process is not Apple-notarized, Gatekeeper may require the standard Control-click → Open first-launch path.
