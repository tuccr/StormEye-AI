import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP_VIDEO_DIR = os.path.join(BASE_DIR, "test_images")
DEFAULT_VIDEO_PATH = os.path.join(TEMP_VIDEO_DIR, "test2.mp4")
