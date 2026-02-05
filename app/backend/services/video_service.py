# backend/services/video_service.py

import os
import asyncio
from typing import Callable, Optional, Any, List, Dict, Tuple
from collections import deque

import cv2
import numpy as np
import av
from aiortc import VideoStreamTrack
from av import VideoFrame

import torch
import torch.nn.functional as F

from backend.services.model_service import model, tfs, postprocess, avatextaug
from backend.api.routes.pistream_routes import frame_queue


async def _get_latest_frame(timeout_s: float = 1.0) -> Optional[np.ndarray]:
    """
    Try to get a frame from the Pi queue without blocking forever.
    Returns None on timeout.
    """
    try:
        return await asyncio.wait_for(frame_queue.get(), timeout=timeout_s)
    except asyncio.TimeoutError:
        return None


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

    Key reliability improvement:
    - Never block forever waiting for a frame.
    - If the Pi stops sending temporarily, keep streaming the last frame.
    """

    def __init__(self):
        super().__init__()
        self._last = np.zeros((480, 640, 3), dtype=np.uint8)

    async def recv(self) -> av.VideoFrame:
        pts, time_base = await self.next_timestamp()

        frame = await _get_latest_frame(timeout_s=1.0)
        if frame is None:
            frame = self._last
        else:
            self._last = frame

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

    Reliability improvements:
    - Never block forever if Pi frames stop (timeout + last frame).
    - postprocess uses the REAL output frame size (fixes drift).
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
        self.buffer_max_len = 72  # adjust as needed
        self.buffer = deque(maxlen=self.buffer_max_len)  # stores (C,H,W) uint8 numpy arrays
        self.imgsize = (240, 320)  # (h, w) used for buffering only

        # ---- Preallocate inference tensors (reused every run) ----
        # We sample 9 frames from the 72-frame buffer at a fixed stride.
        step = max(1, self.buffer_max_len // 9)  # 72//9 = 8 -> indices 0..64
        self._sample_idx = list(range(0, self.buffer_max_len, step))[:9]

        H, W = self.imgsize  # (h,w)
        self._use_cuda = torch.cuda.is_available() and (self.device.startswith("cuda"))
        self._clip_cpu = torch.empty(
            (9, 3, H, W),
            dtype=torch.float32,
            pin_memory=self._use_cuda,  # enables non_blocking H2D copies
        )
        # Keep a persistent GPU tensor to avoid allocating every inference call.
        gpu_dtype = torch.float16 if self._use_cuda else torch.float32
        self._clip_gpu = torch.empty((9, 3, H, W), device=self.device, dtype=gpu_dtype)

        # Keep text embeddings on the same device/dtype as the vision logits we will matmul with.
        # This avoids Half vs Float dtype mismatches when using AMP / float16 inference.
        self.text_embeds = self.text_embeds.to(device=self.device, dtype=gpu_dtype)

        # Manual Normalize constants (ImageNet) for in-place normalization on GPU
        self._norm_mean = torch.tensor([0.485, 0.456, 0.406], device=self.device, dtype=gpu_dtype).view(1, 3, 1, 1)
        self._norm_std  = torch.tensor([0.229, 0.224, 0.225], device=self.device, dtype=gpu_dtype).view(1, 3, 1, 1)

        # Optional AMP for speed on CUDA
        self._use_amp = self._use_cuda and (gpu_dtype == torch.float16)

        # Callback to send inference results (boxes/labels/scores) to client overlay
        self.send_data_func = send_data_func

        # Background inference control
        self._infer_task: Optional[asyncio.Task] = None
        self._infer_lock = asyncio.Lock()

        # Last-good frame fallback for streaming continuity
        self._last = np.zeros((480, 640, 3), dtype=np.uint8)

        # Track real output size of the outgoing frames (h, w) for correct postprocess mapping
        self.out_size: Tuple[int, int] = (480, 640)

    async def recv(self) -> VideoFrame:
        pts, time_base = await self.next_timestamp()

        # Pull next frame from Pi queue, but don't stall forever
        frame = await _get_latest_frame(timeout_s=1.0)
        if frame is None:
            frame = self._last
        else:
            self._last = frame

        # Update output size (h, w) to match actual stream frames
        h, w = frame.shape[:2]
        self.out_size = (h, w)

        # Build buffer for inference (small frames)
        small = cv2.resize(frame, (self.imgsize[1], self.imgsize[0]))
        self.buffer.append(small.transpose(2, 0, 1))  # (C,H,W) uint8

        # If buffer full, start inference in the background (do not block recv)
        if len(self.buffer) == self.buffer_max_len:
            if self._infer_task is None or self._infer_task.done():
                # Shallow snapshot of references (cheap). We copy into preallocated tensors inside _run_inference.
                frames_snapshot = list(self.buffer)
                out_size_snapshot = self.out_size  # (h,w) for correct postprocess mapping
                self._infer_task = asyncio.create_task(
                    self._run_inference(frames_snapshot, out_size_snapshot)
                )

        # Return the live frame immediately
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_frame = VideoFrame.from_ndarray(frame_rgb, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame

    async def _run_inference(self, frames: List[np.ndarray], out_size: Tuple[int, int]) -> None:
        """
        Runs inference on a copy of the buffer and sends results via send_data_func.

        out_size is the (h, w) of the live stream frames the client is viewing.
        postprocess MUST use that size to produce correctly aligned pixel boxes.
        """
        async with self._infer_lock:
            try:
                # ---- Fill preallocated tensors (no big reallocations per loop) ----
                # frames are (C,H,W) uint8 numpy arrays.
                for k, idx in enumerate(self._sample_idx):
                    # CPU: copy into float32 tensor (casts uint8->float32)
                    self._clip_cpu[k].copy_(torch.from_numpy(frames[idx]), non_blocking=False)

                # Scale to [0,1] in-place on CPU
                self._clip_cpu.mul_(1.0 / 255.0)

                # H2D copy into persistent GPU tensor (no new allocations)
                self._clip_gpu.copy_(self._clip_cpu, non_blocking=self._use_cuda)

                # In-place normalize on GPU
                self._clip_gpu.sub_(self._norm_mean).div_(self._norm_std)

                with torch.no_grad():
                    if self._use_amp:
                        with torch.cuda.amp.autocast(dtype=torch.float16):
                            outputs = model.encode_vision(self._clip_gpu.unsqueeze(0))
                    else:
                        outputs = model.encode_vision(self._clip_gpu.unsqueeze(0))

                    # Ensure both sides of the matmul share dtype/device (AMP can make pred_logits fp16).
                    pred = outputs["pred_logits"].to(device=self.text_embeds.device, dtype=self.text_embeds.dtype)
                    outputs["pred_logits"] = F.normalize(pred, dim=-1) @ self.text_embeds.T

                    # FIX: use actual output frame size instead of hardcoded (480, 640)
                    result = postprocess(
                        outputs, out_size, human_conf=0.0, thresh=self.thresh
                    )[0]

                    result["text_labels"] = [
                        [self.captions[e] for e in ele] for ele in result["labels"]
                    ]

                box_data = self._get_data(result)

                if self.send_data_func:
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
