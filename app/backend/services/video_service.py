# backend/services/video_service.py

import os
import asyncio
from typing import Callable, Optional, Any, List, Dict

import cv2
import numpy as np
import av
from aiortc import VideoStreamTrack
from av import VideoFrame

import torch
import torch.nn.functional as F

from backend.services.model_service import model, tfs, postprocess, avatextaug
from backend.api.routes.pistream_routes import frame_queue


class VideoCameraTrack(VideoStreamTrack):
    """
    Simple video track that either plays from a file or generates random frames.
    (Useful for local testing when no Pi stream is present.)
    """

    def __init__(self, video_path: Optional[str] = None):
        super().__init__()
        if video_path and os.path.exists(video_path):
            self.cap = cv2.VideoCapture(video_path)
        else:
            self.cap = None

    def _read_frame(self) -> np.ndarray:
        if self.cap:
            ret, frame = self.cap.read()
            if not ret:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self.cap.read()

            if ret and frame is not None:
                frame = cv2.resize(frame, (640, 480))
            else:
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
        else:
            frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

        return frame

    async def recv(self) -> VideoFrame:
        pts, time_base = await self.next_timestamp()

        frame_bgr = self._read_frame()
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        video_frame = VideoFrame.from_ndarray(frame_rgb, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame


class PiStreamTrack(VideoStreamTrack):
    """
    Sends frames directly from the Pi frame_queue to the peer (no inference).
    """

    def __init__(self):
        super().__init__()

    async def recv(self) -> av.VideoFrame:
        frame = await frame_queue.get()

        if frame is None:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)

        pts, time_base = await self.next_timestamp()
        new_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
        new_frame.pts = pts
        new_frame.time_base = time_base
        return new_frame


class InferenceVideoTrack(VideoStreamTrack):
    """
    Video stream that runs model inference on frames from the Pi stream.

    IMPORTANT:
    - recv() must be fast. We DO NOT run inference inside recv().
    - When the buffer is full, we spawn a background task to run inference.
    - The video stream continues smoothly while inference runs.
    """

    def __init__(
        self,
        actions: Optional[List[str]] = None,
        thresh: float = 0.25,
        send_data_func: Optional[Callable[[Any], Any]] = None,
    ):
        super().__init__()

        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"

        self.captions = (
            [a.replace("_", " ") for a in actions]
            if actions
            else list(avatextaug.keys())
        )

        # Precompute and normalize text embeddings once
        self.text_embeds = model.encode_text(self.captions)
        self.text_embeds = F.normalize(self.text_embeds, dim=-1)

        self.thresh = thresh

        # Buffer settings
        self.buffer: List[np.ndarray] = []
        self.buffer_max_len = 72  # adjust as needed
        self.imgsize = (240, 320)  # (h, w) used for buffering only

        # Callback to send inference results (boxes/labels/scores) to client overlay
        self.send_data_func = send_data_func

        # Background inference control
        self._infer_task: Optional[asyncio.Task] = None
        self._infer_lock = asyncio.Lock()

    async def recv(self) -> VideoFrame:
        pts, time_base = await self.next_timestamp()

        # Pull next frame from Pi queue
        frame = await frame_queue.get()
        if frame is None:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Build buffer for inference (small frames)
        small = cv2.resize(frame, (self.imgsize[1], self.imgsize[0]))
        self.buffer.append(small.transpose(2, 0, 1))  # (C,H,W)

        if len(self.buffer) > self.buffer_max_len:
            self.buffer.pop(0)

        # If buffer full, start inference in the background (do not block recv)
        if len(self.buffer) == self.buffer_max_len:
            if self._infer_task is None or self._infer_task.done():
                buffer_copy = np.array(self.buffer, copy=True)
                self._infer_task = asyncio.create_task(self._run_inference(buffer_copy))

        # Return the live frame immediately
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_frame = VideoFrame.from_ndarray(frame_rgb, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame

    async def _run_inference(self, buffer_copy: np.ndarray) -> None:
        """
        Runs inference on a copy of the buffer and sends results via send_data_func.
        """
        async with self._infer_lock:
            try:
                # Sample frames for the model (your original logic)
                step = max(1, self.buffer_max_len // 9)
                sampled = buffer_copy[0 : self.buffer_max_len : step]

                with torch.no_grad():
                    clip = torch.tensor(sampled) / 255.0
                    clip = tfs(clip)
                    outputs = model.encode_vision(clip.unsqueeze(0).to(self.device))

                    outputs["pred_logits"] = (
                        F.normalize(outputs["pred_logits"], dim=-1) @ self.text_embeds.T
                    )

                    # NOTE: postprocess uses the *output* frame size (480, 640)
                    result = postprocess(
                        outputs, (480, 640), human_conf=0.0, thresh=self.thresh
                    )[0]

                    result["text_labels"] = [
                        [self.captions[e] for e in ele] for ele in result["labels"]
                    ]

                box_data = self._get_data(result)

                if self.send_data_func:
                    # If send_data_func is async, await it. If sync, call directly.
                    if asyncio.iscoroutinefunction(self.send_data_func):
                        await self.send_data_func(box_data)
                    else:
                        self.send_data_func(box_data)

            except Exception as e:
                print(f"❌ Inference task failed: {e}")

    def _draw_boxes(self, frame: np.ndarray, result: Dict[str, Any]) -> np.ndarray:
        """
        Optional: draw boxes directly on the outgoing video.
        (You currently do overlay on the frontend, so you likely won't use this.)
        """
        draw = frame.copy()

        boxes = result["boxes"]
        labels = result["text_labels"]
        scores = result["scores"]

        for j in range(len(boxes)):
            x1, y1, x2, y2 = boxes[j].cpu().detach().numpy().astype(int)
            cv2.rectangle(draw, (x1, y1), (x2, y2), (0, 255, 0), 2)

            y_offset = y1
            for k, lab in enumerate(labels[j]):
                score_val = float(scores[j][k].item())
                caption = f"{lab} {score_val:.2f}"
                cv2.putText(
                    draw,
                    caption,
                    (x1, y_offset),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2,
                )
                y_offset += 22

        return draw

    def _get_data(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Converts model output to JSON-serializable overlay data.
        """
        boxes, labels, scores = result["boxes"], result["text_labels"], result["scores"]

        box_data: List[Dict[str, Any]] = []
        for j in range(len(boxes)):
            box = boxes[j].cpu().detach().numpy().astype(int)
            label = labels[j]
            score = scores[j]

            box_data.append(
                {
                    "box": [int(b) for b in box],
                    "labels": label,
                    "scores": [float(s) for s in score],
                }
            )

        return box_data
