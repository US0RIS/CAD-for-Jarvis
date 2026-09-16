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
    from .release_readiness import run as release_readiness
    result = release_readiness()
    assert result["version"] == "2.0.0"
    assert result["validation_domains_present"] is True
    assert result["planner_contracts_present"] is True
    assert result["project_surface_present"] is True
    print("ForgeCAD 2.0 Windows release smoke: PASS")


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
