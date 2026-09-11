# ForgeCAD High-Fidelity Purchased-Component Contract

A component being a real catalog SKU is not sufficient for ForgeCAD to present its geometry as realistic.

For the built-in acceptance assembly, every purchased component must render at **detailed parametric** fidelity or better. Generic mechanical envelopes and bounding boxes are not acceptable release geometry.

Preference order:

1. Manufacturer-provided STEP/CAD when a usable engineering asset is published.
2. Verified STEP/CAD from an authorized distributor when manufacturer delivery is unavailable.
3. Part-specific detailed parametric B-rep derived from manufacturer dimensions and product documentation.
4. Mechanical envelope or bounding box only as an explicitly identified fallback for catalog entries that have not yet been upgraded; these must never be reported as high-fidelity geometry.

The acceptance assembly currently has dedicated high-fidelity geometry for:

- Raspberry Pi 5 8GB
- Adafruit MOSFET Driver / STEMMA, product 5648
- Adafruit Small Push-Pull Solenoid 12VDC, product 412
- MEAN WELL LRS-75-12
- Pololu D24V50F5 5V 5A step-down regulator

`full_scope_selftest` rejects the release if any of those five components resolves below `detailed_parametric` fidelity or through the legacy generic-geometry fallback.

The canonical `/v2/scene` payload publishes `geometry_source`, `geometry_fidelity`, and `geometry_fallback` for each rendered part so clients and tests can distinguish manufacturer CAD from derived geometry.

On normal desktop sessions, components with a published CAD source attempt a bounded first-use STEP download and cache the result locally. Raspberry Pi 5 and Pololu D24V50F5 resolve from manufacturer engineering files; MEAN WELL LRS-75 uses the published distributor CAD package. If a source is unavailable, ForgeCAD falls back to its dedicated part-specific B-rep rather than a generic block. CI disables those network fetches so the detailed offline fallback is independently qualified.

Release qualification must execute this geometry-fidelity gate on the same clean branch head used to build the installer.
