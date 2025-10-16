from fastapi import APIRouter
from ..controllers.webrtc_controller import handle_offer
from ..models.webrtc_models import Offer

router = APIRouter(prefix="/webrtc", tags=["WebRTC"])

@router.post("/offer")
async def offer(request: Offer):
    return await handle_offer(request)
