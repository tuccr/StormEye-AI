# frontend/views/main_window.py
import asyncio
from PyQt6 import QtWidgets
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QSizePolicy

from ui.main_ui import Ui_MainWindow
from services.webrtc_client import WebRTCClient


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.ui.videoLabel.setMinimumSize(640, 480)
        self.ui.videoLabel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.ui.videoLabel.setScaledContents(False)

        # --- Add a webview for the map (hidden by default) ---
        self.webView = QWebEngineView(self)
        self.webView.setVisible(False)
        self.ui.videoReportLayout.insertWidget(0, self.webView, 2)
        self.webView.load(QUrl("http://127.0.0.1:8000/map"))

        # AI toggle state (UI default is checked)
        self.ai_enabled = bool(self.ui.btnAIToggle.isChecked())

        self.webrtc_client = WebRTCClient(
            self.ui.videoLabel,
            ai_enabled=self.ai_enabled,
            overlay_enabled=self.ai_enabled,
        )

        # handlers
        self.ui.btnLiveFeed.clicked.connect(self.on_connect_clicked)
        self.ui.btn3DMap.clicked.connect(self.on_map_view_clicked)
        self.ui.btnAIToggle.clicked.connect(self.on_ai_toggle_clicked)

    def on_ai_toggle_clicked(self):
        """Toggle AI inference + overlay without restarting WebRTC."""
        self.ai_enabled = bool(self.ui.btnAIToggle.isChecked())
        self.ui.btnAIToggle.setText("AI: ON" if self.ai_enabled else "AI: OFF")
        self.ui.btnAIToggle.setStyleSheet("" if self.ai_enabled else "background-color: #444; color: white;")

        self.webrtc_client.set_ai_enabled(self.ai_enabled)
        self.webrtc_client.set_overlay_enabled(self.ai_enabled)

        # Live control message -> backend flips inference on/off instantly
        self.webrtc_client.send_control(ai=self.ai_enabled, overlay=self.ai_enabled)

    def on_connect_clicked(self):
        asyncio.create_task(self._connect_webrtc())

    async def _connect_webrtc(self):
        self.ui.btnLiveFeed.setEnabled(False)
        self.ui.btn3DMap.setEnabled(True)

        self.webView.setVisible(False)
        self.ui.videoLabel.setVisible(True)

        await self.webrtc_client.close_connection()
        await self.webrtc_client.start_connection()

    def on_map_view_clicked(self):
        asyncio.create_task(self._switch_to_map())

    async def _switch_to_map(self):
        self.ui.btn3DMap.setEnabled(False)
        self.ui.btnLiveFeed.setEnabled(True)

        self.ui.videoLabel.clear()
        self.ui.videoLabel.setVisible(False)
        self.webView.setVisible(True)

        await self.webrtc_client.close_connection()

        self.webrtc_client = WebRTCClient(
            self.ui.videoLabel,
            ai_enabled=self.ai_enabled,
            overlay_enabled=self.ai_enabled,
        )

    def closeEvent(self, event):
        """Ensure WebRTC is closed cleanly to avoid pending-task warnings."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.webrtc_client.close_connection())
        except RuntimeError:
            try:
                asyncio.run(self.webrtc_client.close_connection())
            except Exception:
                pass
        event.accept()
