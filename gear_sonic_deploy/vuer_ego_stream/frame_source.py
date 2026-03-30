from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

import numpy as np


class ColorSpace(str, Enum):
    RGB = "rgb"
    BGR = "bgr"


@dataclass(slots=True)
class FramePacket:
    """Container for one frame and the metadata needed downstream."""

    image: np.ndarray
    color_space: ColorSpace
    timestamp_sec: float
    frame_index: int


class BaseFrameSource(ABC):
    """Generic frame-source interface so OpenCV can later be replaced cleanly."""

    @abstractmethod
    def open(self) -> None:
        """Allocate any native resources required by the source."""

    @abstractmethod
    def read(self) -> FramePacket | None:
        """Return the next available frame or None if no frame was available."""

    @abstractmethod
    def close(self) -> None:
        """Release any native resources held by the source."""


class OpenCVFrameSource(BaseFrameSource):
    """Default example source using cv2.VideoCapture."""

    def __init__(
        self,
        source: str,
        color_space: ColorSpace = ColorSpace.BGR,
        capture_width: int | None = None,
        capture_height: int | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.source = source
        self.color_space = color_space
        self.capture_width = capture_width
        self.capture_height = capture_height
        self.logger = logger or logging.getLogger(__name__)

        self._cv2 = None
        self._cap = None
        self._frame_index = 0

    def open(self) -> None:
        import cv2

        self._cv2 = cv2
        capture_source: int | str = _normalize_capture_source(self.source)
        self._cap = cv2.VideoCapture(capture_source)
        if not self._cap.isOpened():
            raise RuntimeError(f"OpenCV could not open source: {self.source!r}")

        if self.capture_width is not None:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.capture_width)
        if self.capture_height is not None:
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.capture_height)

        actual_width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = float(self._cap.get(cv2.CAP_PROP_FPS))

        self.logger.info(
            "Opened OpenCV source=%r actual_capture_size=%sx%s reported_fps=%.2f color_space=%s",
            self.source,
            actual_width,
            actual_height,
            actual_fps,
            self.color_space.value,
        )

    def read(self) -> FramePacket | None:
        if self._cap is None:
            raise RuntimeError("OpenCVFrameSource.read() called before open()")

        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None

        packet = FramePacket(
            image=frame,
            color_space=self.color_space,
            timestamp_sec=time.time(),
            frame_index=self._frame_index,
        )
        self._frame_index += 1
        return packet

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class SonicBridgeFrameSource(BaseFrameSource):
    """Frame source that matches the current sonic_data GUI preview path."""

    def __init__(
        self,
        host: str,
        port: int,
        timeout_ms: int = 100,
        image_key: str = "ego_view",
        logger: logging.Logger | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout_ms = timeout_ms
        self.image_key = image_key
        self.logger = logger or logging.getLogger(__name__)

        self._client = None
        self._frame_index = 0
        self._missing_key_logs = 0

    def open(self) -> None:
        from gear_sonic_deploy.sonic_data.camera_client import ComposedCameraClientSensor

        self._client = ComposedCameraClientSensor(
            server_ip=self.host,
            port=self.port,
            timeout_ms=self.timeout_ms,
        )
        self.logger.info(
            "Opened sonic bridge source host=%s port=%d image_key=%s",
            self.host,
            self.port,
            self.image_key,
        )

    def read(self) -> FramePacket | None:
        if self._client is None:
            raise RuntimeError("SonicBridgeFrameSource.read() called before open()")

        message = self._client.read()
        if message is None:
            return None

        images = message.get("images", {})
        if self.image_key not in images:
            self._missing_key_logs += 1
            if self._missing_key_logs <= 5 or self._missing_key_logs % 50 == 0:
                self.logger.warning(
                    "Missing image_key=%s in bridged stream. available_keys=%s",
                    self.image_key,
                    sorted(images.keys()),
                )
            return None

        image = images[self.image_key]
        timestamps = message.get("timestamps", {})
        timestamp_sec = float(timestamps.get(self.image_key, time.time()))
        packet = FramePacket(
            image=image,
            color_space=ColorSpace.RGB,
            timestamp_sec=timestamp_sec,
            frame_index=self._frame_index,
        )
        self._frame_index += 1
        return packet

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


class LatestFrameReader:
    """Background reader that always keeps the newest frame available."""

    def __init__(
        self,
        source: BaseFrameSource,
        stats_interval_sec: float = 2.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.source = source
        self.stats_interval_sec = stats_interval_sec
        self.logger = logger or logging.getLogger(__name__)

        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._first_frame_event = threading.Event()
        self._latest: FramePacket | None = None
        self._exception: Exception | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("LatestFrameReader.start() called twice")

        self._thread = threading.Thread(
            target=self._reader_loop,
            name="vuer-ego-frame-reader",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def wait_for_first_frame(self, timeout_sec: float) -> bool:
        return self._first_frame_event.wait(timeout=timeout_sec)

    def get_latest(self) -> FramePacket | None:
        with self._lock:
            return self._latest

    def raise_if_failed(self) -> None:
        if self._exception is not None:
            raise RuntimeError("Frame reader thread failed") from self._exception

    def _reader_loop(self) -> None:
        frame_count = 0
        failure_count = 0
        last_stats_time = time.perf_counter()
        last_failure_log_time = 0.0
        first_shape_logged = False

        try:
            self.source.open()

            while not self._stop_event.is_set():
                packet = self.source.read()
                now = time.perf_counter()

                if packet is None:
                    failure_count += 1
                    if now - last_failure_log_time >= self.stats_interval_sec:
                        self.logger.warning(
                            "Frame source returned no frame. failures=%d",
                            failure_count,
                        )
                        last_failure_log_time = now
                    time.sleep(0.02)
                    continue

                if not first_shape_logged:
                    self.logger.info(
                        "First frame received: shape=%s dtype=%s color_space=%s",
                        packet.image.shape,
                        packet.image.dtype,
                        packet.color_space.value,
                    )
                    first_shape_logged = True

                with self._lock:
                    self._latest = packet

                self._first_frame_event.set()
                frame_count += 1

                if now - last_stats_time >= self.stats_interval_sec:
                    elapsed = now - last_stats_time
                    effective_fps = frame_count / elapsed if elapsed > 0 else 0.0
                    self.logger.info(
                        "Capture stats: fps=%.2f latest_shape=%s latest_dtype=%s failures=%d",
                        effective_fps,
                        packet.image.shape,
                        packet.image.dtype,
                        failure_count,
                    )
                    frame_count = 0
                    failure_count = 0
                    last_stats_time = now

        except Exception as exc:  # pragma: no cover - best-effort runtime logging
            self._exception = exc
            self.logger.exception("Frame reader thread crashed: %s", exc)
        finally:
            try:
                self.source.close()
            except Exception:  # pragma: no cover - cleanup path
                self.logger.exception("Failed to close frame source cleanly")


def _normalize_capture_source(value: str) -> int | str:
    if value.lstrip("-").isdigit():
        return int(value)
    return value
