import asyncio
import json
import logging
import os
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
import cv2
import av

logging.basicConfig(level=logging.INFO)
pcs = set()

# ---- Video Capture Track ----
class CameraVideoTrack(VideoStreamTrack):
    """A video stream track that captures frames from the Raspberry Pi camera."""
    def __init__(self):
        super().__init__()
        self.cap = cv2.VideoCapture(0)  # Use Pi Camera or USB cam
        if not self.cap.isOpened():
            raise RuntimeError("Could not open video device")

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        ret, frame = self.cap.read()
        if not ret:
            raise Exception("Failed to read frame from camera")


        # Convert to RGB (WebRTC uses this format)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_frame = av.VideoFrame.from_ndarray(frame, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame

# ---- WebRTC Handlers ----
async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    pc = RTCPeerConnection()
    pcs.add(pc)

    # Log new connection
    logging.info(f"Created peer connection: {pc}")

    # Add video track
    video_track = CameraVideoTrack()
    pc.addTrack(video_track)

    # Set remote description and create answer
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        ),
    )

async def on_shutdown(app):
    # Clean up connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()

# ---- Web Server ----
async def index(request):
    with open(os.path.join("static", "index.html")) as f:
        return web.Response(content_type="text/html", text=f.read())

async def javascript(request):
    with open(os.path.join("static", "client.js")) as f:
        return web.Response(content_type="application/javascript", text=f.read())

app = web.Application()
app.on_shutdown.append(on_shutdown)
app.router.add_get("/", index)
app.router.add_get("/client.js", javascript)
app.router.add_post("/offer", offer)

if __name__ == "__main__":
    web.run_app(app, port=8080, host="0.0.0.0")
