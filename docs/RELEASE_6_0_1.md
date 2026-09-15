# ForgeCAD 6.0.1

ForgeCAD 6.0.1 is a correctness and interaction-hardening release on top of the validated 6.0.0 engineering substrate. It does not expand ForgeCAD's physical-validation claims. Its purpose is to make the shipped desktop behave consistently with the canonical design, branch, code, job, and evidence invariants already established by 6.0.0.

## What changed

- Embedded component code saves are serialized and project/branch mutations wait for pending editor writes before replacing canonical state.
- Stateful desktop UX regressions are run serially against the single canonical Forge Engine project, eliminating false cross-test state races.
- Copilot and engineering jobs are tracked independently so a simulation/campaign cannot overwrite the visible state of an active agent task.
- Every queued engineering job is pinned to the exact source branch and project revision. A plan/result that becomes stale fails closed before it can mutate or record against a different design.
- Simulation, campaign, component-search, and deployment work executes as a canonical branch/revision transaction rather than racing the globally active project.
- Non-interruptible worker phases can no longer be reported as cancelled while their underlying calculation continues.
- Human branch-status labels preserve evidence-owned `physical_verified` state server-side; a transient client read or `physical_verified:false` status payload cannot erase recorded evidence.
- Branch activation waits on canonical engineering work without blocking the asyncio event loop.
- Focused browser coverage now proves optimistic delete/undo, normal Copilot Enter/Shift+Enter behavior, offline draft preservation, concurrent agent/engineering-job UI isolation, keyboard guards, and dirty-code persistence across an immediate branch switch.
- A deterministic 6.0.1 engine selftest separately proves branch-persistent embedded code, stale-job rejection, evidence preservation, cross-branch job rejection, and truthful non-interruptible cancellation.

## Native artifacts

The release is published only after source, installed-package, and desktop-launch validation succeeds on all supported release targets:

- `ForgeCAD-Setup-6.0.1.exe` — Windows x64 NSIS installer;
- `ForgeCAD-6.0.1-arm64.dmg` — native Apple Silicon macOS image;
- `ForgeCAD-6.0.1-x64.dmg` — native Intel macOS image;
- `SHA256SUMS.txt` — SHA-256 hashes generated from the exact published binaries.

Native validation also runs the installed Forge Engine over its public HTTP surface, verifies the 6.0.1 runtime identity and release truth contract, loads packaged Cantera data, executes the validated chemistry smoke study, and confirms the desktop starts its bundled engine.

## Compatibility and truth boundaries

6.0.1 preserves the 3.1 browser/integration substrate and the complete 6.0.0 engineering capability set. The patch does not merge the release branch into `main`.

`6.0.1` remains a software release, not a hardware-certification claim. In particular:

```text
designed truth != observed state != inference
```

CI fixtures remain synthetic contract tests. Physical verification remains revision-bound recorded evidence, unsupported physics continues to fail closed, and the release does not claim that a real fabricated device has been built, fitted, load-tested, or certified merely because the software and native installers pass.
