import asyncio
import os
import time
import httpx
from aiortc import RTCPeerConnection, RTCSessionDescription
from av import VideoFrame
from pymavlink import mavutil

import os
from dotenv import load_dotenv
import importlib.util
import sys

# Load .env
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
dotenv_path = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path)

TELEMETRY_PORT = os.getenv("TELEMETRY_PORT")  # string path

# Telemetry receiver port, needs to be changed for ground station
RECIEVER_PORT = TELEMETRY_PORT

# Prefer an IP if possible. mDNS (raspberrypi.local) can be flaky on Windows.
PI_OFFER_URL = os.getenv("PI_OFFER_URL", "http://10.3.141.1:8080/offer")

# Keep only latest frame
frame_queue: asyncio.Queue = asyncio.Queue(maxsize=1)

# ----------------------------
# Flight (backend on/off) state
# ----------------------------

_FLIGHT_ENABLED: bool = False
_FLIGHT_EVENT: asyncio.Event = asyncio.Event()
_FLIGHT_EVENT.clear()  # disabled by default


def is_flight_enabled() -> bool:
    return bool(_FLIGHT_ENABLED)


def set_flight_enabled(value: bool) -> None:
    global _FLIGHT_ENABLED
    _FLIGHT_ENABLED = bool(value)
    if _FLIGHT_ENABLED:
        _FLIGHT_EVENT.set()
    else:
        _FLIGHT_EVENT.clear()


def flight_enabled_event() -> asyncio.Event:
    return _FLIGHT_EVENT


# ----------------------------
# Pi connection / media health
# ----------------------------

_LAST_PI_FRAME_TS: float = 0.0
_PI_STREAM_OK: bool = False
_PI_ALIVE_WINDOW_S: float = 2.5


def mark_pi_frame_received() -> None:
    global _LAST_PI_FRAME_TS
    _LAST_PI_FRAME_TS = time.monotonic()


def set_pi_stream_ok(value: bool) -> None:
    global _PI_STREAM_OK
    _PI_STREAM_OK = bool(value)


def is_pi_stream_alive(window_s: float | None = None) -> bool:
    """
    True when:
      - we've successfully connected recently, AND
      - we've received a frame within the last window_s seconds
    """
    if window_s is None:
        window_s = _PI_ALIVE_WINDOW_S

    if not _PI_STREAM_OK:
        return False
    if _LAST_PI_FRAME_TS <= 0:
        return False

    return (time.monotonic() - _LAST_PI_FRAME_TS) <= float(window_s)


# ----------------------------
# Pause control for the Pi ingest loop
# ----------------------------

_pause_event = asyncio.Event()
_pause_event.set()  # not paused initially


def pause_pistream():
    _pause_event.clear()

    try:
        while frame_queue.full():
            frame_queue.get_nowait()
    except Exception:
        pass

    set_pi_stream_ok(False)


def resume_pistream():
    _pause_event.set()


async def push_frames_to_queue(track, disconnect_event: asyncio.Event, last_frame_ts: dict):
    """
    Receives frames from a remote video track and puts them into frame_queue.
    Updates last_frame_ts["t"] whenever a frame is received.
    If track.recv() errors, signal disconnect.
    """
    while not disconnect_event.is_set():
        try:
            frame: VideoFrame = await track.recv()
            img = frame.to_ndarray(format="bgr24")

            t = time.monotonic()
            last_frame_ts["t"] = t
            mark_pi_frame_received()

            if frame_queue.full():
                try:
                    frame_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

            await frame_queue.put(img)

        except Exception as e:
            print(f"❌ Track error (stopping frame push): {e}")
            disconnect_event.set()
            break


async def _watchdog(disconnect_event: asyncio.Event, last_frame_ts: dict, stall_s: float = 3.0):
    """
    If we stop receiving frames for stall_s seconds, force a reconnect.
    This catches cases where ICE/connection state doesn't transition, but media stalls.
    """
    while not disconnect_event.is_set():
        await asyncio.sleep(0.5)
        if (time.monotonic() - last_frame_ts["t"]) > stall_s:
            print(f"⚠️ Frame stall detected (> {stall_s}s). Forcing reconnect...")
            disconnect_event.set()
            break


# ----------------------------
# Telemetry state
# ----------------------------

telemetry_data = {
    "connected": False,
    "lat": 0.0,
    "lon": 0.0,
    "alt": 0.0,
    "heading": 0,
    "battery": 0,
    "speed": 0.0,
}


