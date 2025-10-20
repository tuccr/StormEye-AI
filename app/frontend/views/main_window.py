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
        # put webView in the same slot as the video (left side)
        # index 0 is the left widget in your HBox; insert at 0 with same stretch=2
        self.ui.videoReportLayout.insertWidget(0, self.webView, 2)

        # WebRTC client draws into ui.videoLabel
        self.webrtc_client = WebRTCClient(self.ui.videoLabel)
        #FastAPI loads Leaflet map
        self.webView.load(QUrl("http://127.0.0.1:8000/map"))
        # ---------- handlers ---------------
        self.ui.btnLiveFeed.clicked.connect(self.on_connect_clicked)
        self.ui.btn3DMap.clicked.connect(self.on_map_view_clicked)

    def on_connect_clicked(self):
        # toggle buttons
        self.ui.btnLiveFeed.setEnabled(False)
        self.ui.btn3DMap.setEnabled(True)

        # show video, hide map
        self.webView.setVisible(False)
        self.ui.videoLabel.setVisible(True)

        asyncio.create_task(self.webrtc_client.start_connection())

    def on_map_view_clicked(self):
        self.ui.btn3DMap.setEnabled(False)
        self.ui.btnLiveFeed.setEnabled(True)

        # hide video, show map
        self.ui.videoLabel.clear()
        self.ui.videoLabel.setVisible(False)
        self.webView.setVisible(True)

