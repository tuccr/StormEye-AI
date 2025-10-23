# backend/services/model_service.py
import torch
import torch.nn.functional as F
import numpy as np
import cv2
import time
import json
from torchvision.transforms import v2

import os
from dotenv import load_dotenv
import importlib.util
import sys

# Load .env
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
dotenv_path = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path)

DEFAULT_MODEL_PATH = os.getenv("DEFAULT_MODEL_PATH")  # string path
DEFAULT_MODEL_PATH = os.path.expanduser(DEFAULT_MODEL_PATH)

# Add DEFAULT_MODEL_PATH to sys.path so Python can import modules from there
sys.path.append(DEFAULT_MODEL_PATH)

# Dynamically import sia module
sia_spec = importlib.util.find_spec("sia")
if sia_spec is None:
    raise ImportError(f"sia module not found in {DEFAULT_MODEL_PATH}")
sia_module = importlib.util.module_from_spec(sia_spec)
sia_spec.loader.exec_module(sia_module)

get_sia = sia_module.get_sia
PostProcessViz = sia_module.PostProcessViz

print("path found")

from util.box_ops import box_cxcywh_to_xyxy

# Load model once at import
device = "cuda:0" if torch.cuda.is_available() else "cpu"
print(f"Loading SIA model on {device}...")

weights_path = os.path.join(
    DEFAULT_MODEL_PATH,
    "weights",
    "avak_aws_stats_flt_b16_txtaug_txtlora",
    "avak_b16_10.pt"
)

model = get_sia(size='b', pretrain=None, det_token_num=20, text_lora=True, num_frames=9)['sia']
model.load_state_dict(
    torch.load(weights_path, weights_only=True),
    strict=False
)
model.to(device)
model.eval()

print("SIA model loaded successfully.")

gpt_path = os.path.join(
    DEFAULT_MODEL_PATH,
    "gpt",
    "GPT_AVA.json"
)

tfs = v2.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
postprocess = PostProcessViz()
avatextaug = json.load(open(gpt_path))


def run_inference(video_path: str, captions: list[str] = None, thresh: float = 0.25):
    """Run SIA inference on a video and return predictions."""

    cap = cv2.VideoCapture(video_path)
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    imgsize = (240, 320)
    
    if captions is None:
        captions = list(avatextaug.keys())
    else:
        captions = [c.replace('_', ' ') for c in captions]
        
    text_embeds = model.encode_text(captions)
    text_embeds = F.normalize(text_embeds, dim=-1)

    buffer_max_len = 72
    mididx = buffer_max_len // 2
    buffer, plotbuffer = [], []
    outsize = (frame_height, frame_width)
    writer = cv2.VideoWriter(
        f"DUMP/pred_{video_path.split('/')[-1]}",
        cv2.VideoWriter_fourcc(*'mp4v'),
        25,
        (frame_width, frame_height)
    )

    results = []
    init = 0
    ret = True
    out_frame = None

    while ret:
        ret, frame = cap.read()
        if not ret:
            break
        raw_image = frame
        plotbuffer.append(raw_image.transpose(2, 0, 1))
        raw_image = cv2.resize(raw_image, (imgsize[1], imgsize[0]), interpolation=cv2.INTER_NEAREST)
        buffer.append(raw_image.transpose(2, 0, 1))

        if len(buffer) > buffer_max_len:
            _ = buffer.pop(0)
            _ = plotbuffer.pop(0)
            clip_torch = torch.tensor(np.array(buffer)[0:buffer_max_len:buffer_max_len//9]) / 255
            clip_torch = tfs(clip_torch)

            with torch.no_grad():
                outputs = model.encode_vision(clip_torch.unsqueeze(0).to(device))
                outputs['pred_logits'] = F.normalize(outputs['pred_logits'], dim=-1) @ text_embeds.T
                result = postprocess(outputs, outsize, human_conf=0.0, thresh=thresh)[0]
                result['text_labels'] = [[captions[e] for e in ele] for ele in result['labels']]
                boxes = result['boxes']
                labels = result['text_labels']
                scores = result['scores']

            frame_out = plotbuffer[mididx].transpose(1, 2, 0)
            frame_preds = []
            for j in range(len(boxes)):
                box = boxes[j].cpu().detach().numpy().tolist()
                label = labels[j]
                score = [s.item() for s in scores[j]]
                frame_preds.append({"box": box, "labels": label, "scores": score})
            results.append(frame_preds)

            writer.write(frame_out)

    writer.release()
    cap.release()
    print('inference')

    return {
        "output_video": f"DUMP/pred_{video_path.split('/')[-1]}",
        "predictions": results,
    }

