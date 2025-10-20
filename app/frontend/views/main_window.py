# frontend/views/main_window.py
import asyncio
from PyQt6 import QtWidgets, QtCore
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView

from ui.main_ui import Ui_MainWindow
from services.webrtc_client import WebRTCClient

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        # --- Add a webview for the map (hidden by default) ---
        self.webView = QWebEngineView(self)
        self.webView.setVisible(False)
        self.ui.videoReportLayout.insertWidget(0, self.webView, 2)

        self.webrtc_client = WebRTCClient(self.ui.videoLabel)
        self.webView.load(QUrl("http://127.0.0.1:8000/map"))

        # ---------- handlers ---------------
        self.ui.btnLiveFeed.clicked.connect(self.on_connect_clicked)
        self.ui.btn3DMap.clicked.connect(self.on_map_view_clicked)

    def on_connect_clicked(self):
        # schedule the async function properly
        asyncio.create_task(self._connect_webrtc())

    async def _connect_webrtc(self):
        self.ui.btnLiveFeed.setEnabled(False)
        self.ui.btn3DMap.setEnabled(True)

        # show video, hide map
        self.webView.setVisible(False)
        self.ui.videoLabel.setVisible(True)

        # Close any previous connection before starting a new one
        await self.webrtc_client.close_connection()
        await self.webrtc_client.start_connection()

    def on_map_view_clicked(self):
        # schedule the async function properly
        asyncio.create_task(self._switch_to_map())

    async def _switch_to_map(self):
        # disable buttons
        self.ui.btn3DMap.setEnabled(False)
        self.ui.btnLiveFeed.setEnabled(True)

        # hide video, show map
        self.ui.videoLabel.clear()
        self.ui.videoLabel.setVisible(False)
        self.webView.setVisible(True)

        # Close existing WebRTC connection
        await self.webrtc_client.close_connection()

        # Reset the WebRTC client for next use
        self.webrtc_client = WebRTCClient(self.ui.videoLabel)

