# StormEye-AI
A software which connects a drone to a laptop on the ground to assess storm damage using a state-of-the-art computer vision model.

# Jira Link
<https://stormeye-ai.atlassian.net/jira>

# Installation Instructions
There are two necessary setups for this codebase--the drone and ground station app.

## Application Setup

This repository contains two components: the Ground Station (backend + desktop frontend) and the Drone (on-board WebRTC server). Follow these steps to get a fresh machine and a Raspberry Pi running.

Prerequisites
- Python 3.10+ and pip
- System libraries (Debian/Ubuntu):
  sudo apt update && sudo apt install -y python3-venv python3-dev build-essential ffmpeg libavcodec-dev libavformat-dev libavdevice-dev libavfilter-dev libavutil-dev libswscale-dev libsrtp2-dev libopus-dev libvpx-dev pkg-config

Ground station (local laptop)
1. Create and activate a virtual environment from the repo root:
   python -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip

2. Install Python dependencies.
   - Install PyTorch appropriate for your machine following https://pytorch.org (CPU or CUDA). Example (CPU-only):
     pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

   - Install the remaining Python packages:
     pip install fastapi uvicorn[standard] httpx aiortc aiohttp av opencv-python pymavlink python-dotenv qasync PyQt6

3. Configure the backend environment:
   - Edit app/backend/.env and set DEFAULT_MODEL_PATH to the path containing the "sia" model package and weights (required). Example:
     DEFAULT_MODEL_PATH=~/Documents/SiA_OV-AR/
   - Set TELEMETRY_PORT to your MAVLink radio device (e.g. /dev/ttyUSB0).
   - Optionally set PI_OFFER_URL to your Pi's offer endpoint (http://<PI_IP>:8080/offer).

   Note: model code must expose a Python package named "sia" and include the weights in DEFAULT_MODEL_PATH/weights/... as expected by the code.

4. Start the backend API (from repo root, venv active):
   uvicorn app.backend.main:app --host 0.0.0.0 --port 8000 --reload

5. Start the desktop frontend (in the same venv):
   python app/frontend/main.py

Drone (Raspberry Pi / on-board computer)
1. On the Pi, copy the files from the drone/ directory to the Pi's filesystem.
2. Create and activate a virtual environment in the drone folder and install dependencies:
   python -m venv .venv
   source .venv/bin/activate
   pip install aiortc aiohttp av

3. Adjust server.py camera device and options (e.g. /dev/video4) if needed.
4. Configure the included systemd service: drone/WebRTCStream.service must be edited to match the correct User, WorkingDirectory and ExecStart paths for your Pi. Then install and enable it:
   sudo mv WebRTCStream.service /etc/systemd/system/WebRTCStream.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now WebRTCStream.service

   Or run the server manually for testing:
   source .venv/bin/activate && python server.py
   Visit http://<PI_IP>:8080 to verify the stream.

Running a flight
- Start the Pi stream and the backend.
- Open the frontend application and press "Start Flight" (or call POST /system/flight/start) to enable the backend and connect to the Pi stream.
- Toggle "AI" in the frontend to enable inference (inference can also start by calling /webrtc/offer/inference).

Troubleshooting
- ImportError: "sia module not found" — ensure DEFAULT_MODEL_PATH points to the folder containing the "sia" package and that the weights/gpt files are present.
- aiortc / PyAV build errors — install the system libraries listed above (ffmpeg and development headers) before pip installing aiortc/av.
- PyTorch: install the correct wheel for CPU or CUDA from https://pytorch.org.

If anything is unclear or an installation step fails, provide the error output and the target OS (desktop or Pi) and the preferred GPU/CPU configuration.
## Drone Setup
The drone's on-board computer must be running a debian-based OS (i.e. PiOS or Jetson Linux). While other operating systems may run the provided code, none have been tested and are not confirmed to have full functionality.

### Drone WLAN
Install RaspAP [here](https://docs.raspap.com/get-started/).

If using an external wifi adapter, make sure to change the interface in the RaspAP webgui.

NOTE: RaspAP is not necessarily required, any other means of having the ground station laptop and drone on the same network will suffice (i.e. hostapd).

### Video Server
On your on-board computer, put the files from the "drone" directory somewhere in the drone computer's filesystem.

Make changes to drone/server.py to match the system's configuration (device name for camera, hosting address and port, etc.).

Create a python virtual environment using venv and install necessary packages:
```
# Create virtual environment
python -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Install necessary packages into virtual environment
pip install aiortc aiohttp
```

Modify the included example service file (drone/WebRTCStream.service) to match your file structure and system. Move this file into the systemd directory to add it as a service in linux:
```
mv WebRTCStream.service /etc/systemd/system/WebRTCStream.service
```

Set created service to start on boot:
```
sudo systemctl enable WebRTCStream.service
```

Reboot the system to confirm changes work as intended. Go to "http://[COMPUTER_IP]:[CONFIGURED_PORT]" to confirm a video stream is visible.
