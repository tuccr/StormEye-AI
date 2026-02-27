from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from ..controllers.webrtc_controller import handle_offer
from ..models.webrtc_models import Offer
from .pistream_routes import is_flight_enabled, is_pi_stream_alive

router = APIRouter(prefix="/webrtc", tags=["WebRTC"])


@router.post("/offer")
async def offer(request: Offer):
    if not is_flight_enabled():
        return JSONResponse({"error": "Backend disabled (flight ended)."}, status_code=503)

    # ✅ NEW: Only allow WebRTC to client when Pi is actually streaming
    if not is_pi_stream_alive():
        return JSONResponse({"error": "Pi stream not available."}, status_code=503)

    return await handle_offer(request)


@router.post("/offer/inference")
async def offer_inference(request: Offer, thresh: float = Query(0.25)):
    if not is_flight_enabled():
        return JSONResponse({"error": "Backend disabled (flight ended)."}, status_code=503)

    # ✅ NEW: Only allow WebRTC to client when Pi is actually streaming
    if not is_pi_stream_alive():
        return JSONResponse({"error": "Pi stream not available."}, status_code=503)

    return await handle_offer(request, mode="inference", thresh=thresh)