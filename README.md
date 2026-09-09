# ForgeCAD

ForgeCAD is a local-first AI engineering workstation: CAD, real-component selection, simulation, design lineage, embedded device code, and autonomous engineering in one desktop application.

This repository is a clean-sheet rebuild. The previous ForgeCAD prototype is not the frontend foundation for this codebase.

## Product contract

The target interface is not approximate. `docs/reference/forgecad-target-ui.png` is the canonical visual reference for desktop composition, density, hierarchy, and interaction placement. The implementation should converge toward that reference rather than reinterpret it into a generic CAD UI.

The product should feel like working on a real physical object with an expert engineer beside you:

- manipulate a photorealistic assembly directly;
- explode, isolate, hide, rotate, inspect, and select actual components;
- branch designs like Git and preserve physically verified baselines;
- compare failed variants against known-good designs;
- search and insert real purchasable components with images, supplier data, cost, geometry, electrical/thermal/mechanical behavior, and provenance;
- click a Raspberry Pi or other programmable device and edit its attached code without leaving the project;
- let the local engineering agent modify CAD, code, components, and analyses through typed deterministic tools;
- run structural, modal, thermal, airflow, dynamics, tolerance, and external-solver workflows without freezing the UI;
- launch autonomous multi-branch engineering campaigns against explicit requirements;
- expose the same engineering tool API to Jarvis for remote voice control while preserving branch protection and audit history.

## Architecture decisions

The desktop client uses **Electron + React + TypeScript**. Electron is intentional: ForgeCAD relies heavily on WebGL2, Three.js, Monaco, ES modules, workers, WASM, and complex GPU rendering. A bundled Chromium renderer gives us one known rendering target on macOS and Windows instead of repeating the WebView compatibility failures from the prototype.

The engineering core remains a separate local Python service using FastAPI and established engineering libraries/solvers. The desktop process supervises it, but the UI communicates with it only through explicit HTTP/WebSocket contracts. Long-running AI and solver operations are jobs; they never block the renderer.

See:

- [Product specification](docs/PRODUCT_SPEC.md)
- [Frontend architecture](docs/FRONTEND_ARCHITECTURE.md)
- [Interaction and state contracts](docs/INTERACTION_CONTRACTS.md)

## Platform model defaults

Model choice is a host profile, not a hard-coded global assumption.

- macOS development profile: local Ollama `qwen3:8b`
- Windows engineering profile: configurable local Ollama model

A build must never silently substitute another model. If the configured model is unavailable, the UI reports that state explicitly.

## Non-negotiable release gates

ForgeCAD is not considered launch-ready because HTML rendered. A desktop release must pass automated checks for: frontend bootstrap, Three.js scene creation, camera controls, explode slider, tab switching, component-card rendering, Ollama status, chat submission, streamed job progress, design branching, code editor activation, and backend health. Any uncaught JavaScript bootstrap failure is a hard launch failure, not a warning.

## Repository status

This repository currently contains the v2 product specification and frontend architecture that define the clean-sheet implementation. The next commits build the shell and vertical slice directly against those contracts.
