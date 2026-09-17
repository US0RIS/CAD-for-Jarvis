from __future__ import annotations

"""Cross-vendor component family/compatibility index for ForgeCAD 3.1.

No supplier facts are invented here. The index derives from the normalized local
registry, including manufacturer/distributor packs imported by the user. This lets
Jarvis reason across thousands of parts without coupling engineering logic to any
one vendor API.
"""

from copy import deepcopy
from typing import Any

from ..v110 import component_registry as registry


def _interface_signature(component: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted({str(row.get("kind") or "") for row in component.get("interfaces", []) if row.get("kind")}))


def component_families() -> dict[str, Any]:
    families: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = {}
    for component in registry.all_components():
        key = (str(component.get("category") or "custom"), _interface_signature(component))
        families.setdefault(key, []).append(component)
    rows = []
    for (category, interfaces), components in sorted(families.items(), key=lambda item: (item[0][0], item[0][1])):
        manufacturers = sorted({str(row.get("manufacturer") or "Unknown") for row in components})
        rows.append({
            "id": f"family:{category}:{'+' .join(interfaces) if interfaces else 'no-interface'}",
            "category": category,
            "interfaces": list(interfaces),
            "component_count": len(components),
            "manufacturer_count": len(manufacturers),
            "manufacturers": manufacturers[:50],
            "geometry_fidelity": sorted({str((row.get("geometry") or {}).get("fidelity") or "none") for row in components}),
            "trust_range": [min(int(row.get("trust_score", 0)) for row in components), max(int(row.get("trust_score", 0)) for row in components)],
        })
    return {"items": rows, "count": len(rows), "registry": registry.registry_stats()}


def compatible_components(component_id: str, *, limit: int = 100, require_all_required_interfaces: bool = True) -> dict[str, Any]:
    source = registry.component_by_id(component_id)
    source_required = [row for row in source.get("interfaces", []) if row.get("required")]
    rows = []
    for candidate in registry.all_components(source.get("category")):
        if candidate.get("id") == component_id:
            continue
        mapping = {}
        failures = []
        used: set[str] = set()
        for interface in source_required:
            possibilities = []
            for target in candidate.get("interfaces", []):
                result = registry.interface_compatibility(interface, target)
                if result["compatible"] and str(target.get("id")) not in used:
                    score = int(interface.get("kind") == target.get("kind")) * 2 + int(bool(interface.get("standard")) and interface.get("standard") == target.get("standard")) * 3
                    possibilities.append((-score, str(target.get("id") or ""), target))
            possibilities.sort(key=lambda row: (row[0], row[1]))
            if possibilities:
                target = possibilities[0][2]
                mapping[str(interface.get("id"))] = str(target.get("id"))
                used.add(str(target.get("id")))
            else:
                failures.append(f"No compatible interface for required {interface.get('id')} ({interface.get('kind')})")
        compatible = not failures if require_all_required_interfaces else bool(mapping)
        if not compatible:
            continue
        rows.append({
            "component_id": candidate.get("id"),
            "name": candidate.get("name"),
            "manufacturer": candidate.get("manufacturer"),
            "model": candidate.get("model"),
            "interface_mapping": mapping,
            "required_interface_coverage": 1.0 if not source_required else len(mapping) / len(source_required),
            "dimensions_mm": candidate.get("dimensions_mm"),
            "mass_g": candidate.get("mass_g"),
            "trust_score": candidate.get("trust_score", 0),
            "geometry_fidelity": (candidate.get("geometry") or {}).get("fidelity"),
            "procurement": deepcopy(candidate.get("procurement") or {}),
        })
    rows.sort(key=lambda row: (-float(row["required_interface_coverage"]), -int(row["trust_score"]), str(row["name"])))
    return {"source": source, "items": rows[: max(1, min(1000, int(limit)))], "count": min(len(rows), max(1, min(1000, int(limit))))}


def ecosystem_status() -> dict[str, Any]:
    stats = registry.registry_stats()
    return {
        "registry": stats,
        "catalog_pack_import": True,
        "geometry_asset_import": True,
        "normalized_interfaces": True,
        "cross_vendor_compatibility_index": True,
        "live_supplier_adapters": registry.provider_status(),
        "principle": "Live supplier data is optional and must enter through provenance-bearing adapters; the deterministic local registry remains authoritative for a design revision.",
    }
