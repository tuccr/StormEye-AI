import asyncio
import aiohttp
import time

from PyQt6 import QtWidgets, QtCore
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWidgets import QSizePolicy

from ui.main_ui import Ui_MainWindow
from services.webrtc_client import WebRTCClient


class DebugWebPage(QWebEnginePage):
    """Block popups and print JS console logs to Python terminal."""

    def createWindow(self, _type):
        return None

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        # This will show you exactly why the map is white (CDN blocked, SSL, etc.)
        try:
            print(f"[MAP JS] {sourceID}:{lineNumber} - {message}")
        except Exception:
            pass


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.flight_active = False
        self.stream_connected = False
        self.ai_enabled = False

        self._showing_map = False

        self._webengine_warmed = False
        self._map_loaded = False
        self._map_failed = False
        self._map_url_base = "http://127.0.0.1:8000/map"

        self.ui.videoLabel.setMinimumSize(640, 480)
        self.ui.videoLabel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.ui.videoLabel.setScaledContents(False)

        self.webView = QWebEngineView(self)
        self.webView.setVisible(False)

        page = DebugWebPage(self.webView)
        self.webView.setPage(page)

        settings = self.webView.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, True)

        self.webView.loadFinished.connect(self._on_map_load_finished)

        self.ui.contentLayout.insertWidget(1, self.webView)
        self.ui.contentLayout.setStretch(0, 0)
        self.ui.contentLayout.setStretch(1, 1)
        self.ui.contentLayout.setStretch(2, 1)

        self.ui.btnAIToggle.setChecked(False)
        self.ui.btnAIToggle.setEnabled(False)

        self.webrtc_client = WebRTCClient(
            self.ui.videoLabel,
            ai_enabled=self.ai_enabled,
            overlay_enabled=self.ai_enabled,
        )
        if hasattr(self.webrtc_client, "connection_state_changed"):
            self.webrtc_client.connection_state_changed.connect(self._on_webrtc_state_changed)

        self._setup_connect_overlay()
        self._setup_telemetry_overlay()

        self.ui.btnLiveFeed.clicked.connect(self.on_live_feed_clicked)
        self.ui.btn3DMap.clicked.connect(self.on_map_view_clicked)
        self.ui.btnAIToggle.clicked.connect(self.on_ai_toggle_clicked)
        self.ui.btnDataStream.clicked.connect(self.on_flight_toggle_clicked)

        self._sync_flight_ui()
        self._set_connection_status("disconnected")

        self.telemetry_timer = QtCore.QTimer()
        self.telemetry_timer.timeout.connect(self._update_telemetry)
        self.telemetry_timer.start(500)

        QtCore.QTimer.singleShot(0, self._post_qt_startup)

    def _set_connection_status(self, state: str):
        if state == "connected":
            dot = "#3CB371"
            text = "Connected"
        elif state == "connecting":
            dot = "#F4C542"
            text = "Connecting..."
        elif state == "failed":
            dot = "#E74C3C"
            text = "Connection Failed"
        else:
            dot = "#E74C3C"
            text = "Not Connected"

        self.ui.connectionStatus.setText(
            f'<span style="color:{dot}; font-size:18px;">●</span> '
            f'<span style="font-size:14px;">{text}</span>'
        )
        self.ui.connectionStatus.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def _setup_connect_overlay(self):
        self._connectOverlay = QtWidgets.QFrame(self.ui.videoLabel)
        self._connectOverlay.setVisible(False)
        self._connectOverlay.setStyleSheet("QFrame { background-color: rgba(0,0,0,140); border: none; }")

        layout = QtWidgets.QVBoxLayout(self._connectOverlay)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addStretch(1)

        self._connectSpinner = QtWidgets.QProgressBar(self._connectOverlay)
        self._connectSpinner.setRange(0, 0)
        self._connectSpinner.setTextVisible(False)
        self._connectSpinner.setFixedWidth(260)
        layout.addWidget(self._connectSpinner, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._connectLabel = QtWidgets.QLabel("Connecting to Pi…", self._connectOverlay)
        self._connectLabel.setStyleSheet("color: white; font-size: 18px;")
        layout.addWidget(self._connectLabel, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch(2)

        self.ui.videoLabel.installEventFilter(self)
        
    def _setup_telemetry_overlay(self):
        self._telemetryLabel = QtWidgets.QLabel(self.ui.videoLabel)
        self._telemetryLabel.setStyleSheet("color: #00FF00; font-weight: bold; font-size: 14px; background-color: rgba(0, 0, 0, 100); padding: 4px; border-radius: 4px;")
        self._telemetryLabel.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._telemetryLabel.setVisible(False)

    def _update_telemetry(self):
        if self.flight_active:
            asyncio.create_task(self._fetch_telemetry())
        else:
            self._telemetryLabel.setVisible(False)

    async def _fetch_telemetry(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("http://127.0.0.1:8000/map/telemetry") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._render_telemetry(data)
        except Exception:
            pass

    def _render_telemetry(self, data):
        if not data.get("connected"):
            # Hide overlay
            self._telemetryLabel.setVisible(False)
            # Reset sidebar labels to placeholder state
            self.ui.lblAlt.setText("ALT: -- m")
            self.ui.lblSpeed.setText("SPD: -- m/s")
            self.ui.lblHeading.setText("HDG: -- °")
            self.ui.lblHeading.setText("LAT: --")
            self.ui.lblHeading.setText("LON: --")
            return

        # 1. Update Existing Video Overlay
        text = (f"BAT: {data.get('battery', 0)}%  |  ALT: {data.get('alt', 0):.1f}m  |  SPD: {data.get('speed', 0):.1f}m/s  |  HDG: {data.get('heading', 0)}° | LAT: {data.get('lat', 0.0):.6f}  | LON: {data.get('lon', 0.0):.6f}")
        self._telemetryLabel.setText(text)
        self._telemetryLabel.adjustSize()
        self._telemetryLabel.setVisible(True)

        # 2. Update New Sidebar Box
        self.ui.lblAlt.setText(f"ALT: {data.get('alt', 0):.1f} m")
        self.ui.lblSpeed.setText(f"SPD: {data.get('speed', 0):.1f} m/s")
        self.ui.lblHeading.setText(f"HDG: {data.get('heading', 0)}°")
        text = (f"ALT: {data.get('alt', 0):.1f}m  |  SPD: {data.get('speed', 0):.1f}m/s  |  HDG: {data.get('heading', 0)}°")
        self._telemetryLabel.setText(text)
        self._telemetryLabel.adjustSize()
        self._telemetryLabel.setVisible(True)

    def _show_connect_overlay(self, show: bool, text: str | None = None):
        try:
            self._connectOverlay.setGeometry(self.ui.videoLabel.rect())
        except Exception:
            pass
        if text is not None:
            self._connectLabel.setText(text)
        self._connectOverlay.setVisible(bool(show))

    def eventFilter(self, obj, event):
        if obj is self.ui.videoLabel and event.type() == QtCore.QEvent.Type.Resize:
            try:
                self._connectOverlay.setGeometry(self.ui.videoLabel.rect())
                self._telemetryLabel.move(10, 10)
            except Exception:
                pass
        return super().eventFilter(obj, event)

    def _on_map_load_finished(self, ok: bool):
        if ok:
            self._map_loaded = True
            self._map_failed = False
        else:
            self._map_loaded = False
            self._map_failed = True
            print("[MAP] loadFinished(ok=False) – map load failed (possibly 503/blocked resources).")

    def _reload_map(self):
        # ✅ cache-bust every reload to avoid “stuck white page”
        url = QUrl(f"{self._map_url_base}?ts={int(time.time() * 1000)}")
        self.webView.load(url)
        self._map_loaded = False

    def _on_webrtc_state_changed(self, state: str):
        self.stream_connected = (state == "connected")
        self._set_connection_status(state)

        if state == "connecting":
            if self.flight_active and self.ui.videoLabel.isVisible():
                self._show_connect_overlay(True, "Connecting to Pi…")
        else:
            self._show_connect_overlay(False)

        # When we become connected, refresh map (if we ever showed a failure/blank page)
        if state == "connected":
            if self._map_failed or (not self._map_loaded):
                self._reload_map()

        self._sync_flight_ui()

    def _post_qt_startup(self):
        self._warm_webengine_hidden()
        try:
            asyncio.get_running_loop()
            asyncio.create_task(self._ensure_backend_off())
        except RuntimeError:
            pass

    def _warm_webengine_hidden(self):
        if self._webengine_warmed:
            return

        def _mark_warmed(_ok: bool):
            self._webengine_warmed = True
            try:
                self.webView.loadFinished.disconnect(_mark_warmed)
            except Exception:
                pass

        self.webView.loadFinished.connect(_mark_warmed)
        self.webView.load(QUrl("about:blank"))

    async def _ensure_backend_off(self):
        try:
            async with aiohttp.ClientSession() as session:
                await session.post("http://127.0.0.1:8000/system/flight/end")
        except Exception:
            pass

    def _show_offline(self):
        self._showing_map = False
        self.webView.setVisible(False)
        self.ui.videoLabel.setVisible(True)
        self._show_connect_overlay(False)
        self.ui.videoLabel.clear()
        self.ui.videoLabel.setText("Offline")
        self.ui.videoLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ui.videoLabel.setStyleSheet("background-color: black; color: white; font-size: 32px;")

    def _show_video_view(self):
        self._showing_map = False
        self.webView.setVisible(False)
        self.ui.videoLabel.setVisible(True)
        self.ui.videoLabel.setStyleSheet("background-color: black; color: white;")

        if self.flight_active and self.stream_connected:
            self.ui.btnLiveFeed.setEnabled(False)
            self.ui.btn3DMap.setEnabled(True)

    def _show_map_view(self):
        self._showing_map = True
        self.ui.videoLabel.setVisible(False)
        self._show_connect_overlay(False)
        self.webView.setVisible(True)

        if self.flight_active and self.stream_connected:
            self.ui.btn3DMap.setEnabled(False)
            self.ui.btnLiveFeed.setEnabled(True)

    def _sync_flight_ui(self):
        self.ui.btnDataStream.setText("End Flight" if self.flight_active else "Start Flight")

        unlocked = bool(self.flight_active and self.stream_connected)
        self.ui.btnLiveFeed.setEnabled(unlocked)
        self.ui.btn3DMap.setEnabled(unlocked)
        self.ui.btnAIToggle.setEnabled(unlocked)

        if not self.flight_active:
            self.stream_connected = False
            self.ai_enabled = False
            self.ui.btnAIToggle.setChecked(False)
            self.ui.btnAIToggle.setText("Toggle AI: OFF")
            self.ui.btnAIToggle.setStyleSheet("background-color: #444; color: white;")

            self._set_connection_status("disconnected")
            self._show_offline()
        else:
            self.ui.videoLabel.setStyleSheet("background-color: black; color: white;")
            self.ui.btnAIToggle.setText("Toggle AI: ON" if self.ai_enabled else "Toggle AI: OFF")
            self.ui.btnAIToggle.setStyleSheet("" if self.ai_enabled else "background-color: #444; color: white;")
            self._show_video_view()

    def _close_map_but_keep_webengine_warm(self):
        try:
            self.webView.load(QUrl("about:blank"))
        except Exception:
            pass
        self._map_loaded = False
        self._map_failed = False

    def _show_connection_failed(self):
        self._show_connect_overlay(False)
        self._set_connection_status("failed")
        self.ui.videoLabel.setVisible(True)
        self.ui.videoLabel.clear()
        self.ui.videoLabel.setText("Connection failed")
        self.ui.videoLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ui.videoLabel.setStyleSheet("background-color: black; color: white; font-size: 28px;")

    def on_flight_toggle_clicked(self):
        asyncio.create_task(self._toggle_flight())

    async def _toggle_flight(self):
        if self.flight_active:
            try:
                await self.webrtc_client.close_connection()
            except Exception:
                pass

            try:
                async with aiohttp.ClientSession() as session:
                    await session.post("http://127.0.0.1:8000/system/flight/end")
            except Exception:
                pass

            self.flight_active = False
            self.stream_connected = False
            self._sync_flight_ui()
            self._close_map_but_keep_webengine_warm()
            return

        try:
            async with aiohttp.ClientSession() as session:
                await session.post("http://127.0.0.1:8000/system/flight/start")
        except Exception:
            self._show_connection_failed()
            return

        self.flight_active = True
        self.stream_connected = False
        self._sync_flight_ui()

        # Always attempt to load map UI (even if Pi isn’t ready, coords will 503 until alive)
        self._reload_map()

        self._set_connection_status("connecting")
        if self.ui.videoLabel.isVisible():
            self._show_connect_overlay(True, "Connecting to Pi…")

        try:
            await self.webrtc_client.close_connection()
        except Exception:
            pass

        TIMEOUT_S = 10.0

        try:
            await self.webrtc_client.start_connection(retry_window_s=12.0, retry_interval_s=0.75)
            ok = await self.webrtc_client.wait_connected(timeout_s=TIMEOUT_S)
            if not ok:
                raise TimeoutError("Timed out waiting for first video frame.")
        except Exception:
            try:
                await self.webrtc_client.close_connection()
            except Exception:
                pass

            try:
                async with aiohttp.ClientSession() as session:
                    await session.post("http://127.0.0.1:8000/system/flight/end")
            except Exception:
                pass

            self.flight_active = False
            self.stream_connected = False
            self._sync_flight_ui()
            self._show_connection_failed()
            return

        self._show_video_view()

    def on_ai_toggle_clicked(self):
        if (not self.flight_active) or (not self.stream_connected):
            return

        self.ai_enabled = bool(self.ui.btnAIToggle.isChecked())
        self.ui.btnAIToggle.setText("Toggle AI: ON" if self.ai_enabled else "Toggle AI: OFF")
        self.ui.btnAIToggle.setStyleSheet("" if self.ai_enabled else "background-color: #444; color: white;")

        self.webrtc_client.set_ai_enabled(self.ai_enabled)
        self.webrtc_client.set_overlay_enabled(self.ai_enabled)
        self.webrtc_client.send_control(ai=self.ai_enabled, overlay=self.ai_enabled)

    def on_live_feed_clicked(self):
        if (not self.flight_active) or (not self.stream_connected):
            return
        self._show_video_view()

    def on_map_view_clicked(self):
        if (not self.flight_active) or (not self.stream_connected):
            return

        # If it was blank/failed earlier, reload before showing
        if self._map_failed or (not self._map_loaded):
            self._reload_map()

        self._show_map_view()

    def closeEvent(self, event):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.webrtc_client.close_connection())
        except RuntimeError:
            try:
                asyncio.run(self.webrtc_client.close_connection())
            except Exception:
                pass
        event.accept()