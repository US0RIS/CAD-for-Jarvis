# ForgeCAD 3.1.0 Release Record

Status: **COMPLETE / release-validated**

Application implementation SHA: `dcfc9269c484629797672e046e9da729740d6e66`

Final macOS release-validation SHA: `cd2b3151f99f8762590b04a79df6004a21ead5af`

ForgeCAD 3.1.0 is the integration release that joins CAD, the Engineering Graph, requirements/evidence, component substitution, manufacturing/DFM, fabrication packages, physical-build feedback, deployed-software drift, semantic branch operations, recovery checkpoints, Product Lab, Jarvis semantic context, and the existing 3.0 Physical World Model into one release-validated system.

No application/runtime code changed after `dcfc9269c484629797672e046e9da729740d6e66`. Later commits through `cd2b3151f99f8762590b04a79df6004a21ead5af` only hardened the macOS release-validation workflow. Documentation-only closure commits follow those validated states.

## Release gates

| Gate | Exact SHA | Workflow run | Result |
|---|---|---:|---|
| Full 3.1 integration + inherited regression | `dcfc9269c484629797672e046e9da729740d6e66` | `34818441403` | PASS |
| Browser/UI vertical slice | `dcfc9269c484629797672e046e9da729740d6e66` | `34818441399` | PASS |
| Windows x64 packaged release | `dcfc9269c484629797672e046e9da729740d6e66` | `34818441373` | PASS |
| macOS arm64 + x64 packaged release | `cd2b3151f99f8762590b04a79df6004a21ead5af` | `34873169268` | PASS |

The packaged gates validate the native bundled Forge Engine, 3.1 health and Engineering Graph readiness, direct CAD feature-history mutation, CAD-to-graph projection, Jarvis 3.1 semantic context, installer/DMG contents, installed-copy execution, and desktop launch behavior.

## GitHub Actions artifact archives

| Platform | Artifact ID | Archive size | GitHub artifact SHA-256 |
|---|---:|---:|---|
| Windows x64 | `10337364492` | 311,102,643 bytes | `8f48c8e9be3ff3b55a3ba43728c25c5bb045132b0d4f504170c38f5e5bfefd66` |
| macOS Apple Silicon | `10360320046` | 344,838,494 bytes | `fee6dc6aa9e82368cfd753c5468a84edbe836bdf49e9ad0831f1471db76639e5` |
| macOS Intel | `10360600996` | 369,070,955 bytes | `df1f139a95deaf89632b247896a0b95c053f62a0b1eb8db1098b614eae87985e` |

## Installer payloads

The successful workflow artifacts were downloaded, extracted, and independently SHA-256 hashed after release validation.

| Platform | Installer | Size | Installer SHA-256 |
|---|---|---:|---|
| Windows x64 | `ForgeCAD-Setup-3.1.0.exe` | 311,102,481 bytes | `b40fb66fafa1f0b899f1bc37c5e21f812292b568fc9d9adaa86795d607b01387` |
| macOS Apple Silicon | `ForgeCAD-3.1.0-arm64.dmg` | 344,838,332 bytes | `7caa5a0a98bc3171220d8a248992196b602f01635fe95419b76b22331ec344ed` |
| macOS Intel | `ForgeCAD-3.1.0-x64.dmg` | 369,070,797 bytes | `ffdca853c9b14d9b401637d67e4605d2b6e96dd99dcea6b9891181323a5cdf55` |

## Implemented 3.1 surfaces

ForgeCAD 3.1.0 includes:

- persistent typed Engineering Graph spanning CAD, components, BOM/procurement, electrical state, software/deployments, requirements/evidence, analyses, manufacturing, physical-world entities, capabilities, and telemetry;
- deterministic dirty/stale propagation and impact analysis;
- direct feature-history CAD API and desktop editing;
- stronger assembly/dependency checks;
- first-class requirements and verification evidence;
- deterministic component substitution and compatibility indexing;
- DFM/process screening;
- high-fidelity external-solver contracts with provenance/validity metadata;
- reproducible fabrication archives;
- physical inspection/deviation feedback;
- deployed software/configuration drift findings;
- semantic three-way branch merge;
- recoverable multi-branch checkpoints;
- bounded requirement → diagnosis → repair → reverification loop;
- `/v3.1/jarvis/context` semantic engineering context;
- Product Lab compact-product profile;
- SYSTEM Engineering Graph/Product Lab inspection;
- keyboard-first deletion and broad shortcut support retained from the 3.0 usability pass;
- backward compatibility with the existing 2.x/3.0 engineering and Physical World Model surfaces.

## Release invariants

3.1 preserves the 3.0 epistemic boundary:

```text
designed truth != observed state != inference
```

It adds the engineering-graph invariant:

```text
canonical engineering identity -> explicit typed relationships -> deterministic impact/invalidation
```

A model may propose changes, diagnoses, and repair plans. Canonical mutation, identity, verification status, solver output, evidence fingerprints, and consequential physical actions remain bounded by deterministic systems and explicit authorization.

## Product Lab boundary

Product Lab is included as a workspace/profile and ontology direction for compact integrated products. 3.1 does not claim a separate full consumer-product CAD application; any later dedicated Product Lab workspace is post-3.1 scope.

## Closure

All committed ForgeCAD 3.1.0 acceptance criteria are satisfied. There are no remaining 3.1.0 implementation or release-validation blockers.
