from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaBlackhole
from fastapi.responses import JSONResponse
from ..models.webrtc_models import Offer
from ...services.video_service import VideoCameraTrack, InferenceVideoTrack
from ...config.settings import DEFAULT_VIDEO_PATH

async def handle_offer(request: Offer):
    try:
        pc = RTCPeerConnection()

        mode = "inference"
        thresh = 0.25
        if mode == "inference":
            video_track = InferenceVideoTrack(video_path=DEFAULT_VIDEO_PATH, thresh=thresh)
        else:
            video_track = VideoCameraTrack(video_path=DEFAULT_VIDEO_PATH)

        pc.addTrack(video_track)

        media_blackhole = MediaBlackhole()

        @pc.on("track")
        async def on_track(track):
            await media_blackhole.start()

        offer = RTCSessionDescription(sdp=request.sdp, type=request.type)
        await pc.setRemoteDescription(offer)

        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return JSONResponse({
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

