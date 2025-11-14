import asyncio
import json
import logging
import os
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer


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


### ---- WebRTC Handlers ---- ###
async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    pc = RTCPeerConnection()
    pcs.add(pc)
    logging.info(f"Created peer connection: {pc}")

    player = MediaPlayer("/dev/video0", format="v4l2", options={
        "video_size": "1280x720",
        "framerate": "30"
    })
    pc.addTrack(player.video)

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps({
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        })
    )

async def on_shutdown(app):
    """
    Clean up connections on shutdown.
    """
    await asyncio.gather(*(pc.close() for pc in pcs))
    pcs.clear()


### ------- Web Server ------- ###

async def index(request):
    return web.FileResponse(path=os.path.join("static", "index.html"))

async def javascript(request):
    return web.FileResponse(path=os.path.join("static", "client.js"))

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
