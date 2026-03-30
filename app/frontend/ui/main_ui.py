from PyQt6 import QtCore, QtGui, QtWidgets


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(3000, 1500)

        # Central widget
        self.centralwidget = QtWidgets.QWidget(MainWindow)
        MainWindow.setCentralWidget(self.centralwidget)

        # Main vertical layout
        self.mainLayout = QtWidgets.QVBoxLayout(self.centralwidget)
        self.mainLayout.setContentsMargins(10, 10, 10, 10)

        # ---- TOP ROW (sidebar + content) ----
        self.topLayout = QtWidgets.QHBoxLayout()

        # ===== Sidebar =====
        self.sidebar = QtWidgets.QFrame()
        self.sidebar.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.sidebar.setMinimumWidth(200)

        self.sidebarLayout = QtWidgets.QVBoxLayout(self.sidebar)
        self.sidebarLayout.setSpacing(12)

        # App Title
        self.appTitle = QtWidgets.QLabel("StormEye AI")
        font = QtGui.QFont()
        font.setPointSize(12)
        font.setBold(True)
        self.appTitle.setFont(font)
        self.appTitle.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self.sidebarLayout.addWidget(self.appTitle)

        # Navigation Buttons
        self.btnDashboard = QtWidgets.QPushButton("DASHBOARD")
        self.btnLiveFeed = QtWidgets.QPushButton("LIVE DRONE FEED")
        self.btn3DMap = QtWidgets.QPushButton("3D MAP VIEW")

        for btn in [self.btnDashboard, self.btnLiveFeed, self.btn3DMap]:
            btn.setMinimumHeight(30)
            self.sidebarLayout.addWidget(btn)

# ===== Telemetry Sidebar Box (The Pink Section) =====
        self.telemetryBox = QtWidgets.QGroupBox("Telemetry Data")
        # Optional: Styling to match your dark theme and green text
        self.telemetryBox.setStyleSheet("""
            QGroupBox {
                border: 1px solid #555555;
                border-radius: 5px;
                margin-top: 15px;
                color: #DDDDDD;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
            }
        """)
        
        self.telemetryBoxLayout = QtWidgets.QVBoxLayout(self.telemetryBox)
        self.telemetryBoxLayout.setSpacing(10)

        # Create the placeholders
        self.lblAlt = QtWidgets.QLabel("ALT: -- m")
        self.lblSpeed = QtWidgets.QLabel("SPD: -- m/s")
        self.lblHeading = QtWidgets.QLabel("HDG: -- °")
        self.lblLongitude = QtWidgets.QLabel("LON: --")
        self.lblLatitude = QtWidgets.QLabel("LAT: --")

        # Style the labels to pop (matching your existing overlay color)
        for lbl in [ self.lblAlt, self.lblSpeed, self.lblHeading, self.lblLongitude,self.lblLatitude]:
            lbl.setStyleSheet("color: #00FF00; font-weight: bold; font-size: 13px;")
            self.telemetryBoxLayout.addWidget(lbl)

        # Add the box to the sidebar
        self.sidebarLayout.addWidget(self.telemetryBox)

        # Spacer before control buttons (pushes the control buttons to the very bottom)
        self.sidebarLayout.addStretch(1)
        # Spacer before control buttons
        self.sidebarLayout.addStretch(1)

        # Control Buttons
        # ✅ Default OFF (MainWindow will also enforce OFF on boot)
        self.btnAIToggle = QtWidgets.QPushButton("Toggle AI: OFF")
        self.btnAIToggle.setCheckable(True)
        self.btnAIToggle.setChecked(False)

        # Renamed
        self.btnDataStream = QtWidgets.QPushButton("Start Flight")

        self.sidebarLayout.addWidget(self.btnAIToggle)
        self.sidebarLayout.addWidget(self.btnDataStream)

        self.topLayout.addWidget(self.sidebar)

        # ===== Content Area =====
        self.contentLayout = QtWidgets.QVBoxLayout()

        # Connection Status (top right)
        self.connectionStatus = QtWidgets.QLabel("● Connection Status")
        self.connectionStatus.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.contentLayout.addWidget(self.connectionStatus)

        # ===== Video Section (FULL AREA) =====
        self.videoLabel = QtWidgets.QLabel("Live Video Feed / 3D Map")
        self.videoLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.videoLabel.setFrameShape(QtWidgets.QFrame.Shape.Box)
        self.videoLabel.setStyleSheet("background-color: black; color: white;")

        self.videoLabel.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

        self.contentLayout.addWidget(self.videoLabel)

        self.topLayout.addLayout(self.contentLayout, 1)

        # Add top layout to main
        self.mainLayout.addLayout(self.topLayout)

        # ---- Telemetry Section (bottom) ----
        self.telemetryLayout = QtWidgets.QHBoxLayout()
        self.telemetryLayout.addWidget(QtWidgets.QLabel("Telemetry"))

        self.chkGPS = QtWidgets.QCheckBox("GPS Signal")
        self.telemetryLayout.addWidget(self.chkGPS)
        self.telemetryLayout.addStretch(1)

        self.mainLayout.addLayout(self.telemetryLayout)

        # Retranslate UI
        self.retranslateUi(MainWindow)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

    def retranslateUi(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(_translate("MainWindow", "StormEye AI"))