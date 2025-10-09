import asyncio
from PyQt6 import QtWidgets
from ui.main_ui import Ui_MainWindow
from services.webrtc_client import WebRTCClient

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.webrtc_client = WebRTCClient(self.ui.videoLabel)
        self.ui.btnLiveFeed.clicked.connect(self.on_connect_clicked)

    def on_connect_clicked(self):
        self.ui.btnLiveFeed.setEnabled(False)
        asyncio.create_task(self.webrtc_client.start_connection())

