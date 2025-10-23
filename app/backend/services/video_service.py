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
    
class InferenceVideoTrack(VideoCameraTrack):
    """Video stream that runs model inference on frames."""
    def __init__(self, video_path=None, actions=None, thresh=0.25):
        super().__init__(video_path)
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.captions = [a.replace('_', ' ') for a in actions] if actions else list(avatextaug.keys())
        self.text_embeds = model.encode_text(self.captions)
        self.text_embeds = F.normalize(self.text_embeds, dim=-1)
        self.thresh = thresh
        self.buffer = []
        self.buffer_max_len = 72
        self.mididx = self.buffer_max_len // 2
        self.imgsize = (240, 320)

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        frame = self._read_frame()

        # Store in buffer
        raw_frame = cv2.resize(frame, (self.imgsize[1], self.imgsize[0]))
        self.buffer.append(raw_frame.transpose(2, 0, 1))
        if len(self.buffer) > self.buffer_max_len:
            _ = self.buffer.pop(0)

        # Only run inference once buffer fills
        if len(self.buffer) == self.buffer_max_len:
            with torch.no_grad():
                clip = torch.tensor(np.array(self.buffer)[0:self.buffer_max_len:self.buffer_max_len // 9]) / 255
                clip = tfs(clip)
                outputs = model.encode_vision(clip.unsqueeze(0).to(self.device))
                outputs['pred_logits'] = F.normalize(outputs['pred_logits'], dim=-1) @ self.text_embeds.T
                result = postprocess(outputs, (480, 640), human_conf=0.0, thresh=self.thresh)[0]
                result['text_labels'] = [[self.captions[e] for e in ele] for ele in result['labels']]
                frame = self._draw_boxes(frame, result)

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_frame = VideoFrame.from_ndarray(frame, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame

    def _draw_boxes(self, frame, result):
        boxes, labels, scores = result['boxes'], result['text_labels'], result['scores']
        for j in range(len(boxes)):
            box = boxes[j].cpu().detach().numpy().astype(int)
            label = labels[j]
            score = scores[j]
            color = (0, 255, 0)
            start_point, end_point = (box[0], box[1]), (box[2], box[3])
            cv2.rectangle(frame, start_point, end_point, color, 2)
            offset = 0
            for k in range(len(label)):
                text = f"{label[k]} {round(score[k].item(), 2)}"
                cv2.putText(frame, text, (box[0], box[1] + offset), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                offset += 20
        return frame

