"""OpenCV decoding through Python IO also supports Unicode Windows paths."""
from pathlib import Path
import cv2
import numpy as np


def imread(path, flags=cv2.IMREAD_COLOR):
    image = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), dtype=np.uint8), flags)
    if image is None:
        raise ValueError('Could not decode image: ' + str(path))
    return image
