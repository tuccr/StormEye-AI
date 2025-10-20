
import asyncio
import aiohttp
import cv2
from aiortc import RTCPeerConnection, RTCSessionDescription
from PyQt6 import QtGui, QtCore

class WebRTCClient:
    def __init__(self, video_label):
        self.video_label = video_label
        self.pc = None
        self.track_task = None

    async def start_connection(self):
        # Close previous connection if exists
        if self.pc:
            await self.close_connection()

        self.pc = RTCPeerConnection()
        self.pc.addTransceiver("video", direction="recvonly")

        @self.pc.on("track")
        async def on_track(track):
            try:
                while True:
                    frame = await track.recv()
                    await asyncio.sleep(0.03)
                    self._update_video_label(frame)
            except Exception as e:
                print(f"Track stopped: {e}")

        # Create offer and set as local description
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        # Send offer to server and get answer
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://127.0.0.1:8000/webrtc/offer",
                json={
                    "sdp": self.pc.localDescription.sdp,
                    "type": self.pc.localDescription.type
                }
            ) as resp:
                if resp.status != 200:
                    print("Failed to get answer from server")
                    return
                answer = await resp.json(content_type=None)

        # Set remote description
        await self.pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
        )

        print("WebRTC connection established.")

    async def close_connection(self):
        if self.pc:
            # Cancel any running tasks associated with tracks
            if self.track_task:
                self.track_task.cancel()
                self.track_task = None
            await self.pc.close()
            self.pc = None
            self.video_label.clear()
            print("WebRTC connection closed.")

    def _update_video_label(self, frame):
        img = frame.to_ndarray(format="bgr24")
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w, ch = img.shape
        bytes_per_line = ch * w
        qt_image = QtGui.QImage(
            img.data, w, h, bytes_per_line, QtGui.QImage.Format.Format_RGB888
        )
        pixmap = QtGui.QPixmap.fromImage(qt_image)
        scaled_pixmap = pixmap.scaled(
            640,
            480,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation
        )
        self.video_label.setPixmap(scaled_pixmap)

