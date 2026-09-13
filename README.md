# ForgeCAD

ForgeCAD 2.0.0 is a local-first AI engineering workstation: CAD, real-component selection, simulation, design lineage, embedded device code, manufacturing preparation, physical evidence, and autonomous engineering in one desktop application.

This repository is a clean-sheet rebuild. The previous ForgeCAD prototype is not the frontend foundation for this codebase.

## Product contract

The canonical product contract is [docs/PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md), with the desktop visual reference documented in [docs/reference/README.md](docs/reference/README.md). ForgeCAD is intended to feel like working on a real physical object with an engineering copilot beside you, while keeping deterministic engineering state and solver evidence separate from model-generated reasoning.

ForgeCAD 2.0.0 can:

- manipulate exact custom CAD and detailed/verified purchased-component geometry in a shared 3D scene;
- explode, isolate, hide, rotate, inspect, select, and transform assembly parts;
- branch designs like Git, preserve physically verified baselines, and compare canonical engineering state between branches;
- search and insert a 1,400+ component registry with geometry, interfaces, supplier metadata, provenance, and immutable purchased-part identity;
- click a Raspberry Pi or other programmable device and edit its attached code without leaving the project;
- let the local engineering agent modify CAD, code, components, connections, routes, joints, loads, constraints, requirements, safety records, and analyses through typed deterministic operations;
- run 3D solid FEA screening, modal/rigid-body analysis, tolerance stacks, canonical electrical-net validation, steady-state lumped thermal analysis, steady incompressible hydraulic analysis, routed cable/tube checks, and sampled mechanism-kinematic interference screening;
- couple canonical routed tube length into hydraulic resistance instead of duplicating physical dimensions in separate models;
- maintain a canonical failure-mode/safety register whose high-severity hazards require current-design human/evidence verification and cannot be self-certified by the agent;
- launch autonomous multi-branch engineering campaigns against explicit deterministic requirements;
- prepare fabricated geometry for manufacturing, including Bambu Lab P2S fit/orientation/packing checks, 3MF export, and branch-safe oversized-part splitting;
- record physical manufacturing/test evidence against an exact design/package fingerprint so later design changes make old evidence stale rather than silently carrying it forward;
- exchange portable `.focad` projects containing canonical project state, frozen component snapshots, code, branches, and local CAD assets;
- expose the same engineering API to Jarvis while preserving branch protection and audit history.

ForgeCAD labels screening honestly. Its built-in thermal model is not CFD; its fluid solver is steady-state incompressible rather than a general pneumatic/CFD solver; its kinematics solver is currently rigid single-joint sampled motion rather than continuous multibody dynamics. Physical verification and domain-specific certification remain distinct from solver output.

## Architecture

The desktop client uses **Electron + React + TypeScript**. Electron is intentional: ForgeCAD relies heavily on WebGL2, Three.js, Monaco, ES modules, workers, and complex GPU rendering. A bundled Chromium renderer gives macOS and Windows a controlled rendering target.

The engineering core is a separate local Python service using FastAPI, CadQuery/OCP, NumPy/SciPy, and ForgeCAD's deterministic engineering layers. The desktop supervises it, but communicates through explicit HTTP/WebSocket contracts. Long-running AI and solver operations are jobs and do not block the renderer.

See:

- [Product specification](docs/PRODUCT_SPEC.md)
- [Frontend architecture](docs/FRONTEND_ARCHITECTURE.md)
- [Interaction and state contracts](docs/INTERACTION_CONTRACTS.md)

## Platform model defaults

Model choice is a host profile, not a hard-coded global assumption.

- macOS development profile: local Ollama `qwen3:8b`
- Windows engineering profile: configurable local Ollama model

A build must never silently substitute another model. If the configured model is unavailable, the UI reports that state explicitly.

## 2.0.0 release gates

ForgeCAD is not considered release-ready because HTML rendered or an installer was produced. The 2.0.0 branch is gated by deterministic self-tests for canonical CAD/parametrics, scene caching, 3D FEA, project load cases, tolerances, rigid-body dynamics, electrical, thermal, fluid, routing, route-coupled hydraulics, safety, mechanism kinematics, analysis contracts, `.focad` portability, branch diffs, autonomous campaigns, manufacturing, and physical evidence/feedback.

The desktop vertical slice additionally gates component-catalog completeness, canonical geometry thumbnails, `.focad` round-trip, Three.js rendering, selection/transform interaction, manufacturing export/evidence, tolerance UI, all six system-analysis surfaces, and autonomous campaign results. Windows and macOS packaging workflows build and smoke-test the bundled Forge Engine and installed application rather than validating only source-tree imports.

## Repository status

**ForgeCAD 2.0.0 is in release closure on `forgecad/full-v110-scope`.** The complete backend engineering regression is green. Windows packaging has produced and installed a verified 2.0.0 NSIS build successfully; the final release gate is the current cross-platform desktop/installer acceptance run for the exact branch head.
