from __future__ import annotations

import cv2
import numpy as np


def colorize_depth(depth: np.ndarray, max_depth_mm: int) -> np.ndarray:
    clipped = np.clip(depth, 0, max_depth_mm)
    depth_u8 = cv2.convertScaleAbs(clipped, alpha=255.0 / max_depth_mm)
    return cv2.applyColorMap(depth_u8, cv2.COLORMAP_JET)
