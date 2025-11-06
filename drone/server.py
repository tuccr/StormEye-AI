import asyncio
import json
import logging
import os
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
import cv2
import av

"""
DO NOT MOVE OR RENAME THIS FILE. This file should be named "server.py" and should be at /home/test/vid2_server/server.py

Viewer runs on port 8080, so open web browser and go to http://<IP>:8080 to see stream. <IP> should be one of the following (NOTE: this will eventually be deprecated once laptop can directly receive frames):
	- raspberrypi
	- raspberrypi.local
	- 0.0.0.0 (if running locally on raspberry pi)

If you want to make changes or experiment with the server.py, run "sudo systemctl stop WebRTCStream.service" then run your new script with "python <NAME>.py"

If you must move or rename this file, update /etc/systemd/system/WebRTCStream.service to match the new location.

Run "sudo systemctl restart WebRTCStream.service" after you make any changes to this file to see results.

Camera will not turn on unless the /offer request is called, and will only support one video stream at a time (only one recipient at a time).

This python script is linked with WebRTCStream.service, so that service will run this python script with the python virtual environment in .venv, do one of the following if WebRTCStream.service is not running:
	- source .venv/bin/activate & python server.py
	- sudo systemctl start WebRTCStream.service
	- /home/test/vid2_server/.venv/bin/python /home/test/vid2_server/server.py
"""

logging.basicConfig(level=logging.INFO)
pcs = set()

# ---- Video Capture Track ----
class CameraVideoTrack(VideoStreamTrack):
    """
    A video stream track that captures frames from the Raspberry Pi camera.
    
    TODO: Allegedly, we can take in frames like this (ChatGPT):
    ```
    from aiortc.contrib.media import MediaPlayer

	player = MediaPlayer("/dev/video0", format="v4l2", options={
		"input_format": "h264"
	})
	pc.addTrack(player.video)
	```
	, instead of using open-cv python and processing raw frames.
    """
    
    def __init__(self):
        super().__init__()
        self.cap = cv2.VideoCapture(0)  # Use Pi Camera or USB cam
        if not self.cap.isOpened():
            raise RuntimeError("Could not open video device")
            
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)  # Set width
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)  # Set height
        self.cap.set(cv2.CAP_PROP_FPS, 60)             # Set framerate
	
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
    """
    Clean up connections on shutdown.
    
    TODO: Make sure that this will close video stream when you close the web browser, backend, or whatever you're using to receive the stream. May require changes to client.js and MAY require usage of FastAPI.
    """
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()

"""
------- Web Server -------
TODO: Get rid of need for web server and get ground station backend to directly receive frames from WebRTCStream on Pi. 

ChatGPT Notes:
⚠️ Things to Keep in Mind

You can’t guarantee the unload event always runs (e.g., sudden power loss, browser crash).

Avoid heavy logic during unload — use sendBeacon for quick reporting or cleanup.

Browser restrictions mean you can’t block users from leaving (only warn them, sometimes).
"""

async def index(request):
    with open(os.path.join("static", "index.html")) as f:
        return web.Response(content_type="text/html", text=f.read())

async def javascript(request):
    with open(os.path.join("static", "client.js")) as f:
        return web.Response(content_type="application/javascript", text=f.read())

"""
------- Application Initialization -------
"""
app = web.Application() 
app.on_shutdown.append(on_shutdown)
app.router.add_get("/", index)
app.router.add_get("/client.js", javascript)
app.router.add_post("/offer", offer)

if __name__ == "__main__":
    web.run_app(app, port=8080, host="0.0.0.0")
