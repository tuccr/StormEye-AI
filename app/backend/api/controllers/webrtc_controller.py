import asyncio
import json
from typing import Any, Dict, Set

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaBlackhole
from aiortc.rtcrtpparameters import RTCRtpCodecCapability
from fastapi.responses import JSONResponse

from ..models.webrtc_models import Offer
from ...services.video_service import InferenceVideoTrack
from ..routes.pistream_routes import is_flight_enabled  # <-- import from pistream_routes to avoid cycles

# Track active peer connections so we can close them when flight ends
_ACTIVE_PCS: Set[RTCPeerConnection] = set()
_ACTIVE_LOCK = asyncio.Lock()


async def close_all_peers():
    async with _ACTIVE_LOCK:
        pcs = list(_ACTIVE_PCS)
        _ACTIVE_PCS.clear()

    for pc in pcs:
        try:
            await pc.close()
        except Exception:
            pass


async def handle_offer(request: Offer, mode: str = "stream", thresh: float = 0.25):
    """
    IMPORTANT DESIGN:
    - We always attach an InferenceVideoTrack so we can toggle AI inference ON/OFF
      live via DataChannel messages without restarting WebRTC.

    mode:
      - "stream"    -> start with AI disabled (passthrough)
      - "inference" -> start with AI enabled
    """
    try:
        if not is_flight_enabled():
            return JSONResponse({"error": "Backend disabled (flight ended)."}, status_code=503)

        pc = RTCPeerConnection()

        async with _ACTIVE_LOCK:
            _ACTIVE_PCS.add(pc)

        @pc.on("connectionstatechange")
        async def on_conn_state():
            if pc.connectionState in ("failed", "closed", "disconnected"):
                async with _ACTIVE_LOCK:
                    _ACTIVE_PCS.discard(pc)

        # Keep a reference to the server-side datachannel when it arrives
        data_channel_holder: Dict[str, Any] = {"ch": None}

        def send_data(data):
            ch = data_channel_holder["ch"]
            if ch and ch.readyState == "open":
                ch.send(json.dumps(data))

        start_ai = (mode == "inference")
        video_track = InferenceVideoTrack(
            thresh=thresh,
            send_data_func=send_data,
            ai_enabled=start_ai,
            overlay_enabled=start_ai,
        )
        pc.addTrack(video_track)

        @pc.on("datachannel")
        def on_datachannel(channel):
            data_channel_holder["ch"] = channel

            @channel.on("message")
            def on_message(message):
                """
                Client control messages. Expected JSON (any subset ok):
                  {"ai": true/false, "overlay": true/false}
                """
                try:
                    payload = json.loads(message)
                    if not isinstance(payload, dict):
                        return
                except Exception:
                    return

                # If flight ended mid-session, ignore controls
                if not is_flight_enabled():
                    return

                if "ai" in payload:
                    video_track.set_ai_enabled(bool(payload["ai"]))
                    if not bool(payload["ai"]):
                        video_track.set_overlay_enabled(False)

                if "overlay" in payload:
                    video_track.set_overlay_enabled(bool(payload["overlay"]))

                if "thresh" in payload:
                    try:
                        video_track.thresh = float(payload["thresh"])
                    except Exception:
                        pass

        media_blackhole = MediaBlackhole()

        @pc.on("track")
        async def on_track(track):
            await media_blackhole.start()

        offer = RTCSessionDescription(sdp=request.sdp, type=request.type)
        await pc.setRemoteDescription(offer)

        # Prefer baseline H264 for broad compatibility
        h264_baseline = RTCRtpCodecCapability(
            mimeType="video/H264",
            clockRate=90000,
            parameters={
                "profile-level-id": "42e01f",
                "packetization-mode": "1",
                "level-asymmetry-allowed": "1",
            },
        )

        for transceiver in pc.getTransceivers():
            if transceiver.kind == "video":
                transceiver.setCodecPreferences([h264_baseline])

        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return JSONResponse({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)