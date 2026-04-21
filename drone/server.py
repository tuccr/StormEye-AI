import asyncio
import json
import logging
import os
import subprocess
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer, MediaRecorder, MediaRelay
from datetime import datetime

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

# Global player/relay — only one may be open at a time to avoid double-opening /dev/video4,
# which causes a segfault in libav when two threads read the same V4L2 device simultaneously.
_player = None
_relay = None
# Serializes offer handling so a new connection never opens the camera before the old one releases it.
_offer_lock = asyncio.Lock()


async def _release_player():
    """Stop the MediaPlayer worker thread cleanly before closing the device.

    The player runs a background thread that reads frames from the V4L2 container.
    Calling container.close() directly (the old approach) leaves that thread running
    against freed memory → segfault. The correct sequence is player.video.stop(),
    which signals thread_quit, joins the thread, then closes the container.
    The join is blocking so we run it in an executor to avoid stalling the event loop.
    """
    global _player, _relay
    if _player is not None:
        try:
            if _player.video is not None:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _player.video.stop)
            logging.info("Released camera device.")
        except Exception as e:
            logging.warning(f"Failed to release camera: {e}")
        _player = None
        _relay = None


# Currently unused due to performance constraints
async def minute_clip(track):
	rec_num = 0
	if not os.path.exists('recordings'):
		os.mkdir('recordings')
	while True:
		filename = f'recordings/{rec_num}.mp4'
		recorder = MediaRecorder(filename)
		recorder.addTrack(track)
		
		await recorder.start()
		logging.info(f"Started recording {filename}...")
		
		await asyncio.sleep(10)
		
		await recorder.stop()
		logging.info(f"Stopped recording {filename}...")
		
		rec_num = rec_num + 1

async def offer(request):
    global _player, _relay

    params = await request.json()
    offer_desc = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    async with _offer_lock:
        # Close any existing peer connections before opening a new camera handle.
        # Without this, a rapid refresh sends a new offer before the old connection's
        # connectionstatechange fires, causing two MediaPlayers to open /dev/video4
        # simultaneously → segfault inside libav.
        if pcs:
            logging.info("Closing existing peer connections before new offer...")
            await asyncio.gather(*(pc.close() for pc in list(pcs)), return_exceptions=True)
            pcs.clear()

        await _release_player()

        pc = RTCPeerConnection()
        pcs.add(pc)
        logging.info(f"Created peer connection: {pc}")

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logging.info(f"Connection state changed to: {pc.connectionState}")
            if pc.connectionState in ("failed", "closed", "disconnected"):
                logging.info("Client disconnected, closing peer connection.")
                pcs.discard(pc)
                await pc.close()
                await _release_player()

        try:
            """
            Using Intel RealSense D415 depth camera, /dev/video0 is a raw depth stream and not camera access.
            Use "sudo realsense-viewer" to view live view.
            /dev/video2 ->  RGB camera which picks up projected mesh from light on front of camera. 1280x720p30 or 848x480p90
            /dev/video4 ->  Normal RGB camera access, no projected mesh or depth data, 1920x1080p30 or 960x540p90. Pi 5 struggles to keep up with 1080p30.
            """

            _relay = MediaRelay()

            _player = MediaPlayer("/dev/video4", format="v4l2", options={
                "video_size": "1280x720",
                "framerate": "30",
               # "input_format": "yuyv422"
            })
            source = _player.video

            webrtc_track = _relay.subscribe(source)
            record_track = _relay.subscribe(source)

            pc.addTrack(webrtc_track)

            await pc.setRemoteDescription(offer_desc)
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)

            #asyncio.create_task(minute_clip(record_track))

        except Exception as e:
            logging.error("Error occured:", exc_info=True)
            return web.Response(
                content_type="application/json",
                text=json.dumps({
                    "error": str(e)
                })
            )

        return web.Response(
            content_type="application/json",
            text=json.dumps({
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type
            })
        )

"""
BUG: Currently doesn't close on closing webpage. (can't recall if on_shutdown runs when closing program or client closes webpage)
"""
async def on_shutdown(app):
    await asyncio.gather(*(pc.close() for pc in pcs))
    pcs.clear()
    await _release_player()

async def index(request):
    return web.FileResponse(path=os.path.join("static", "index.html"))

async def javascript(request):
    return web.FileResponse(path=os.path.join("static", "client.js"))

app = web.Application()
app.on_shutdown.append(on_shutdown)
app.router.add_get("/", index)
app.router.add_get("/client.js", javascript)
app.router.add_post("/offer", offer)

if __name__ == "__main__":
    web.run_app(app, port=8080, host="0.0.0.0")
