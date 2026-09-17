# ForgeCAD 6.0.0

ForgeCAD 6.0.0 is the first release candidate line validated as a single AI-native physical-engineering environment rather than as disconnected CAD, software, simulation, and physical-test subsystems.

## Release scope

6.0.0 preserves the validated 3.1 canonical Engineering Graph and Physical World substrate and adds:

- geometry-backed mechanical interfaces, full interface frames, mount synthesis/audit, constraint-rank analysis, access envelopes, and standards-backed mount hardware;
- evidence-preserving analysis refresh and bounded multi-strategy autonomous repair;
- revision-bound physical artifacts, metrology, repeated-run/specimen evidence, prediction residuals, and scoped retest closure;
- fail-closed external-solver discovery and real Cantera-backed thermochemistry, equilibrium, kinetics, and zero-dimensional reactor analysis with mechanism SHA-256 provenance;
- one cross-domain release-candidate fixture carrying the same engineering identities through purchased components, custom CAD, assembly, electrical, software, structural analysis, thermal, fluid, tolerance, safety, chemistry, fabrication, redesign/retest, Engineering Graph, Jarvis context, and Physical World state;
- native packaged-runtime validation that runs the actual installed Forge Engine, verifies the 6.0 health contract, loads packaged `gri30.yaml`, and executes a Cantera chemistry study from the public API.

## Native artifacts

The release workflow must pass install-and-run validation before this release is published. Published assets are:

- `ForgeCAD-Setup-6.0.0.exe` — Windows x64 NSIS installer;
- `ForgeCAD-6.0.0-arm64.dmg` — native Apple Silicon macOS image;
- `ForgeCAD-6.0.0-x64.dmg` — native Intel macOS image;
- `SHA256SUMS.txt` — hashes produced from the exact published binaries.

## Validation truth

`6.0.0` denotes a completed software release. It is **not** a hardware certification claim.

The following invariant remains explicit throughout the product:

```text
designed truth != observed state != inference
```

CI physical fixtures are synthetic contract tests. No automated test is presented as proof that a real fabricated device was built, fits, survives load, or is safe. Physical evidence is accepted only against the exact revision/fingerprint actually tested, and a passing scoped retest does not silently verify unrelated requirements.

Similarly, external solver availability is not treated as proof that every geometry or physics regime is supported. Unsupported analysis continues to fail closed rather than fabricate precision.

## Deliberate limitations

- General arbitrary featured-B-rep volume meshing/high-fidelity structural FEA is not claimed; unsupported geometries remain fail-closed unless a validated solver path exists.
- Optional CalculiX, Gmsh, and OpenFOAM installations may be detected, but 6.0.0 does not claim production adapters for every model/case simply because those executables exist.
- Cantera is the validated external chemistry engine in this release; multidimensional reacting-flow CFD is not implied.
- Real-hardware maturity remains separate from software-release completeness and must be established project-by-project with actual measurements and test evidence.

See `docs/ACCEPTANCE_6_0.md` for the acceptance history and maturity boundaries.
