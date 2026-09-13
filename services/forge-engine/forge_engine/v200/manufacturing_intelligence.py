from __future__ import annotations

"""Make available manufacturing resources part of ForgeCAD's design reasoning.

The P2S is not a catalog component.  It is a fabrication capability with a process
envelope, so this adapter adds it to planner context without polluting component
search or pretending the printer is part of the designed assembly.
"""

from copy import deepcopy
from typing import Any

from . import design_intelligence
from . import manufacturing

_INSTALLED = False
_ORIGINAL_BUILD_PLANNER_CONTEXT = None

_PRINT_INTENTS = (
    "3d print", "3d-print", "printable", "printing", "print this", "p2s", "bambu",
    "filament", "slicer", "slice", "fff", "fdm", "manufacture", "fabricate",
)


def _resource_context() -> dict[str, Any]:
    executable = manufacturing.discover_bambu_studio()
    profiles = manufacturing.configured_profiles()
    return {
        **deepcopy(manufacturing.P2S_PROFILE),
        "availability": "configured-local-resource",
        "capabilities": [
            "additive_manufacturing",
            "fff",
            "3mf",
            "orientation",
            "plate_arrangement",
            "slicing",
        ],
        "bambu_studio": {
            "cli_available": bool(executable),
            "executable": executable,
            "profiles_complete": bool(profiles.get("complete")),
            "ready_for_headless_slice": bool(executable and profiles.get("complete")),
        },
        "design_rules": {
            "do_not_assume_printable_from_bounding_box_alone": True,
            "do_not_guess_process_profiles": True,
            "oversize_strategy": "split into fabricated bodies with explicit joints/alignment/fasteners, then revalidate",
            "purchased_components_are_not_printed": True,
        },
    }


def _contains_print_intent(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in _PRINT_INTENTS)


def install() -> None:
    global _INSTALLED, _ORIGINAL_BUILD_PLANNER_CONTEXT
    if _INSTALLED:
        return

    design_intelligence.CAPABILITY_PROFILES["additive_manufacturing"] = {
        # A deliberately impossible catalog category keeps the generic component
        # resolver from returning arbitrary parts. This capability resolves below
        # against the manufacturing-resource registry instead.
        "categories": ["__manufacturing_resource__"],
        "search": [],
        "resource_only": True,
    }
    design_intelligence._KEYWORD_CAPABILITIES[:0] = [
        (
            _PRINT_INTENTS,
            "additive_manufacturing",
            "Fabricate the required custom bodies on the configured Bambu Lab P2S and validate them against the printer/process envelope.",
        )
    ]

    _ORIGINAL_BUILD_PLANNER_CONTEXT = design_intelligence.build_planner_context

    def build_planner_context(text: str, architecture: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
        context = _ORIGINAL_BUILD_PLANNER_CONTEXT(text, architecture, project)
        resource = _resource_context()
        context["available_manufacturing_resources"] = [resource]
        context["manufacturing_policy"] = {
            "primary_additive_resource": manufacturing.P2S_PROFILE["id"],
            "primary_exchange_format": "3mf",
            "slicer": "Bambu Studio",
            "physical_print_start_requires_explicit_user_confirmation": True,
            "direct_printer_control_available": False,
        }

        requested = _contains_print_intent(text)
        for row in context.get("functions") or []:
            if str(row.get("capability")) != "additive_manufacturing":
                continue
            requested = True
            row["kind"] = "manufacturing"
            row["status"] = "manufacturing_resource"
            row["resolution"] = (
                "Use the configured Bambu Lab P2S. Keep each printable body inside the 256 × 256 × 256 mm process envelope, "
                "then export 3MF and validate with explicit Bambu Studio machine/process/filament profiles."
            )
            row["existing_assets"] = []
            row["candidate_components"] = []
            constraints = row.get("constraints") if isinstance(row.get("constraints"), dict) else {}
            row["constraints"] = {
                **constraints,
                "manufacturing_resource_id": manufacturing.P2S_PROFILE["id"],
                "build_volume_mm": deepcopy(manufacturing.P2S_PROFILE["build_volume_mm"]),
                "default_nozzle_mm": manufacturing.P2S_PROFILE["default_nozzle_mm"],
                "primary_exchange_format": "3mf",
            }

        context["manufacturing_requested"] = requested
        return context

    design_intelligence.build_planner_context = build_planner_context
    _INSTALLED = True
