import asyncio
import httpx
import cv2
import numpy as np
import time


import asyncio
import httpx
import cv2
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaStreamTrack
from av import VideoFrame

PI_OFFER_URL = "http://raspberrypi.local:8080/offer"
frame_queue = asyncio.Queue(maxsize=1)

from av import VideoFrame
import numpy as np

async def push_frames_to_queue(track):
    """
    Receives frames from a remote video track and puts them into frame_queue.
    """
    while True:
        try:
            frame: VideoFrame = await track.recv()  # async receive
            img = frame.to_ndarray(format="bgr24")  # convert to OpenCV format

            # Keep only latest frame in the queue
            if frame_queue.full():
                try:
                    frame_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

            await frame_queue.put(img)
        except Exception as e:
            print(f"❌ Track error: {e}")
            break

async def connect_webrtc():
    while True:
        try:
            pc = RTCPeerConnection()
            
            pc.addTransceiver("video", direction="recvonly")

            # Handle incoming tracks
            @pc.on("track")
            def on_track(track):
                print(f"🎥 Received track: {track.kind}")
                if track.kind == "video":
                    # Start async task to push frames into frame_queue
                    asyncio.create_task(push_frames_to_queue(track))

            # 1️⃣ Create local OFFER
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)

            # 2️⃣ Send OFFER to Pi
            async with httpx.AsyncClient(timeout=20) as client:
                print("📨 Sending OFFER to Pi...")
                response = await client.post(
                    PI_OFFER_URL,
                    json={"sdp": offer.sdp, "type": offer.type},
                )

            if response.status_code != 200:
                print(f"❌ Pi returned {response.status_code}: {response.text}")
                await asyncio.sleep(5)
                continue

            # 3️⃣ Receive ANSWER from Pi
            answer_json = response.json()
            answer = RTCSessionDescription(answer_json["sdp"], answer_json["type"])
            await pc.setRemoteDescription(answer)

            print("✅ WebRTC connection established! Streaming video...")

            # Keep running indefinitely
            await asyncio.Future()

        except Exception as e:
            print(f"❌ WebRTC error: {e}")
            await asyncio.sleep(5)
