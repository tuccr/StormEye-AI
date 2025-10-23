from fastapi import APIRouter, Query
from ..controllers.webrtc_controller import handle_offer
from ..models.webrtc_models import Offer

router = APIRouter(prefix="/webrtc", tags=["WebRTC"])

@router.post("/offer")
async def offer(request: Offer):
    return await handle_offer(request)


@router.post("/offer/inference")
async def offer_inference(request: Offer, thresh: float = Query(0.25)):
    return await handle_offer(request, mode="inference", thresh=thresh)
