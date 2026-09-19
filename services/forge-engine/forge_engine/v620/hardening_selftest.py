from __future__ import annotations

"""Deterministic acceptance for ForgeCAD 6.2 exact-CAD identity hardening."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile

import cadquery as cq

from . import component_fidelity as fidelity
from . import component_fidelity_hardening as hardening


def _component() -> dict:
    return {
        "schema_version": 1,
        "id": "fixture.vendor.identity-stepper",
        "category": "stepper_motor",
        "manufacturer": "Fixture Motion",
        "model": "IDENTITY-42",
        "name": "Fixture Motion IDENTITY-42",
        "manufacturer_part_number": "IDENTITY-42",
        "dimensions_mm": [42.0, 42.0, 48.0],
        "geometry": {
            "preferred": "official_step",
            "fidelity": "detailed_parametric",
            "dimensions_mm": [42.0, 42.0, 48.0],
            "assets": [],
            "asset_sources": [
                {
                    "url": "https://manufacturer.example/products/IDENTITY-42",
                    "kind": "manufacturer",
                }
            ],
        },
        "interfaces": [],
        "keepouts": [],
        "procurement": {},
        "software": {"programmable": False, "platform": None},
        "provenance": [
            {
                "kind": "manufacturer",
                "trust": 100,
                "url": "https://manufacturer.example/products/IDENTITY-42",
                "title": "Fixture Motion IDENTITY-42",
            }
        ],
        "trust_score": 100,
    }


def _export(shape, path: Path) -> bytes:
    cq.exporters.export(shape, str(path))
    data = path.read_bytes()
    assert len(data) > 800
    return data


def run() -> dict:
    hardening.install()
    component = _component()
    source_url = "https://manufacturer.example/products/IDENTITY-42"

    with tempfile.TemporaryDirectory(prefix="forgecad-v620-hardening-") as temp_dir:
        root = Path(temp_dir)

        # A perfectly valid STEP is still the wrong product if its physical envelope is
        # incompatible with the purchased SKU. Parsing successfully must never be enough.
        wrong_data = _export(cq.Workplane("XY").box(180.0, 120.0, 90.0).val(), root / "wrong.step")
        wrong_verification = fidelity._validate_step_bytes(wrong_data, component_id=component["id"])
        assert wrong_verification["solid_count"] >= 1
        rejected = False
        try:
            hardening._verify_component_identity(
                component,
                wrong_verification,
                source_url=source_url,
                resolved_url="https://manufacturer.example/files/IDENTITY-42.step",
                metadata={},
                data=wrong_data,
            )
        except ValueError as exc:
            rejected = "incompatible" in str(exc)
        assert rejected, "A syntactically valid STEP for the wrong physical product must fail closed"

        # A real product assembly can extend beyond the nominal motor body because of a
        # shaft, connector, or wire. Accept that when a constituent solid matches the
        # declared product body instead of forcing the whole-assembly bounding box to fit.
        body = cq.Workplane("XY").box(42.0, 42.0, 48.0).val()
        shaft = cq.Workplane("XY").circle(2.5).extrude(38.0).val().translate((0.0, 0.0, 24.0))
        tail = cq.Workplane("XY").box(8.0, 110.0, 5.0).val().translate((0.0, -70.0, -10.0))
        plausible = cq.Compound.makeCompound([body, shaft, tail])
        plausible_data = _export(plausible, root / "plausible.step")
        plausible_verification = fidelity._validate_step_bytes(plausible_data, component_id=component["id"])
        evidence = hardening._verify_component_identity(
            component,
            plausible_verification,
            source_url=source_url,
            resolved_url="https://manufacturer.example/files/IDENTITY-42.step",
            metadata={},
            data=plausible_data,
        )
        assert evidence["component_id"] == component["id"]
        assert evidence["matching_body_solid"] is True or evidence["assembly_envelope_match"] is True

        # Geometry plausibility alone is not identity. An unrelated high-trust source
        # with no explicit component binding or MPN/model token must also fail closed.
        unbound = deepcopy(component)
        unbound["geometry"]["asset_sources"] = []
        unbound["provenance"] = []
        source_rejected = False
        try:
            hardening._verify_component_identity(
                unbound,
                plausible_verification,
                source_url="https://manufacturer.example/downloads/cad-model.step",
                resolved_url="https://cdn.example/cad/opaque.step",
                metadata={},
                data=plausible_data,
            )
        except ValueError as exc:
            source_rejected = "not explicitly bound" in str(exc)
        assert source_rejected, "Plausible geometry from an unbound source must not acquire SKU identity"

        # Background geometry completion uses a monotonic generation signal. Desktop
        # polling relies on this to replace a temporary fallback without mutating design
        # history or inventing a new engineering revision.
        generation_before = hardening.asset_generation()
        hardening._bump_generation()
        generation_after = hardening.asset_generation()
        assert generation_after == generation_before + 1

        return {
            "ok": True,
            "version": "6.2.1",
            "checks": {
                "valid_wrong_step_rejected": True,
                "extended_assembly_with_matching_body_accepted": True,
                "source_identity_required": True,
                "background_asset_generation_monotonic": True,
            },
            "plausible_identity": evidence,
        }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
