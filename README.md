# StormEye-AI
A software which connects a drone to a laptop on the ground to assess storm damage using a state-of-the-art computer vision model.

# Jira Link
<https://stormeye-ai.atlassian.net/jira>

# Installation Instructions
There are two necessary setups for this codebase--the drone and ground station app.

## Application Setup
...

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
