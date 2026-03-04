from fastapi import FastAPI
import asyncio

from .api.routes import webrtc_routes, map_routes, pistream_routes
from .api.controllers.webrtc_controller import close_all_peers

app = FastAPI(title="StormEye AI", version="1.0.0")

app.include_router(webrtc_routes.router)
app.include_router(map_routes.router)
# app.include_router(pistream_routes.router)

# -------------------------------
# System endpoints
# -------------------------------

@app.get("/system/flight/status")
def flight_status():
    return {
        "enabled": pistream_routes.is_flight_enabled(),
        "pi_alive": pistream_routes.is_pi_stream_alive(),
    }


@app.post("/system/flight/start")
async def flight_start():
    pistream_routes.set_flight_enabled(True)
    pistream_routes.resume_pistream()
    return {"enabled": True}


@app.post("/system/flight/end")
async def flight_end():
    pistream_routes.set_flight_enabled(False)
    await close_all_peers()
    pistream_routes.pause_pistream()
    return {"enabled": False}


@app.on_event("startup")
async def startup_event():
    print("🚀 FastAPI started — initializing Pi connection (will wait until flight is started)...")

    # ✅ Ensure backend starts OFF
    pistream_routes.set_flight_enabled(False)
    pistream_routes.pause_pistream()

    asyncio.create_task(pistream_routes.connect_webrtc())
    asyncio.create_task(pistream_routes.telemetry_loop())