import asyncio
import aiohttp
import cv2
from aiortc import RTCPeerConnection, RTCSessionDescription

from PyQt6 import QtGui, QtCore

class WebRTCClient:
    def __init__(self, video_label):
        self.video_label = video_label
        self.pc = RTCPeerConnection()

    async def start_connection(self):
        self.pc.addTransceiver("video", direction="recvonly")

        @self.pc.on("track")
        async def on_track(track):
            while True:
                frame = await track.recv()
                await asyncio.sleep(0.03)
                self._update_video_label(frame)

        async with aiohttp.ClientSession() as session:
            offer = await self.pc.createOffer()
            await self.pc.setLocalDescription(offer)

            async with session.post("http://127.0.0.1:8000/webrtc/offer", json={
                "sdp": self.pc.localDescription.sdp,
                "type": self.pc.localDescription.type
            }) as resp:
                if resp.status != 200:
                    return
                answer = await resp.json(content_type=None)

            await self.pc.setRemoteDescription(
                RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
            )

        print("WebRTC connection established.")

    def _update_video_label(self, frame):
        img = frame.to_ndarray(format="bgr24")
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w, ch = img.shape
        bytes_per_line = ch * w
        qt_image = QtGui.QImage(img.data, w, h, bytes_per_line, QtGui.QImage.Format.Format_RGB888)
        pixmap = QtGui.QPixmap.fromImage(qt_image)
        scaled_pixmap = pixmap.scaled(
            640,
            480,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation
        )
        self.video_label.setPixmap(scaled_pixmap)

