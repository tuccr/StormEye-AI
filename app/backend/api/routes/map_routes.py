from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from pathlib import Path
import mimetypes
import sqlite3
import time

from .pistream_routes import telemetry_data
from .pistream_routes import is_flight_enabled

router = APIRouter(prefix="/map", tags=["Map"])

UI_DIR = Path(__file__).resolve().parents[3] / "frontend" / "ui"
HTML_PATH = UI_DIR / "map.html"
LEAFLET_DIR = UI_DIR / "vendor" / "leaflet"
MBTILES_PATH = UI_DIR / "offline_map.mbtiles"

_gps_trail: list[dict] = []
_MAX_TRAIL_POINTS = 150


def _valid_gps(lat: float, lon: float) -> bool:
    try:
        lat = float(lat)
        lon = float(lon)
    except Exception:
        return False
    return (
        lat != 0.0
        and lon != 0.0
        and -90.0 <= lat <= 90.0
        and -180.0 <= lon <= 180.0
    )


def _append_trail(lat: float, lon: float, ts: float) -> None:
    if not _gps_trail:
        _gps_trail.append({"lat": lat, "lon": lon, "ts": ts})
        return
    last = _gps_trail[-1]
    if abs(last["lat"] - lat) > 1e-7 or abs(last["lon"] - lon) > 1e-7:
        _gps_trail.append({"lat": lat, "lon": lon, "ts": ts})
    if len(_gps_trail) > _MAX_TRAIL_POINTS:
        del _gps_trail[:-_MAX_TRAIL_POINTS]


def _mbtiles_exists() -> bool:
    return MBTILES_PATH.exists() and MBTILES_PATH.is_file()


def _xyz_to_tms_y(z: int, y: int) -> int:
    return (2 ** z - 1) - y


def _detect_mbtiles_format(conn: sqlite3.Connection) -> str:
    try:
        cur = conn.execute("SELECT value FROM metadata WHERE name = 'scheme'")
        row = cur.fetchone()
        if row and str(row[0]).strip().lower() == "xyz":
            return "xyz"
    except Exception:
        pass
    return "tms"


def _detect_tile_mime(tile_bytes: bytes) -> str:
    if tile_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if tile_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if tile_bytes[:4] == b"RIFF" and tile_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _get_mbtiles_metadata() -> dict:
    if not _mbtiles_exists():
        return {}

    conn = sqlite3.connect(str(MBTILES_PATH))
    try:
        rows = conn.execute("SELECT name, value FROM metadata").fetchall()
        return {str(k): str(v) for k, v in rows}
    except Exception:
        return {}
    finally:
        conn.close()


def _parse_mbtiles_bounds() -> list[list[float]] | None:
    """
    Returns Leaflet-style bounds:
      [[south, west], [north, east]]
    from MBTiles metadata 'bounds' = west,south,east,north
    """
    meta = _get_mbtiles_metadata()
    raw = meta.get("bounds")
    if not raw:
        return None

    try:
        west, south, east, north = [float(x.strip()) for x in raw.split(",")]
        if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= 90 and -90 <= north <= 90):
            return None
        return [[south, west], [north, east]]
    except Exception:
        return None


def _get_mbtiles_minmax_zoom() -> tuple[int | None, int | None]:
    meta = _get_mbtiles_metadata()

    minzoom = None
    maxzoom = None

    try:
        if "minzoom" in meta:
            minzoom = int(meta["minzoom"])
    except Exception:
        pass

    try:
        if "maxzoom" in meta:
            maxzoom = int(meta["maxzoom"])
    except Exception:
        pass

    return minzoom, maxzoom


def _get_tile_from_mbtiles(z: int, x: int, y_xyz: int) -> tuple[bytes, str] | None:
    if not _mbtiles_exists():
        return None

    conn = sqlite3.connect(str(MBTILES_PATH))
    try:
        scheme = _detect_mbtiles_format(conn)
        tile_bytes = None

        y_to_try = [y_xyz] if scheme == "xyz" else [_xyz_to_tms_y(z, y_xyz)]
        alt_y = _xyz_to_tms_y(z, y_xyz) if y_to_try[0] == y_xyz else y_xyz
        if alt_y not in y_to_try:
            y_to_try.append(alt_y)

        for tile_y in y_to_try:
            cur = conn.execute(
                """
                SELECT tile_data
                FROM tiles
                WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?
                LIMIT 1
                """,
                (z, x, tile_y),
            )
            row = cur.fetchone()
            if row and row[0]:
                tile_bytes = row[0]
                break

        if not tile_bytes:
            return None

        mime = _detect_tile_mime(tile_bytes)
        return tile_bytes, mime
    finally:
        conn.close()


@router.get("", response_class=HTMLResponse)
def map_page():
    if not is_flight_enabled():
        return HTMLResponse("<h2>Backend disabled (flight ended).</h2>", status_code=503)

    if not HTML_PATH.exists():
        return HTMLResponse("<h2>map.html not found.</h2>", status_code=500)

    return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))

@router.get("/coords")
def coords():
    if not is_flight_enabled():
        return JSONResponse({"error": "Backend disabled (flight ended)."}, status_code=503)

    lat = float(telemetry_data.get("lat", 0.0) or 0.0)
    lon = float(telemetry_data.get("lon", 0.0) or 0.0)
    alt = float(telemetry_data.get("alt", 0.0) or 0.0)
    heading = int(telemetry_data.get("heading", 0) or 0)
    battery = int(telemetry_data.get("battery", 0) or 0)
    speed = float(telemetry_data.get("speed", 0.0) or 0.0)
    connected = bool(telemetry_data.get("connected", False))
    now = time.time()

    has_fix = connected and _valid_gps(lat, lon)

    if has_fix:
        _append_trail(lat, lon, now)

    return JSONResponse({
        "connected": connected,
        "has_fix": has_fix,
        "drone": {
            "id": "drone",
            "lat": lat,
            "lon": lon,
            "alt": alt,
            "heading": heading,
            "battery": battery,
            "speed": speed,
            "ts": now,
        },
        "trail": list(_gps_trail) if has_fix else [],
    })


@router.get("/telemetry")
def get_telemetry():
    return JSONResponse(telemetry_data)


@router.get("/assets/leaflet/{asset_path:path}")
def leaflet_assets(asset_path: str):
    file_path = LEAFLET_DIR / asset_path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Leaflet asset not found")

    media_type, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(file_path, media_type=media_type)


@router.get("/mbtiles/{z}/{x}/{y}")
def mbtiles_tile(z: int, x: int, y: str):
    y_str = y.split(".", 1)[0] if "." in y else y
    try:
        y_int = int(y_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tile y value")

    result = _get_tile_from_mbtiles(z, x, y_int)
    if not result:
        raise HTTPException(status_code=404, detail="MBTiles tile not found")

    tile_bytes, mime = result
    return Response(content=tile_bytes, media_type=mime)


@router.get("/offline-status")
def offline_status():
    leaflet_ok = (LEAFLET_DIR / "leaflet.js").exists() and (LEAFLET_DIR / "leaflet.css").exists()
    mbtiles_ok = _mbtiles_exists()
    bounds = _parse_mbtiles_bounds()
    minzoom, maxzoom = _get_mbtiles_minmax_zoom()

    return JSONResponse({
        "leaflet_local_available": leaflet_ok,
        "mbtiles_available": mbtiles_ok,
        "mbtiles_path": str(MBTILES_PATH),
        "leaflet_dir": str(LEAFLET_DIR),
        "mbtiles_bounds": bounds,
        "mbtiles_minzoom": minzoom,
        "mbtiles_maxzoom": maxzoom,
    })