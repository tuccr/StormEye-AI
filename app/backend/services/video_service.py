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

    def _read_frame(self):
        if self.cap:
            ret, frame = self.cap.read()
            if not ret:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self.cap.read()
            frame = cv2.resize(frame, (640, 480)) if ret else np.zeros((480, 640, 3), dtype=np.uint8)
        else:
            frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        return frame

import torch
import torch.nn.functional as F
from backend.services.model_service import model, tfs, postprocess, avatextaug
    
from aiortc import VideoStreamTrack
import av
import numpy as np
import cv2
from backend.api.routes.pistream_routes import frame_queue
import av

class InferenceVideoTrack(VideoStreamTrack):
    """Video stream that runs model inference on frames from Pi stream."""
    def __init__(self, actions=None, thresh=0.25, send_data_func = None):
        super().__init__()
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.captions = [a.replace('_', ' ') for a in actions] if actions else list(avatextaug.keys())
        self.text_embeds = model.encode_text(self.captions)
        self.text_embeds = F.normalize(self.text_embeds, dim=-1)
        self.thresh = thresh
        self.buffer = []
        self.buffer_max_len = 72
        self.mididx = self.buffer_max_len // 2
        self.imgsize = (240, 320)
        self.send_data_func = send_data_func

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        # ✅ Get the next frame from the Pi stream queue
        frame = await frame_queue.get()  # will wait until a frame is available
        if frame is None:
            # If somehow we get None, just return a blank frame
            frame = np.zeros((self.imgsize[0], self.imgsize[1], 3), dtype=np.uint8)

        # Resize and store in buffer
        raw_frame = cv2.resize(frame, (self.imgsize[1], self.imgsize[0]))
        self.buffer.append(raw_frame.transpose(2, 0, 1))
        if len(self.buffer) > self.buffer_max_len:
            _ = self.buffer.pop(0)

        # Run inference only when buffer fills
        if len(self.buffer) == self.buffer_max_len:
            print("buffer full")
            with torch.no_grad():
                clip = torch.tensor(np.array(self.buffer)[0:self.buffer_max_len:self.buffer_max_len // 9]) / 255
                clip = tfs(clip)
                outputs = model.encode_vision(clip.unsqueeze(0).to(self.device))
                outputs['pred_logits'] = F.normalize(outputs['pred_logits'], dim=-1) @ self.text_embeds.T
                result = postprocess(outputs, (480, 640), human_conf=0.0, thresh=self.thresh)[0]
                result['text_labels'] = [[self.captions[e] for e in ele] for ele in result['labels']]
                #frame = self._draw_boxes(frame, result)
                print("predictions made")
                box_data = self._get_data(result)
                if self.send_data_func:
                    self.send_data_func(box_data)

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_frame = VideoFrame.from_ndarray(frame, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        print("frame returned")
        return video_frame

    def _draw_boxes(self, frame, result):
        # Ensure using a BGR frame for drawing
        draw = frame.copy()

        boxes = result["boxes"]
        labels = result["text_labels"]
        scores = result["scores"]

        for j in range(len(boxes)):
            # boxes must be (x1, y1, x2, y2)
            x1, y1, x2, y2 = boxes[j].cpu().detach().numpy().astype(int)

            cv2.rectangle(draw, (x1, y1), (x2, y2), (0, 255, 0), 2)

            # Draw all text labels for this box
            y_offset = y1
            for k, lab in enumerate(labels[j]):
                score_val = float(scores[j][k].item())
                caption = f"{lab} {score_val:.2f}"
                cv2.putText(draw, caption, (x1, y_offset),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                y_offset += 22

        return draw

    def _get_data(self, result):
        boxes, labels, scores = result['boxes'], result['text_labels'], result['scores']
        box_data = []
        for j in range(len(boxes)):
            box = boxes[j].cpu().detach().numpy().astype(int)
            label = labels[j]
            score = scores[j]
            print("getting data")

            box_data.append({
                "box": [int(b) for b in box],
                "labels": label,
                "scores": [float(s) for s in score]
            })
        return box_data

import av
from aiortc import VideoStreamTrack

class PiStreamTrack(VideoStreamTrack):
    """
    Sends video frames from frame_queue to a remote peer.
    """
    def __init__(self):
        super().__init__()

    async def recv(self):
        # Get latest frame, do not block forever
        frame = await frame_queue.get()

        if frame is None:
            # Send a black frame if no frame available
            import numpy as np
            frame = np.zeros((480, 640, 3), dtype=np.uint8)

        pts, time_base = await self.next_timestamp()
        new_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
        new_frame.pts = pts
        new_frame.time_base = time_base
        return new_frame