async def telemetry_loop():
    """
    Task to read MAVLink data from radio.
    """
    print(f"Starting mavlink service with port: {RECIEVER_PORT}")

    while True:
        conn = None
        try:
            print("Connecting to radio...")
            conn = await asyncio.to_thread(
                mavutil.mavlink_connection,
                RECIEVER_PORT,
                baud=57600,
            )

            print("Waiting for heartbeat...")
            await asyncio.to_thread(conn.wait_heartbeat)
            print("Mavlink heartbeat received! Telemetry is active.")

            telemetry_data["connected"] = True

            while True:
                msg = await asyncio.to_thread(conn.recv_match, blocking=True, timeout=1.0)

                # No message this cycle -> keep looping without crashing
                if msg is None:
                    await asyncio.sleep(0.01)
                    continue

                msg_type = msg.get_type()

                if msg_type == "GPS_RAW_INT":
                    telemetry_data["lat"] = msg.lat / 1e7
                    telemetry_data["lon"] = msg.lon / 1e7
                    telemetry_data["alt"] = msg.alt / 1000.0

                elif msg_type == "GLOBAL_POSITION_INT":
                    # Fallback/extra source for relative altitude if needed
                    telemetry_data["lat"] = msg.lat / 1e7
                    telemetry_data["lon"] = msg.lon / 1e7
                    telemetry_data["alt"] = msg.relative_alt / 1000.0

                elif msg_type == "VFR_HUD":
                    telemetry_data["heading"] = int(msg.heading)
                    telemetry_data["speed"] = float(msg.groundspeed)

                elif msg_type == "SYS_STATUS":
                    telemetry_data["battery"] = int(msg.battery_remaining)

                await asyncio.sleep(0.01)

        except Exception as e:
            print(f"Telemetry error: {e}")
            telemetry_data["connected"] = False

            # Optional: keep last known coordinates, but clear non-positional values if you want
            # telemetry_data["heading"] = 0
            # telemetry_data["speed"] = 0.0
            # telemetry_data["battery"] = 0

            try:
                if conn is not None:
                    await asyncio.to_thread(conn.close)
            except Exception:
                pass

            await asyncio.sleep(5)


async def connect_webrtc():
    """
    Persistent loop:
      - creates a PC
      - offers to the Pi
      - receives track + pushes frames
      - watches connection state + watchdog
      - reconnects on failure

    Respects flight enabled/disabled state and pause state.
    Also tracks Pi stream health so the frontend can be blocked when Pi is down.
    """
    while True:
        await _FLIGHT_EVENT.wait()
        await _pause_event.wait()

        pc = None
        disconnect_event = asyncio.Event()
        frame_task = None
        watchdog_task = None
        last_frame_ts = {"t": time.monotonic()}

        set_pi_stream_ok(False)

        try:
            pc = RTCPeerConnection()
            pc.addTransceiver("video", direction="recvonly")

            @pc.on("track")
            def on_track(track):
                print(f"🎥 Received track: {track.kind}")
                if track.kind == "video":
                    nonlocal frame_task
                    if frame_task and not frame_task.done():
                        frame_task.cancel()
                    frame_task = asyncio.create_task(
                        push_frames_to_queue(track, disconnect_event, last_frame_ts)
                    )

            @pc.on("connectionstatechange")
            async def on_conn_state():
                print(f"🌐 PC connectionState = {pc.connectionState}")
                if pc.connectionState in ("failed", "closed", "disconnected"):
                    disconnect_event.set()

            @pc.on("iceconnectionstatechange")
            async def on_ice_state():
                print(f"🧊 ICE state = {pc.iceConnectionState}")
                if pc.iceConnectionState in ("failed", "disconnected", "closed"):
                    disconnect_event.set()

            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)

            print("📨 Sending OFFER to Pi...")
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    PI_OFFER_URL,
                    json={"sdp": offer.sdp, "type": offer.type},
                )

            if resp.status_code != 200:
                print(f"❌ Pi returned {resp.status_code}: {resp.text}")
                await asyncio.sleep(2)
                continue

            answer_json = resp.json()

            if "sdp" not in answer_json or "type" not in answer_json:
                raise KeyError("sdp/type missing from Pi answer")

            answer = RTCSessionDescription(answer_json["sdp"], answer_json["type"])
            await pc.setRemoteDescription(answer)

            set_pi_stream_ok(True)
            print("✅ Pi WebRTC signaling complete — waiting for frames...")

            watchdog_task = asyncio.create_task(
                _watchdog(disconnect_event, last_frame_ts, stall_s=3.0)
            )

            while not disconnect_event.is_set():
                if (not _FLIGHT_EVENT.is_set()) or (not _pause_event.is_set()):
                    disconnect_event.set()
                    break
                await asyncio.sleep(0.2)

            print("⚠️ Pi WebRTC disconnected/stalled — reconnecting...")

        except Exception as e:
            print(f"❌ WebRTC error: {e}")

        finally:
            set_pi_stream_ok(False)

            if watchdog_task and not watchdog_task.done():
                watchdog_task.cancel()
            if frame_task and not frame_task.done():
                frame_task.cancel()

            if pc is not None:
                try:
                    await pc.close()
                except Exception:
                    pass

            await asyncio.sleep(2)
