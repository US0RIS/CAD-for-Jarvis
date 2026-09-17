from __future__ import annotations

"""Deterministic regression test for ForgeCAD 2.0 electrical design intelligence."""

from ..engineering_state import PROJECT
from ..v110 import core
from . import electrical_design


def _add_component(component_id: str) -> str:
    before = {str(obj.get("id")) for obj in core.PROJECT.get("objects", [])}
    core.execute(
        "add_component",
        {"component_id": component_id},
        actor="human",
        reason=f"Electrical self-test: add {component_id}",
    )
    created = [
        obj for obj in core.PROJECT.get("objects", [])
        if str(obj.get("id")) not in before
    ]
    assert len(created) == 1, (component_id, len(created))
    return str(created[0]["id"])


def _connect(
    a_id: str,
    a_interface: str,
    b_id: str,
    b_interface: str,
    *,
    net_name: str,
    voltage_v: float,
) -> str:
    before = {
        str(connection.get("id"))
        for connection in core.PROJECT.get("connections", [])
        if isinstance(connection, dict)
    }
    core.execute(
        "connect_interfaces",
        {
            "a_id": a_id,
            "a_interface": a_interface,
            "b_id": b_id,
            "b_interface": b_interface,
            "kind": "electrical",
            "net_name": net_name,
            "net_class": "power",
            "nominal_voltage_v": voltage_v,
        },
        actor="human",
        reason=f"Electrical self-test: connect {net_name}",
    )
    created = [
        connection for connection in core.PROJECT.get("connections", [])
        if isinstance(connection, dict) and str(connection.get("id")) not in before
    ]
    assert len(created) == 1
    connection = created[0]
    assert connection["net_name"] == net_name
    assert connection["net_class"] == "power"
    assert float(connection["nominal_voltage_v"]) == voltage_v
    return str(connection["id"])


def run() -> dict[str, object]:
    PROJECT.new_project()

    supply = _add_component("power.meanwell.lrs_75_12")
    regulator = _add_component("power.pololu.d24v50f5")
    fan = _add_component("fan.noctua.nf_a4x10_5v")

    twelve_v = _connect(
        supply,
        "dc_out",
        regulator,
        "vin",
        net_name="+12V",
        voltage_v=12.0,
    )
    five_v = _connect(
        regulator,
        "vout",
        fan,
        "power",
        net_name="+5V",
        voltage_v=5.0,
    )

    # Net metadata is applied by the v2 layer after the underlying v1.1 connection
    # mutation. Prove that undoing a *subsequent* operation does not resurrect a stale
    # pre-metadata connection snapshot.
    core.execute(
        "add_note",
        {"text": "Electrical history sentinel"},
        actor="human",
        reason="Electrical self-test: history sentinel",
    )
    assert core.undo()
    five_v_after_undo = next(
        connection
        for connection in core.PROJECT.get("connections", [])
        if isinstance(connection, dict) and str(connection.get("id")) == five_v
    )
    assert five_v_after_undo["net_name"] == "+5V"
    assert five_v_after_undo["net_class"] == "power"
    assert float(five_v_after_undo["nominal_voltage_v"]) == 5.0
    assert core.redo()

    schematic = electrical_design.compile_schematic(core.PROJECT)
    assert schematic["solver"] == "ForgeCAD ElectricalGraph"
    assert schematic["solver_version"] == "2.0.0"
    assert schematic["net_count"] == 2
    nets = {str(net["name"]): net for net in schematic["nets"]}
    assert set(nets) == {"+12V", "+5V"}
    assert float(nets["+12V"]["nominal_voltage_v"]) == 12.0
    assert float(nets["+5V"]["nominal_voltage_v"]) == 5.0
    assert nets["+5V"]["class"] == "power"
    assert float(nets["+5V"]["known_load_current_a"]) > 0.0

    clean = electrical_design.analyze_electrical(core.PROJECT)
    clean_error_codes = {
        str(risk.get("code"))
        for risk in clean["risks"]
        if risk.get("severity") == "error"
    }
    assert "voltage_mismatch" not in clean_error_codes
    assert "overvoltage" not in clean_error_codes
    assert clean["coverage"]["power_nets"] == 2
    # The open-frame supply's required AC input intentionally remains an external
    # boundary in this isolated rail test, so it may be warning-level but not a hard
    # electrical design failure.
    assert clean["counts"]["error"] == 0, clean["risks"]

    core.execute(
        "label_electrical_net",
        {
            "connection_id": five_v,
            "name": "VLOGIC",
            "net_class": "power",
            "nominal_voltage_v": 5.0,
        },
        actor="human",
        reason="Electrical self-test: relabel logic rail",
    )
    relabelled = electrical_design.compile_schematic(core.PROJECT)
    relabelled_nets = {str(net["name"]): net for net in relabelled["nets"]}
    assert "VLOGIC" in relabelled_nets
    assert "+5V" not in relabelled_nets
    assert five_v in relabelled_nets["VLOGIC"]["connection_ids"]
    assert twelve_v in {cid for net in relabelled["nets"] for cid in net["connection_ids"]}

    # Add a second otherwise-valid regulator/fan branch and deliberately label its 5 V
    # output as the same VLOGIC rail. Point-to-point interface checks accept each edge;
    # only the v2 canonical-net layer can see that two independent power outputs have
    # been electrically tied together without a verified current-sharing scheme.
    regulator_2 = _add_component("power.pololu.d24v50f5")
    fan_2 = _add_component("fan.noctua.nf_a4x10_5v")
    _connect(
        supply,
        "dc_out",
        regulator_2,
        "vin",
        net_name="+12V",
        voltage_v=12.0,
    )
    _connect(
        regulator_2,
        "vout",
        fan_2,
        "power",
        net_name="VLOGIC",
        voltage_v=5.0,
    )
    failed = electrical_design.analyze_electrical(core.PROJECT)
    failed_codes = {
        str(risk.get("code"))
        for risk in failed["risks"]
        if risk.get("severity") == "error"
    }
    assert not failed["ok"]
    assert "parallel_power_sources_unverified" in failed_codes, failed["risks"]

    # The project-wide validation surface used by the autonomous repair loop must carry
    # the same hard electrical failure.
    project_validation = PROJECT.validation()
    project_codes = {
        str(risk.get("code"))
        for risk in project_validation["risks"]
        if risk.get("severity") == "error"
    }
    assert "parallel_power_sources_unverified" in project_codes
    assert project_validation["electrical"]["ok"] is False

    return {
        "solver": schematic["solver"],
        "clean_nets": schematic["net_count"],
        "clean_power_nets": clean["coverage"]["power_nets"],
        "clean_errors": clean["counts"]["error"],
        "bad_design_errors": failed["counts"]["error"],
        "parallel_source_conflict_detected": True,
        "repair_loop_validation_gated": True,
        "history_metadata_preserved": True,
        "net_relabel_persisted": True,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 electrical design self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
