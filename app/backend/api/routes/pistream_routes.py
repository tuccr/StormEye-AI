import asyncio
import os
import time
import httpx
from aiortc import RTCPeerConnection, RTCSessionDescription
from av import VideoFrame

# Prefer an IP if possible. mDNS (raspberrypi.local) can be flaky on Windows.
PI_OFFER_URL = os.getenv("PI_OFFER_URL", "http://10.3.141.1:8080/offer")

# Keep only latest frame
frame_queue: asyncio.Queue = asyncio.Queue(maxsize=1)


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

            last_frame_ts["t"] = time.monotonic()

            # Keep only the latest frame
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


async def connect_webrtc():
    """
    Persistent loop:
      - creates a PC
      - offers to the Pi
      - receives track + pushes frames
      - watches connection state + watchdog
      - reconnects on failure
    """
    while True:
        pc = None
        disconnect_event = asyncio.Event()
        frame_task = None
        watchdog_task = None

        # Track last received frame time
        last_frame_ts = {"t": time.monotonic()}

        try:
            pc = RTCPeerConnection()
            pc.addTransceiver("video", direction="recvonly")

            @pc.on("track")
            def on_track(track):
                print(f"🎥 Received track: {track.kind}")
                if track.kind == "video":
                    nonlocal frame_task
                    # Restart frame task if needed
                    if frame_task and not frame_task.done():
                        frame_task.cancel()
                    frame_task = asyncio.create_task(push_frames_to_queue(track, disconnect_event, last_frame_ts))

            @pc.on("connectionstatechange")
            async def on_conn_state():
                # "new"|"connecting"|"connected"|"disconnected"|"failed"|"closed"
                print(f"🌐 PC connectionState = {pc.connectionState}")
                if pc.connectionState in ("failed", "closed", "disconnected"):
                    disconnect_event.set()

            @pc.on("iceconnectionstatechange")
            async def on_ice_state():
                # "new"|"checking"|"connected"|"completed"|"failed"|"disconnected"|"closed"
                print(f"🧊 ICE state = {pc.iceConnectionState}")
                if pc.iceConnectionState in ("failed", "disconnected", "closed"):
                    disconnect_event.set()

            # 1) Create local offer
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)

            # 2) Send offer to Pi
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

            # 3) Set remote description (answer)
            answer_json = resp.json()
            answer = RTCSessionDescription(answer_json["sdp"], answer_json["type"])
            await pc.setRemoteDescription(answer)

            print("✅ Pi WebRTC connected! Streaming video...")

            # Start watchdog once connected
            watchdog_task = asyncio.create_task(_watchdog(disconnect_event, last_frame_ts, stall_s=3.0))

            # Wait until we detect disconnect (state change OR frame stall OR track error)
            await disconnect_event.wait()
            print("⚠️ Pi WebRTC disconnected/stalled — reconnecting...")

        except Exception as e:
            import traceback
            print(f"❌ WebRTC error: {e}")
            print(f"Type: {type(e)}")
            print(f"Repr: {repr(e)}")
            traceback.print_exc()

        finally:
            # Stop background tasks
            if watchdog_task and not watchdog_task.done():
                watchdog_task.cancel()
            if frame_task and not frame_task.done():
                frame_task.cancel()

            # Close PC
            if pc is not None:
                try:
                    await pc.close()
                except Exception:
                    pass

            # Small backoff before retry
            await asyncio.sleep(2)
