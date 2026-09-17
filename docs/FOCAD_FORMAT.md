# `.focad` — ForgeCAD Design Exchange Format

`.focad` is ForgeCAD's portable design file. It is designed for two workflows:

1. move a complete design between ForgeCAD installations; and
2. export a design from ForgeCAD, give it to an external engineering agent such as ChatGPT for higher-capability design work, then import the resulting `.focad` back into ForgeCAD.

## Container

A `.focad` file is a ZIP container with the MIME type:

`application/vnd.forgecad.project+zip`

The file extension is always `.focad` for newly exported designs. ForgeCAD 1.1.2 also accepts legacy `.forgecad.zip` bundles when opening a design.

## Required files

Every version-1 `.focad` contains:

- `manifest.json` — format/version metadata.
- `project.json` — the canonical ForgeCAD design model.
- `components.json` — frozen purchased-component snapshots used by the design.

It may also contain:

- `assets/**` — STEP/CAD assets referenced by component snapshots.

A minimal manifest is:

```json
{
  "format": "focad",
  "format_name": "ForgeCAD Design",
  "format_version": 1,
  "bundle_version": 1,
  "project_file": "project.json",
  "component_file": "components.json"
}
```

`bundle_version` is retained for compatibility with ForgeCAD 1.1-era project bundles.

## External-agent workflow

1. In ForgeCAD, choose **Export .focad**.
2. Upload the `.focad` file to ChatGPT and describe the design change you want.
3. ChatGPT can inspect `project.json`, component snapshots, code workspaces, and embedded CAD assets; create or modify canonical objects; and return a new `.focad` file.
4. In ForgeCAD, choose **Open .focad**.
5. ForgeCAD validates the container, restores embedded assets/components, loads the canonical project, and re-tessellates the 3D scene locally.

This allows a more capable external model to perform the design/planning work without making ForgeCAD depend on that model at runtime.

## Authoring contract

Externally authored files must preserve the canonical ForgeCAD project schema. In particular:

- Units are millimeters unless a field explicitly declares another unit.
- Existing object IDs should remain stable when the same physical object is being edited.
- Purchased parts should retain their `component_ref` and frozen `component_snapshot`; do not scale purchased-component geometry to make it fit.
- Fabricated/imported geometry and transforms belong in the project's object records.
- Branch/history information should be retained when modifying an existing project.
- Embedded component assets must use relative paths under `assets/`; absolute machine-local paths are not portable.
- ZIP entries may not escape the archive root (`..` traversal is rejected).

## Trust and verification

Importing a `.focad` file does **not** make the design physically verified. An externally generated design is engineering input, not certification. ForgeCAD's deterministic validation, simulation/screening checks, and any required physical testing should be rerun after import before marking a design as working or physically verified.

## Versioning

Current format version: **1**.

Readers reject unsupported format versions instead of silently interpreting them with the wrong schema. Future ForgeCAD versions should remain able to import version-1 files or provide an explicit migration path.
