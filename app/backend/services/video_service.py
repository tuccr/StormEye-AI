import os
import cv2
import numpy as np
from aiortc import VideoStreamTrack
from av import VideoFrame

class VideoCameraTrack(VideoStreamTrack):
    def __init__(self, video_path=None):
        super().__init__()
        if video_path and os.path.exists(video_path):
            self.cap = cv2.VideoCapture(video_path)
        else:
            self.cap = None

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        if self.cap:
            ret, frame = self.cap.read()
            if not ret:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self.cap.read()
            frame = cv2.resize(frame, (640, 480))
        else:
            frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_frame = VideoFrame.from_ndarray(frame, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame

