# frontend/services/webrtc_client.py

import asyncio
import json
import time

import aiohttp
import cv2
from aiortc import RTCPeerConnection, RTCSessionDescription
from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QColor, QFont, QPen


class WebRTCClient(QtCore.QObject):
    # "disconnected" | "connecting" | "connected" | "failed"
    connection_state_changed = QtCore.pyqtSignal(str)

    _render_tick = QtCore.pyqtSignal()
    _clear_requested = QtCore.pyqtSignal()

    def __init__(self, video_label, ai_enabled: bool = True, overlay_enabled: bool = True):
        super().__init__()
        self.video_label = video_label

        self._state = "disconnected"
        self._has_received_frame = False
        self._connected_event = asyncio.Event()
        self._connected_event.clear()

        self.ai_enabled = bool(ai_enabled)
        self.overlay_enabled = bool(overlay_enabled)

        self.pc = None
        self.box_data = []
        self._data_channel = None

        self._conn_lock = asyncio.Lock()
        self._closing = False

        self._latest_frame = None
        self._render_pending = False

        self._canvas = None
        self._canvas_size = (0, 0)

        self.draw_text = True
        self.text_every_n_frames = 2
        self._frame_counter = 0

        self._render_tick.connect(self._on_render_tick, QtCore.Qt.ConnectionType.QueuedConnection)
        self._clear_requested.connect(self._clear_video, QtCore.Qt.ConnectionType.QueuedConnection)

    def _set_state(self, new_state: str):
        if new_state != self._state:
            self._state = new_state
            try:
                self.connection_state_changed.emit(new_state)
            except Exception:
                pass

    async def start_connection(self, retry_window_s: float = 12.0, retry_interval_s: float = 0.75):
        """
        Connect to backend WebRTC. If backend returns 503 (Pi not ready),
        keep retrying for retry_window_s instead of failing immediately.
        """
        async with self._conn_lock:
            self._closing = False
            self._has_received_frame = False
            self._connected_event.clear()
            self._set_state("connecting")

            if self.pc:
                await self.close_connection()

            pc = RTCPeerConnection()
            self.pc = pc

            @pc.on("connectionstatechange")
            async def on_connectionstatechange():
                if self._closing:
                    return
                st = pc.connectionState
                if st == "failed":
                    self._connected_event.clear()
                    self._set_state("failed")
                elif st in ("closed", "disconnected"):
                    self._connected_event.clear()
                    self._set_state("disconnected")

            @pc.on("iceconnectionstatechange")
            async def on_iceconnectionstatechange():
                if self._closing:
                    return
                st = pc.iceConnectionState
                if st == "failed":
                    self._connected_event.clear()
                    self._set_state("failed")
                elif st in ("closed", "disconnected"):
                    self._connected_event.clear()
                    self._set_state("disconnected")

            pc.addTransceiver("video", direction="recvonly")

            @pc.on("track")
            async def on_track(track):
                try:
                    while True:
                        frame = await track.recv()
                        if self._closing:
                            break

                        if not self._has_received_frame:
                            self._has_received_frame = True
                            self._connected_event.set()
                            self._set_state("connected")

                        self._latest_frame = frame
                        if not self._render_pending:
                            self._render_pending = True
                            self._render_tick.emit()

                except Exception as e:
                    if not self._closing:
                        print(f"Track stopped: {e}")
                        self._connected_event.clear()
                        self._set_state("disconnected")

            data_channel = pc.createDataChannel("data")
            self._data_channel = data_channel

            @data_channel.on("open")
            def on_open():
                print("Data channel is open")
                self.send_control(ai=self.ai_enabled, overlay=self.overlay_enabled)

            @data_channel.on("message")
            def on_message(message):
                try:
                    if self.overlay_enabled:
                        self.box_data = json.loads(message)
                    else:
                        self.box_data = []
                except json.JSONDecodeError:
                    if not self._closing:
                        print("failed to receive JSON message")
                    self.box_data = []

            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)

            if self._closing or self.pc is not pc:
                return

            url = (
                "http://127.0.0.1:8000/webrtc/offer/inference"
                if self.ai_enabled
                else "http://127.0.0.1:8000/webrtc/offer"
            )

            deadline = time.monotonic() + float(retry_window_s)

            while True:
                if self._closing or self.pc is not pc:
                    return

                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            url,
                            json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
                        ) as resp:

                            # ✅ 503 means backend is up but Pi isn’t ready yet → retry
                            if resp.status == 503:
                                if time.monotonic() >= deadline:
                                    print("Backend still not ready (503) after retry window.")
                                    self._set_state("failed")
                                    return

                                # keep showing “connecting…”
                                await asyncio.sleep(retry_interval_s)
                                continue

                            if resp.status != 200:
                                print(f"Failed to get answer from server (HTTP {resp.status})")
                                self._set_state("failed")
                                return

                            answer = await resp.json(content_type=None)
                            if "sdp" not in answer or "type" not in answer:
                                print("Malformed answer from server.")
                                self._set_state("failed")
                                return

                except Exception as e:
                    # transient failures -> retry until deadline
                    if time.monotonic() >= deadline:
                        print(f"Offer retry window expired: {e}")
                        self._set_state("failed")
                        return
                    await asyncio.sleep(retry_interval_s)
                    continue

                # Got an answer — finish handshake
                if self._closing or self.pc is not pc:
                    return

                await pc.setRemoteDescription(
                    RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
                )
                print("WebRTC offer/answer complete. Waiting for first video frame...")
                return

    async def wait_connected(self, timeout_s: float = 10.0) -> bool:
        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout=timeout_s)
            return True
        except asyncio.TimeoutError:
            return False

    async def close_connection(self):
        async with self._conn_lock:
            self._closing = True
            self._has_received_frame = False
            self._connected_event.clear()
            self._latest_frame = None
            self._render_pending = False

            if self.pc:
                try:
                    await self.pc.close()
                    await asyncio.sleep(0)
                except Exception as e:
                    print(f"Error closing pc: {e}")
                self.pc = None

            self._data_channel = None
            self.box_data = []
            self._clear_requested.emit()
            self._set_state("disconnected")
            print("WebRTC connection closed.")

    def set_ai_enabled(self, enabled: bool):
        self.ai_enabled = bool(enabled)
        if not self.ai_enabled:
            self.overlay_enabled = False

    def set_overlay_enabled(self, enabled: bool):
        self.overlay_enabled = bool(enabled)
        if not self.overlay_enabled:
            self.box_data = []

    def send_control(self, **payload):
        try:
            if self._data_channel and self._data_channel.readyState == "open":
                self._data_channel.send(json.dumps(payload))
        except Exception:
            pass

    @QtCore.pyqtSlot()
    def _on_render_tick(self):
        if self._closing or self.video_label is None:
            self._render_pending = False
            return

        frame = self._latest_frame
        self._latest_frame = None
        if frame is None:
            self._render_pending = False
            return

        try:
            self._update_video_label(frame)
        except RuntimeError:
            self._render_pending = False
            return

        if self._latest_frame is not None and not self._closing:
            self._render_tick.emit()
        else:
            self._render_pending = False

    @QtCore.pyqtSlot()
    def _clear_video(self):
        if self.video_label is None:
            return
        try:
            self.video_label.clear()
        except RuntimeError:
            pass

    def _update_video_label(self, frame):
        target_w = max(1, self.video_label.width())
        target_h = max(1, self.video_label.height())

        img = frame.to_ndarray(format="bgr24")
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        orig_h, orig_w, ch = img.shape
        bytes_per_line = ch * orig_w

        qt_image = QtGui.QImage(
            img.data, orig_w, orig_h, bytes_per_line, QtGui.QImage.Format.Format_RGB888
        )
        frame_pixmap = QtGui.QPixmap.fromImage(qt_image)

        scale = min(target_w / orig_w, target_h / orig_h)
        disp_w = max(1, int(orig_w * scale))
        disp_h = max(1, int(orig_h * scale))
        offset_x = (target_w - disp_w) // 2
        offset_y = (target_h - disp_h) // 2

        scaled_frame = frame_pixmap.scaled(
            disp_w, disp_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation
        )

        if self._canvas is None or self._canvas_size != (target_w, target_h):
            self._canvas = QtGui.QPixmap(target_w, target_h)
            self._canvas_size = (target_w, target_h)

        final_pixmap = self._canvas
        final_pixmap.fill(QColor(0, 0, 0))

        painter = QPainter(final_pixmap)
        try:
            painter.drawPixmap(offset_x, offset_y, scaled_frame)

            if self.box_data:
                painter.setPen(QPen(QColor(255, 0, 0), 2))
                self._frame_counter += 1
                draw_text_now = self.draw_text and (self._frame_counter % self.text_every_n_frames == 0)
                if draw_text_now:
                    painter.setFont(QFont("Arial", 12))

                for data in self.box_data:
                    box = data.get("box")
                    if not box or len(box) != 4:
                        continue

                    labels = data.get("labels", [])
                    scores = data.get("scores", [])

                    x1, y1, x2, y2 = [float(c) for c in box]
                    if max(x1, y1, x2, y2) <= 1.5:
                        x1 *= orig_w; x2 *= orig_w; y1 *= orig_h; y2 *= orig_h

                    sx1 = int(x1 * scale) + offset_x
                    sy1 = int(y1 * scale) + offset_y
                    sx2 = int(x2 * scale) + offset_x
                    sy2 = int(y2 * scale) + offset_y

                    painter.drawRect(sx1, sy1, sx2 - sx1, sy2 - sy1)

                    if draw_text_now and labels and scores:
                        painter.drawText(sx1, max(0, sy1 - 10), f"{labels[0]}: {float(scores[0]):.2f}")
        finally:
            painter.end()

        self.video_label.setPixmap(final_pixmap)