from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from gear_sonic_deploy.vuer_ego_stream.frame_source import ColorSpace, FramePacket


@dataclass(slots=True)
class PreprocessConfig:
    output_width: int
    output_height: int


@dataclass(slots=True)
class ProcessedFrame:
    image_rgb: np.ndarray
    input_shape: tuple[int, ...]
    output_shape: tuple[int, ...]


def preprocess_frame(packet: FramePacket, config: PreprocessConfig) -> ProcessedFrame:
    """Validate, normalize, color-convert, and letterbox a single frame."""

    import cv2

    frame = packet.image
    if frame is None:
        raise ValueError("Received an empty frame")

    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(f"Expected HxWx3 image, got shape={frame.shape}")

    if frame.dtype != np.uint8:
        # Vuer's ImageBackground example uses uint8 image arrays, so normalize to that.
        frame = np.clip(frame, 0, 255).astype(np.uint8)

    if packet.color_space == ColorSpace.BGR:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    elif packet.color_space != ColorSpace.RGB:
        raise ValueError(f"Unsupported color space: {packet.color_space}")

    target_size = (config.output_width, config.output_height)
    current_size = (frame.shape[1], frame.shape[0])
    if current_size != target_size:
        frame = _letterbox_resize(frame, target_size)

    frame = np.ascontiguousarray(frame)
    return ProcessedFrame(
        image_rgb=frame,
        input_shape=packet.image.shape,
        output_shape=frame.shape,
    )


def _letterbox_resize(frame: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
    """Resize into a fixed canvas while preserving the source aspect ratio."""

    import cv2

    target_width, target_height = target_size
    source_height, source_width = frame.shape[:2]

    scale = min(target_width / source_width, target_height / source_height)
    resized_width = max(1, int(round(source_width * scale)))
    resized_height = max(1, int(round(source_height * scale)))

    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    resized = cv2.resize(frame, (resized_width, resized_height), interpolation=interpolation)

    canvas = np.zeros((target_height, target_width, 3), dtype=np.uint8)
    x0 = (target_width - resized_width) // 2
    y0 = (target_height - resized_height) // 2
    canvas[y0 : y0 + resized_height, x0 : x0 + resized_width] = resized
    return canvas
