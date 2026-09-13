# ForgeCAD 3.0.0 Release Record

Status: **COMPLETE / release-validated**

Runtime-validated source SHA: `a5ae8ad5ecc6622498df1e3c8c3688c31ded0afe`

ForgeCAD 3.0.0 is the first release that makes the persistent Physical World Model a supported product surface rather than only a future architecture. It preserves the complete ForgeCAD 2.x engineering workstation while adding stable physical identity, spatial hierarchy, live observations, provenance, deterministic Jarvis entity resolution, capability contracts, world-aware engineering context, a persistent event stream, and the desktop SYSTEM world inspector.

## Release gates

All release gates below completed successfully against the exact runtime source SHA above.

| Gate | Workflow run | Result |
|---|---:|---|
| Full 2.x + 3.0 regression | `34790125504` | PASS |
| Browser SYSTEM world vertical slice | `34790125455` | PASS |
| Windows packaged release | `34790125465` | PASS |
| macOS packaged release, x64 + arm64 | `34790125525` | PASS |

The packaged release gates validate more than artifact generation. They exercise the bundled Forge Engine, `/v3/health`, project-to-world synchronization, Jarvis world context, physical-world planner integration, `.focad` compatibility, the installed application copy, and desktop launch behavior.

## Installer artifacts

### GitHub Actions artifact archives

The hashes below are the digests reported by GitHub for the uploaded artifact ZIP archives.

| Platform | Artifact ID | Archive size | Artifact SHA-256 |
|---|---:|---:|---|
| Windows x64 | `10327592337` | 310,963,262 bytes | `af4661ed2ec81f83d0a001f3bec82e098eca4267cee71c15cc09eb13f31c0c3e` |
| macOS x64 | `10328535594` | 367,205,730 bytes | `f596524ef782291a2435ec3b7ebebbbdd4daf1bcad08f62bfde99f6660291e5d` |
| macOS arm64 | `10328216593` | 342,885,616 bytes | `588eade6b50095ba9586d21303ab051239a790fda7745cb78f328cca07d0c0b3` |

### Installer payloads

The artifact archives were downloaded after the successful exact-SHA workflows, extracted, and independently hashed.

| Platform | Installer | Installer size | Installer SHA-256 |
|---|---|---:|---|
| Windows x64 | `ForgeCAD-Setup-3.0.0.exe` | 310,963,100 bytes | `2cfc2e37c19ad4888393d07ce262987c98fc6690af11e5a68ff779109caccfea` |
| macOS x64 | `ForgeCAD-3.0.0-x64.dmg` | 368,921,226 bytes | `c0f9cecb420750cee996a0d2c87719f8e4064dcbd69c6c0cb9f1e7e5884a9abd` |
| macOS arm64 | `ForgeCAD-3.0.0-arm64.dmg` | 344,703,692 bytes | `d4121e62f9b4688e4f3b9c116feaad4eb1eaf4d6ca5561275cd73477fba4f4f7` |

## Implemented 3.0 surfaces

ForgeCAD 3.0.0 includes:

- persistent world entities with stable IDs;
- hierarchy and SI world-space poses;
- deterministic projection of the active ForgeCAD project into world entities and relations;
- explicit `forgecad_object_id` source links for design-addressable world entities;
- capability and interface contracts;
- live-state observations with source, time, unit, confidence, and metadata;
- provenance that distinguishes designed truth, human declarations, direct observations, inference, and imported data;
- deterministic identity resolution that fails closed on ambiguity;
- compact Jarvis physical-world context;
- world-aware engineering planning without substituting world IDs for CAD IDs;
- authenticated world-event history and WebSocket subscription with catch-up cursors;
- bounded capability execution with explicit confirmation for consequential physical actions;
- desktop SYSTEM world inspection including health, sync state, selected-entity identity, capabilities, interfaces, live state, provenance, and relations;
- automatic project-to-world refresh after canonical project mutations;
- backward compatibility with the existing 2.x engineering core and `.focad` project format.

## Deliberate limits

3.0.0 does not claim general visual SLAM, universal object recognition, unrestricted robot control, arbitrary smart-home integration, general continuous building-scale simulation, autonomous purchasing/fabrication, regulatory certification, or movie-style holography. Those remain later-system problems built on top of the stable identity/provenance/capability/state substrate shipped here.

## Release invariant

The key 3.0 invariant is:

```text
designed truth != observed state != inference
```

A live observation may update live state. It may not silently rewrite authoritative engineering design state. A world entity may drive a CAD edit only through an explicit engineering source link. Jarvis may reason about intent, but identity resolution and canonical state mutation remain deterministic.
