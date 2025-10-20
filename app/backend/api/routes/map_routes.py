from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
import random, time

router = APIRouter(prefix="/map", tags=["Map"])

# Serve the Leaflet page directly from frontend/ui/map.html
@router.get("", response_class=HTMLResponse)
def map_page():
    # project_root/backend/api/routes -> up 3 -> project_root
    html_path = Path(__file__).resolve().parents[3] / "frontend" / "ui" / "map.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))

# Replace coordinates with drone coords later
@router.get("/coords")
def coords(source: str | None = None):
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
