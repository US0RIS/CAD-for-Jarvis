# ForgeCAD 6.2.1 engineering quality work

Development branch: `forgecad/6.2.1`. This is **not** the published
`v6.2.0` installer. The v6.2.0 release remains immutable.

## Improvements

- Purchased-component fidelity status uses validated asset metadata for its solid
  count. Repeated project instances no longer require the engine to re-import an
  entire STEP assembly merely to answer a geometry-status request. Legacy assets
  without stored verification retain best-effort import.
- Seven parameter-driven **fabricated** mechanical model families are supported
  through canonical CAD, standard transforms, editable parameters, feature history,
  scene tessellation, and `.focad` interchange. These are geometry templates,
  **not** purported manufacturer STEP files.
- The Components panel has an expandable **Fabricated parametric shapes** picker.
  It queries `GET /v6/fabricated-profiles` and inserts a canonical custom part
  through the existing authenticated `POST /v2/operations` route. Purchased
  component identity/BOM is not fabricated for these custom parts.

| Canonical kind | Parameters (all mm except degrees) | Example application |
|---|---|---|
| `hollow_tube` | outer_diameter, inner_diameter, length | bushings, guides, tubing layout |
| `flanged_spool` | core_diameter, flange_diameter, bore_diameter, winding_width, flange_thickness | reel packaging |
| `tapered_nozzle` | inlet_diameter, outlet_diameter, length, wall_thickness | flow-path envelope studies |
| `split_cuff` | outer_diameter, inner_diameter, width, opening_angle_deg | wearable layout |
| `guide_eyelet` | width, depth, thickness, hole_diameter | cable/line routing |
| `u_bracket` | outer_width, depth, height, wall_thickness | chassis and motor mounts |
| `cartridge_cup` | outer_diameter, inner_diameter, height, base_thickness | container packaging |

Users can edit parameters through the same custom-part CAD path and externally
author these `kind` values in `.focad` project objects.

### Honest engineering boundaries

A model's dimensional correctness and valid CAD solid do **not** prove that a
part is printable without process review, pressure-safe, suitable for a human
body, able to hold load, made from a particular material, or physically tested.
The new families are initially generic fabricated reference geometry.
No purchased SKU or manufacturer provenance is inferred from them.

## Required quality gates

`.github/workflows/v621-engineering-quality.yml` runs offline, reproducibly:

1. Seven solid validity checks, tessellation, envelopes, analytical spool/cup/
   bracket volumes, and standard feature-history support.
2. Invalid dimensions, impossible wall clearances, excessive cuff opening, and
   NaN inputs rejected before generating a misleading shape.
3. Portable `.focad` export/import of all seven shapes alongside an unchanged
   purchased Pololu regulator and an explicitly unverified design branch.
4. ForgeCAD 6.2 exact-vs-fallback behavior, vendor identity/source hardening,
   persistent group/material rendering, and repeated status calls with STEP
   import deliberately prohibited.
5. Preserved 6.1 simulation/thermal and 6.0.1 runtime regression suites.
6. Authenticated API discovery, real custom-part add, and scene tessellation.
7. Desktop TypeScript typecheck, tests, and production build.

None of these automated checks is a real-hardware qualification test.
