from __future__ import annotations

import os

import uvicorn
from fastapi.middleware.cors import CORSMiddleware

from forge_engine import main_v31
from forge_engine.v300.planner_world_context import install_world_aware_planner
from forge_engine.v300.world_event_stream import install_world_event_stream
from forge_engine.v310.ecosystem_api import install as install_ecosystem_api
from forge_engine.v310.feature_api import install as install_feature_api
from forge_engine.v310.integration_api import install as install_integration_api
from forge_engine.v600.api import install as install_v600_api
from forge_engine.v600.milestone3_api import install as install_v600_milestone3_api
from forge_engine.v600.milestone4_api import install as install_v600_milestone4_api
from forge_engine.v600.milestone5_api import install as install_v600_milestone5_api
from forge_engine.v600.milestone6_api import install as install_v600_milestone6_api
from forge_engine.v601_ollama_runtime import install as install_v601_ollama_runtime
from forge_engine.v601_runtime import install as install_v601_runtime
from forge_engine.v601_scene_runtime import install as install_v601_scene_runtime
from forge_engine.v610.api import install as install_v610_api
from forge_engine.v610.simulation_extensions import install as install_v610_simulation_extensions


# ForgeCAD 6.x keeps 3.1 as the validated desktop substrate and installs semantic,
# physical-engineering and simulation capabilities additively. A newer capability does
# not replace a validated path until its own acceptance gate proves equivalent or
# stronger behavior.
install_world_aware_planner(main_v31.v3.WORLD)
install_world_event_stream(
    main_v31.app,
    main_v31.v3.WORLD,
    session_token=main_v31.v3.legacy.SESSION_TOKEN,
    jarvis_token_verifier=main_v31.v3.legacy.jarvis_bridge.verify_token,
)
install_feature_api(
    main_v31.app,
    main_v31.v3.legacy.require_session,
    main_v31.v3.legacy.broadcast,
    main_v31.v3.legacy.PROJECT.snapshot,
)
install_ecosystem_api(main_v31.app, main_v31.v3.legacy.require_session)
install_integration_api(
    main_v31.app,
    main_v31.v3.legacy.require_session,
    main_v31.GRAPH,
    main_v31.v3.legacy.PROJECT.snapshot,
    main_v31.v3.WORLD,
    main_v31.v3._sync_current_project,
    main_v31._sync_graph,
)
install_v600_api(
    main_v31.app,
    main_v31.v3.legacy.require_session,
    main_v31.v3._sync_current_project,
    main_v31._sync_graph,
)
install_v600_milestone3_api(
    main_v31.app,
    main_v31.v3.legacy.require_session,
    main_v31.GRAPH,
    main_v31.v3.WORLD,
    main_v31.v3._sync_current_project,
    main_v31._sync_graph,
)
install_v600_milestone4_api(
    main_v31.app,
    main_v31.v3.legacy.require_session,
    main_v31.GRAPH,
    main_v31.v3.WORLD,
    main_v31.v3._sync_current_project,
    main_v31._sync_graph,
)
install_v600_milestone5_api(
    main_v31.app,
    main_v31.v3.legacy.require_session,
    main_v31.GRAPH,
    main_v31._sync_graph,
)
install_v600_milestone6_api(
    main_v31.app,
    main_v31.v3.legacy.require_session,
    main_v31.GRAPH,
    main_v31._sync_graph,
)

# The packaged app must discover the same local Ollama daemon the user's terminal sees.
install_v601_ollama_runtime(main_v31.v3.legacy)

# 6.0.1 hardens mutable desktop runtime behavior and viewport geometry startup.
install_v601_runtime(main_v31.app, main_v31.v3.legacy)
install_v601_scene_runtime(main_v31.v3.legacy.PROJECT)

# 6.1 turns canonical mechanical connectivity and analysis inputs into one executable
# simulation state. Viewport transforms propagate through the joint tree, joint
# actuation moves complete downstream subassemblies, and every simulation result is
# fingerprinted and invalidated by subsequent canonical edits.
install_v610_api(
    main_v31.app,
    main_v31.v3.legacy.require_session,
    main_v31.v3._sync_current_project,
    main_v31._sync_graph,
    main_v31.v3.legacy.PROJECT.snapshot,
    main_v31.v3.legacy.broadcast,
)
install_v610_simulation_extensions(
    main_v31.app,
    main_v31.v3.legacy.require_session,
    snapshot=main_v31.v3.legacy.PROJECT.snapshot,
    broadcast=main_v31.v3.legacy.broadcast,
)

# The legacy v2 CORS policy predates the v3.1 parametric feature editor and omits
# PATCH. Keep the outer desktop policy complete for all current mutable methods.
main_v31.app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=[
        "Content-Disposition",
        "X-ForgeCAD-Package-SHA256",
        "X-ForgeCAD-Branch",
        "X-ForgeCAD-3MF-Stage",
        "X-ForgeCAD-Manufacturing-Resource",
        "X-ForgeCAD-Thumbnail-Source",
    ],
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
