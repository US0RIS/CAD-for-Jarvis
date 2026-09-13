from __future__ import annotations

"""Windows CI smoke gate for the ForgeCAD 2.0 design-intelligence import surface.

CadQuery/OCP/VTK load large native extension graphs. On the hosted Windows runner the
short-lived ``python -c`` architecture probe can complete every assertion and print its
PASS line, then return a non-zero process status during native interpreter teardown.
That prevents the workflow from ever reaching the production-like server/browser tests.

This module keeps the smoke test strict while avoiding that teardown-only failure mode:
all imports and assertions run normally, exceptions print a traceback and exit 1, and a
successful probe flushes both streams before terminating without running native module
finalizers. The long-lived packaged/runtime tests still exercise normal application
startup and shutdown, so this is not a substitute for runtime validation.
"""

import os
import sys
import traceback


def run() -> None:
    from . import DESIGN_INTELLIGENCE_VERSION
    from . import design_intelligence as design
    from ..engineering_state import PROJECT

    architecture = design.bootstrap_architecture(
        "notify me when a door is opened",
        PROJECT.snapshot(),
    )
    context = design.build_planner_context(
        "notify me when a door is opened",
        architecture,
        PROJECT.snapshot(),
    )
    assert DESIGN_INTELLIGENCE_VERSION == "2.0.0"
    assert any(
        row.get("capability") == "physical_state_sensing"
        for row in context["functions"]
    )
    assert any(
        row.get("id") == "sensor.adafruit.magnetic_contact_375"
        for row in context["candidate_components"]
    )
    print("ForgeCAD 2.0 Windows architecture smoke: PASS")


def main() -> None:
    exit_code = 0
    try:
        run()
    except BaseException:
        traceback.print_exc()
        exit_code = 1
    finally:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            # os._exit is intentional here; see module docstring. All assertions have
            # already completed and the process has no durable state to flush.
            os._exit(exit_code)


if __name__ == "__main__":
    main()
