# frontend/services/webrtc_client.py
# Drop-in optimized version:
# - GUI-thread painting via Qt signal (prevents QPaintDevice errors)
# - "Latest-frame-only" rendering (drops frames instead of queueing -> lower latency)
# - No artificial sleep in recv loop
# - FastTransformation scaling (much faster on weaker laptops)
# - Cached canvas pixmap (reduces allocations)
# - Smoothed bounding boxes with decay (no jitter, no ghosts)

import asyncio
import json

import aiohttp
import cv2
from aiortc import RTCPeerConnection, RTCSessionDescription
from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QColor, QFont, QPen


class WebRTCClient(QtCore.QObject):
    _render_tick = QtCore.pyqtSignal()
    _clear_requested = QtCore.pyqtSignal()

    def __init__(self, video_label):
        super().__init__()
        self.video_label = video_label

        # ---- Box smoothing & lifecycle ----
        self._smoothed_boxes = {}     # id -> {"box": [x1,y1,x2,y2], "age": int}
        self._smooth_alpha = 0.6
        self._max_box_age = 5

        # WebRTC state
        self.pc = None
        self.box_data = []

        self._conn_lock = asyncio.Lock()
        self._closing = False

        # ---- Low-latency rendering ----
        self._latest_frame = None
        self._render_pending = False

        # ---- Cached drawing resources ----
        self._canvas = None
        self._canvas_size = (0, 0)

        # ---- Optional draw throttles ----
        self.draw_text = True
        self.text_every_n_frames = 2
        self._frame_counter = 0

        self._render_tick.connect(
            self._on_render_tick,
            QtCore.Qt.ConnectionType.QueuedConnection
        )
        self._clear_requested.connect(
            self._clear_video,
            QtCore.Qt.ConnectionType.QueuedConnection
        )

    # ------------------------------------------------------------------
    # WebRTC lifecycle
    # ------------------------------------------------------------------

    async def start_connection(self):
        async with self._conn_lock:
            self._closing = False

            if self.pc:
                await self.close_connection()

            pc = RTCPeerConnection()
            self.pc = pc
            pc.addTransceiver("video", direction="recvonly")

            @pc.on("track")
            async def on_track(track):
                try:
                    while True:
                        frame = await track.recv()
                        if self._closing:
                            break

                        self._latest_frame = frame
                        if not self._render_pending:
                            self._render_pending = True
                            self._render_tick.emit()

                except Exception as e:
                    print(f"Track stopped: {e}")

            data_channel = pc.createDataChannel("data")

            @data_channel.on("message")
            def on_message(message):
                try:
                    self.box_data = json.loads(message)
                except json.JSONDecodeError:
                    self.box_data = []

            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "http://127.0.0.1:8000/webrtc/offer",
                    json={"sdp": pc.localDescription.sdp,
                          "type": pc.localDescription.type},
                ) as resp:
                    answer = await resp.json(content_type=None)

            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
            )

            print("WebRTC connection established.")

    async def close_connection(self):
        async with self._conn_lock:
            self._closing = True
            self._latest_frame = None
            self._render_pending = False

            if self.pc:
                await self.pc.close()
                self.pc = None

            self.box_data = []
            self._smoothed_boxes.clear()
            self._clear_requested.emit()

    # ------------------------------------------------------------------
    # GUI thread slots
    # ------------------------------------------------------------------

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
        if self.video_label:
            self.video_label.clear()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _update_video_label(self, frame):
        target_w = max(1, self.video_label.width())
        target_h = max(1, self.video_label.height())

        img = frame.to_ndarray(format="bgr24")
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        orig_h, orig_w, ch = img.shape

        qt_image = QtGui.QImage(
            img.data,
            orig_w,
            orig_h,
            ch * orig_w,
            QtGui.QImage.Format.Format_RGB888,
        )
        frame_pixmap = QtGui.QPixmap.fromImage(qt_image)

        scale = min(target_w / orig_w, target_h / orig_h)
        disp_w = int(orig_w * scale)
        disp_h = int(orig_h * scale)
        offset_x = (target_w - disp_w) // 2
        offset_y = (target_h - disp_h) // 2

        scaled_frame = frame_pixmap.scaled(
            disp_w,
            disp_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
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
                draw_text_now = (
                    self.draw_text
                    and (self._frame_counter % self.text_every_n_frames == 0)
                )
                if draw_text_now:
                    painter.setFont(QFont("Arial", 12))

                seen_ids = set()

                for data in self.box_data:
                    box = data.get("box")
                    if not box or len(box) != 4:
                        continue

                    labels = data.get("labels", [])
                    scores = data.get("scores", [])
                    box_id = labels[0] if labels else "obj"
                    seen_ids.add(box_id)

                    x1, y1, x2, y2 = map(float, box)
                    x1, x2 = min(x1, x2), max(x1, x2)
                    y1, y2 = min(y1, y2), max(y1, y2)
                    raw = [x1, y1, x2, y2]

                    entry = self._smoothed_boxes.get(box_id)
                    if entry:
                        prev = entry["box"]
                        a = self._smooth_alpha
                        smoothed = [
                            prev[i] * (1 - a) + raw[i] * a for i in range(4)
                        ]
                    else:
                        smoothed = raw

                    self._smoothed_boxes[box_id] = {"box": smoothed, "age": 0}

                    x1, y1, x2, y2 = smoothed
                    if max(x1, y1, x2, y2) <= 1.5:
                        x1 *= orig_w
                        x2 *= orig_w
                        y1 *= orig_h
                        y2 *= orig_h

                    sx1 = x1 * scale + offset_x
                    sy1 = y1 * scale + offset_y
                    sx2 = x2 * scale + offset_x
                    sy2 = y2 * scale + offset_y

                    painter.drawRect(
                        QtCore.QRectF(
                            sx1,
                            sy1,
                            sx2 - sx1,
                            sy2 - sy1,
                        )
                    )

                    if draw_text_now and labels and scores:
                        painter.drawText(
                            int(sx1),
                            int(max(12, sy1 - 6)),
                            f"{labels[0]}: {float(scores[0]):.2f}",
                        )

                # decay stale boxes
                for bid in list(self._smoothed_boxes.keys()):
                    if bid not in seen_ids:
                        self._smoothed_boxes[bid]["age"] += 1
                        if self._smoothed_boxes[bid]["age"] > self._max_box_age:
                            del self._smoothed_boxes[bid]

        finally:
            painter.end()

        self.video_label.setPixmap(final_pixmap)

