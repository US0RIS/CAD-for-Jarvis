from __future__ import annotations

import os

import uvicorn

from forge_engine import main_v31
from forge_engine.v300.planner_world_context import install_world_aware_planner
from forge_engine.v300.world_event_stream import install_world_event_stream


# The packaged desktop engine is ForgeCAD 3.1's production entrypoint. The 3.0
# physical-world integrations still install against the one canonical WORLD store;
# 3.1 adds the engineering graph around that same state instead of creating a
# parallel world/identity system.
install_world_aware_planner(main_v31.v3.WORLD)
install_world_event_stream(
    main_v31.app,
    main_v31.v3.WORLD,
    session_token=main_v31.v3.legacy.SESSION_TOKEN,
    jarvis_token_verifier=main_v31.v3.legacy.jarvis_bridge.verify_token,
)
app = main_v31.app


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
