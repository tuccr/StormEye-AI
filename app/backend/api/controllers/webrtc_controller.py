from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaBlackhole
from fastapi.responses import JSONResponse
from ..models.webrtc_models import Offer
from ...services.video_service import VideoCameraTrack, InferenceVideoTrack, PiStreamTrack
from ...config.settings import DEFAULT_VIDEO_PATH
from aiortc import RTCRtpSender
from aiortc.rtcrtpparameters import RTCRtpCodecCapability
import json

async def handle_offer(request: Offer):
    try:
        pc = RTCPeerConnection()

        data_channel_holder = [None]

        #lucas changes
        @pc.on("datachannel")
        def on_datachannel(channel):
            data_channel_holder[0] = channel

        def send_data(data):
            channel = data_channel_holder[0]
            if channel and channel.readyState == "open":
                channel.send(json.dumps(data))        
        #end

        mode = "inference"
        thresh = 0.25
        if mode == "inference":
            video_track = InferenceVideoTrack(
                thresh=thresh,
                send_data_func=send_data #lucas change
            )
        else:
            #video_track = VideoCameraTrack(video_path=DEFAULT_VIDEO_PATH)
            video_track = PiStreamTrack()

        pc.addTrack(video_track)

        media_blackhole = MediaBlackhole()

        @pc.on("track")
        async def on_track(track):
            await media_blackhole.start()

        offer = RTCSessionDescription(sdp=request.sdp, type=request.type)
        await pc.setRemoteDescription(offer)

        h264_baseline = RTCRtpCodecCapability(
            mimeType="video/H264",
            clockRate=90000,
            parameters={
                "profile-level-id": "42e01f",  # Baseline
                "packetization-mode": "1",
                "level-asymmetry-allowed": "1",
            },
        )

        for transceiver in pc.getTransceivers():
            if transceiver.kind == "video":
                transceiver.setCodecPreferences([h264_baseline])
        
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

