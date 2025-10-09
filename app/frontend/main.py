import sys
import asyncio
from PyQt6 import QtWidgets
from qasync import QEventLoop
from views.main_window import MainWindow

def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    with loop:
        loop.run_forever()

if __name__ == "__main__":
    main()

