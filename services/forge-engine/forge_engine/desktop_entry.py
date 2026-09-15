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
from forge_engine.v601_runtime import install as install_v601_runtime


# ForgeCAD 6.0 development keeps 3.1 as the validated production substrate and
# installs new semantic capabilities additively. A 6.0 capability does not replace
# a 3.1 path until its own acceptance gate proves equivalent or stronger behavior.
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

# 6.0.1 hardens the mutable desktop runtime without altering the frozen 6.0.0
# capability substrate. Existing /v2 route shapes stay compatible while job/branch
# execution gains exact revision provenance and truthful cancellation semantics.
install_v601_runtime(main_v31.app, main_v31.v3.legacy)

# The legacy v2 CORS policy predates the v3.1 parametric feature editor and omits
# PATCH. The desktop renderer is cross-origin in browser acceptance and may also use
# a null/file origin when packaged, so feature parameter edits need an outer policy
# that covers the complete mutable desktop method set. Keep the inner legacy policy
# intact for compatibility and make the desktop entrypoint explicitly complete.
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
