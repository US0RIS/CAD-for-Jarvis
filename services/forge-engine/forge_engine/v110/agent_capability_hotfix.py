from __future__ import annotations

"""Capability-oriented catalog fixes for small local planner models.

The local planner is intentionally constrained to exact component IDs. That is useful for
safety, but it also means a natural-language request can fail if the first ten lexical
catalog matches omit an obvious enabling part. This module adds a real door-contact SKU
and expands a few capability phrases into deterministic catalog candidates without
letting the model invent hardware.
"""

from copy import deepcopy
from typing import Any

from . import component_registry as registry

DOOR_CONTACT_ID = "sensor.adafruit.magnetic_contact_375"
_ORIGINAL_SEARCH = registry.search_components
_INSTALLED = False


def _door_contact() -> dict[str, Any]:
    # Adafruit product 375. Manufacturer page specifies a normally-open reed contact,
    # 29 x 15.2 x 9 mm per half, ~29 cm cable, 100 mA / 200 VDC contact rating and
    # 15 mm maximum operating distance. The component is represented by the sensing
    # half in the current single-object CAD schema; the supplied magnet is recorded in
    # specs so the planner knows it is part of the purchased set.
    raw = {
        "id": DOOR_CONTACT_ID,
        "category": "sensor",
        "manufacturer": "Adafruit",
        "model": "Magnetic contact switch (door sensor) - Product 375",
        "name": "Adafruit Magnetic contact switch (door sensor)",
        "dimensions_mm": [29.0, 15.2, 9.0],
        "mass_g": None,
        "material": "ABS",
        "sensor_type": "door_contact",
        "normally_open": True,
        "rated_current_a": 0.1,
        "rated_voltage_v": 200.0,
        "trigger_distance_mm": 15.0,
        "cable_length_mm": 290.0,
        "included_magnet": True,
        "mechanical_source": "https://www.adafruit.com/product/375",
        "procurement_url": "https://www.adafruit.com/product/375",
        "supplier": "Adafruit",
        "sku": "375",
        "unit_cost_usd": 3.95,
        "tags": [
            "sensor", "door", "drawer", "window", "contact", "magnetic", "magnet",
            "reed", "reed-switch", "open", "closed", "open-close", "switch", "gpio",
            "raspberry-pi", "arduino", "esp32", "security", "automation",
        ],
    }
    item = registry._normalize_legacy(raw)
    # A passive contact is read as a GPIO switch, not as I2C/SPI. Replace the generic
    # sensor bus metadata with an explicit dry-contact interface so mating/validation is
    # meaningful to the engineering agent.
    item["interfaces"] = [
        registry._iface(
            "mount",
            "mount_face",
            position=(0, 0, -4.5),
            axis=(0, 0, -1),
            mate=["sensor_mount", "door_frame"],
        ),
        registry._iface(
            "contact",
            "digital_input",
            position=(14.5, 0, 0),
            axis=(1, 0, 0),
            gender="output",
            mate=["digital_io"],
            required=True,
            metadata={
                "type": "normally_open_dry_contact",
                "rated_current_a": 0.1,
                "rated_voltage_v": 200.0,
                "trigger_distance_mm": 15.0,
                "recommended_logic": "GPIO input with pull-up",
            },
        ),
    ]
    item["trust_score"] = 100
    item["provenance"] = [
        registry._source(
            "manufacturer",
            "https://www.adafruit.com/product/375",
            "Adafruit Magnetic contact switch (door sensor), Product ID 375",
            accessed="2026-09-12",
        )
    ]
    item["geometry"]["source"] = item["provenance"][0]
    return item


def _triggered(text: str, words: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in words)


def _candidate(component_id: str) -> dict[str, Any] | None:
    try:
        return registry.component_by_id(component_id)
    except KeyError:
        return None


def _expanded_search(
    query: str = "",
    category: str | None = None,
    constraints: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
    limit: int = 20,
    include_infeasible: bool = True,
    min_trust: int = 0,
    min_geometry_fidelity: str | None = None,
):
    base = _ORIGINAL_SEARCH(
        query,
        category,
        constraints,
        weights,
        max(limit, 20),
        include_infeasible,
        min_trust,
        min_geometry_fidelity,
    )
    rows = list(base.get("results") or [])
    text = query.lower()
    preferred: list[dict[str, Any]] = []
    related_sensors: list[dict[str, Any]] = []

    # Translate user intent into the actual physical sensing family. A request like
    # "tell me when this door opens" should not require the 8B planner to know that the
    # catalog term it needs is "normally-open magnetic reed contact".
    if _triggered(text, ("door", "drawer", "window", "open", "opened", "closed", "contact")):
        if category in (None, "sensor"):
            door = _candidate(DOOR_CONTACT_ID)
            if door is not None:
                preferred.append(door)
            related = _ORIGINAL_SEARCH(
                "reed magnetic contact hall sensor door open close",
                "sensor" if category in (None, "sensor") else category,
                constraints,
                weights,
                12,
                include_infeasible,
                min_trust,
                min_geometry_fidelity,
            )
            related_sensors.extend(related.get("results") or [])

    # Network notification requests need a programmable networked computer, but that can
    # be an already-inserted Raspberry Pi. Put these immediately after the primary sensor
    # so the planner's ten-candidate context always contains both sides of the solution.
    if _triggered(text, ("discord", "dm", "message", "notify", "notification", "webhook", "internet", "wifi")):
        if category is None:
            for cid in (
                "compute.raspberry_pi_5_8gb",
                "compute.raspberry_pi_zero_2w",
                "mcu.arduino_nano_esp32",
                "mcu.esp32_devkitc",
                "mcu.adafruit_feather_esp32s3",
            ):
                item = _candidate(cid)
                if item is not None:
                    preferred.append(item)

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in preferred + related_sensors + rows:
        cid = str(row.get("id") or "")
        if not cid or cid in seen:
            continue
        if category and str(row.get("category")) != str(category):
            continue
        seen.add(cid)
        merged.append(deepcopy(row))
        if len(merged) >= max(1, int(limit)):
            break

    out = dict(base)
    out["results"] = merged
    # Preserve compatibility with callers that inspect count/returned metadata.
    if "count" in out:
        out["count"] = len(merged)
    if "returned" in out:
        out["returned"] = len(merged)
    return out


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    registry._BUILTIN[DOOR_CONTACT_ID] = _door_contact()
    registry.REGISTRY = list(registry._all_map().values())
    registry.search_components = _expanded_search
    _INSTALLED = True
