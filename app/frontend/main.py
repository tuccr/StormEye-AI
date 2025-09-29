import sys
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QTextEdit
from api_client import send_message

class MyApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt6 + FastAPI Demo")
        self.setMinimumSize(400, 300)

        # Layout
        self.layout = QVBoxLayout()

        # Text editor
        self.text = QTextEdit(self)
        self.layout.addWidget(self.text)

        # Button
        self.button = QPushButton("Send to FastAPI", self)
        self.button.clicked.connect(self.call_backend)
        self.layout.addWidget(self.button)

        self.setLayout(self.layout)

    def call_backend(self):
        user_text = self.text.toPlainText()
        response = send_message(user_text)
        self.text.setText(f"Response: {response}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MyApp()
    win.show()
    sys.exit(app.exec())

