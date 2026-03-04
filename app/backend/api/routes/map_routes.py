from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
import random
import time
from .pistream_routes import telemetry_data
from .pistream_routes import is_flight_enabled, is_pi_stream_alive

router = APIRouter(prefix="/map", tags=["Map"])


@router.get("", response_class=HTMLResponse)
def map_page():
    # ✅ Only block when flight is off.
    # Do NOT block map HTML based on Pi alive, or QtWebEngine can get stuck on error/blank pages.
    if not is_flight_enabled():
        return HTMLResponse("<h2>Backend disabled (flight ended).</h2>", status_code=503)

    html_path = Path(__file__).resolve().parents[3] / "frontend" / "ui" / "map.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@router.get("/coords")
def coords(source: str | None = None):
    # Still block when flight is off
    if not is_flight_enabled():
        return JSONResponse({"error": "Backend disabled (flight ended)."}, status_code=503)

    # ✅ Only gate the DATA by Pi alive
    if not is_pi_stream_alive():
        return JSONResponse({"error": "Pi stream not available."}, status_code=503)

    # Your existing placeholder coords
    lat0, lon0 = 28.6024, -81.2001
    points = []
    for i in range(10):
        points.append({
            "id": i,
            "lat": lat0 + random.uniform(-0.01, 0.01),
            "lon": lon0 + random.uniform(-0.01, 0.01),
            "severity": random.choice(["minor", "moderate", "major"]),
            "ts": time.time()
        })
    return JSONResponse({"points": points})

#Endpoint to get latest telemetry data from drone. 
@router.get("/telemetry")
def get_telemetry():
    return JSONResponse(telemetry_data)
