import asyncio
import httpx
import re
import cv2
import numpy as np

PI_STREAM_URL = "http://raspberrypi.local:8089/"
frame_queue = asyncio.Queue(maxsize=1)  # holds the latest frame only

BOUNDARY = b"--BoundaryString"

async def connect_to_pi_stream():
    while True:
        print("📡 Attempting to connect to Raspberry Pi...")
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", PI_STREAM_URL) as response:
                    if response.status_code != 200:
                        print(f"⚠️ Pi responded with {response.status_code}")
                        await asyncio.sleep(5)
                        continue

                    print("✅ Connected to Pi stream successfully!")
                    buffer = b""

                    async for chunk in response.aiter_bytes():
                        buffer += chunk
                        while True:
                            start = buffer.find(BOUNDARY)
                            if start == -1:
                                break
                            end = buffer.find(BOUNDARY, start + len(BOUNDARY))
                            if end == -1:
                                break
                            frame_part = buffer[start:end]
                            buffer = buffer[end:]

                            # Extract JPEG bytes
                            match = re.search(b"\r\n\r\n", frame_part)
                            if match:
                                jpeg_bytes = frame_part[match.end():]
                                frame = cv2.imdecode(
                                    np.frombuffer(jpeg_bytes, np.uint8),
                                    cv2.IMREAD_COLOR
                                )
                                if frame is not None:
                                    if frame_queue.full():
                                        _ = frame_queue.get_nowait()
                                    await frame_queue.put(frame)
        except Exception as e:
            print(f"❌ Connection failed: {e}")
        print("⏳ Retrying in 5 seconds...")
        await asyncio.sleep(5)

