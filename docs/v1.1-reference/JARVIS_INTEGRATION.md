# ForgeCAD ↔ Jarvis integration

ForgeCAD v1 can be operated from Jarvis without exposing the CAD/CAE service to the public Internet.

```text
Meta glasses / iPhone
        ↓ existing Jarvis authenticated transport
Jarvis Windows host
        ↓ ForgeCAD tool family
127.0.0.1 only
        ↓ X-ForgeCAD-Jarvis-Key
ForgeCAD Engine
        ↓
canonical design + component registry + code + analysis + lineage
```

ForgeCAD writes a loopback discovery record with a per-install random token to its platform data directory (`%LOCALAPPDATA%\\ForgeCAD\\jarvis_bridge.json` on Windows). Remote authentication remains Jarvis's responsibility; the ForgeCAD token protects only the local application protocol from accidental/untrusted callers.

## Native tool surface

The engine exposes token-protected endpoints corresponding to:

- `forgecad.status`
- `forgecad.summary`
- `forgecad.designs`
- `forgecad.history`
- `forgecad.diff`
- `forgecad.component_select`
- `forgecad.reality_scan`
- `forgecad.analyze`
- `forgecad.change`

`forgecad.change` requests are planned by local Qwen and applied as typed ForgeCAD operations. By default, Jarvis creates a `jarvis-*` child branch **before the first remote mutation**, preserving a known-good or physically verified design. ForgeCAD never automatically marks a remote result as working in real life.

The normal desktop process and `ForgeCAD.exe --headless` / `ForgeCAD --headless` expose the same engine. The service listens only on loopback.

## Jarvis plugin installer

The source tree includes `integrations/jarvis/install.py` and a reference plugin module. Point the installer at a local `Jarvis-for-MRB` checkout. The integration is opt-in and does not alter Jarvis's remote transport.

## Engineering trust

Remote convenience does not upgrade solver fidelity. ForgeCAD continues to expose stale analyses, validation gaps and physical-verification state. Safety-critical or expensive designs still require validated solver workflows and physical testing.
