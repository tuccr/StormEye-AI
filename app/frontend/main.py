import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QTextEdit
from PyQt6 import uic
from api_client import retrieve_video_feed
from main_ui import Ui_MainWindow

class MyApp(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        # Layout
        '''self.layout = QVBoxLayout()

        # Text editor
        self.text = QTextEdit(self)
        self.layout.addWidget(self.text)

        # Button
        self.button = QPushButton("Send to FastAPI", self)
        self.button.clicked.connect(self.call_backend)
        self.layout.addWidget(self.button)

        self.setLayout(self.layout)'''
        
        self.btnLiveFeed.clicked.connect(self.retrieve_video_feed)

    def retrieve_video_feed(self):
        user_text = "video accessed"
        response = retrieve_video_feed(user_text)
        print(response)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MyApp()
    win.show()
    sys.exit(app.exec())

