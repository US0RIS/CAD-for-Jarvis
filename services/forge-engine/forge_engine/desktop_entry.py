from __future__ import annotations

import os

import uvicorn

from forge_engine import main_v3
from forge_engine.v300.planner_world_context import install_world_aware_planner


# The packaged desktop engine is ForgeCAD 3.0's production entrypoint. Install the
# physical-world context bridge only after main_v3 has created the canonical WORLD
# store, avoiding a second world instance or import-time circular dependency.
install_world_aware_planner(main_v3.WORLD)
app = main_v3.app


def main() -> None:
    port = int(os.environ.get("FORGECAD_PORT", "8765"))
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
