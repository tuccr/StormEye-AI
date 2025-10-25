# frontend/views/main_window.py
import asyncio
from PyQt6 import QtWidgets, QtCore
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView

import asyncio
from PyQt6 import QtWidgets
from ui.main_ui import Ui_MainWindow
from services.webrtc_client import WebRTCClient

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.webView = QWebEngineView(self)
        self.webView.setVisible(False)
        self.ui.videoReportLayout.insertWidget(0, self.webView, 2)

        self.webrtc_client = WebRTCClient(self.ui.videoLabel)

        self.webView.load(QUrl("http://127.0.0.1:8000/map"))

        # connect signals ONCE
        self.ui.btnLiveFeed.clicked.connect(self.on_connect_clicked)
        self.ui.btn3DMap.clicked.connect(self.on_map_view_clicked)

    async def _reset_webrtc(self):
        if self.webrtc_client:
            await self.webrtc_client.close()

        self.webrtc_client = WebRTCClient(self.ui.videoLabel)

    def on_connect_clicked(self):

        self.ui.btnLiveFeed.setEnabled(False)
        self.ui.btn3DMap.setEnabled(True)
        self.webView.setVisible(False)
        self.ui.videoLabel.setVisible(True)

        asyncio.create_task(self._start_fresh_connection())

    async def _start_fresh_connection(self):
        await self._reset_webrtc()
        await self.webrtc_client.start_connection()

    def on_map_view_clicked(self):
        self.ui.btn3DMap.setEnabled(False)
        self.ui.btnLiveFeed.setEnabled(True)
        self.ui.videoLabel.clear()
        self.ui.videoLabel.setVisible(False)
        self.webView.setVisible(True)

        asyncio.create_task(self.webrtc_client.close())
