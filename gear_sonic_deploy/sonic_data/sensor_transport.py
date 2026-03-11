from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import cv2
import msgpack
import msgpack_numpy as m
import numpy as np
import zmq


@dataclass
class ImageMessageSchema:
    """Typed image transport schema used by the gear_sonic bridge/client path."""

    timestamps: dict[str, float]
    images: dict[str, np.ndarray]

    def serialize(self) -> dict[str, Any]:
        serialized_msg = {"timestamps": self.timestamps, "images": {}}
        for key, image in self.images.items():
            serialized_msg["images"][key] = ImageUtils.encode_typed_image(image)
        return serialized_msg

    @staticmethod
    def deserialize(data: dict[str, Any]) -> "ImageMessageSchema":
        timestamps = data.get("timestamps", {})
        images = {}
        for key, value in data.get("images", {}).items():
            if isinstance(value, (str, dict)):
                images[key] = ImageUtils.decode_typed_image(value)
            else:
                images[key] = value
        return ImageMessageSchema(timestamps=timestamps, images=images)

    def asdict(self) -> dict[str, Any]:
        return {"timestamps": self.timestamps, "images": self.images}


class SensorServer:
    def start_server(self, port: int) -> None:
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.setsockopt(zmq.SNDHWM, 20)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.bind(f"tcp://*:{port}")
        print(f"Sensor server running at tcp://*:{port}")
        self.message_sent = 0
        self.message_dropped = 0

    def stop_server(self) -> None:
        self.socket.close()
        self.context.term()

    def send_message(self, data: dict[str, Any]) -> None:
        try:
            packed = msgpack.packb(data, use_bin_type=True)
            self.socket.send(packed, flags=zmq.NOBLOCK)
        except zmq.Again:
            self.message_dropped += 1
            print(f"[Warning] message dropped: {self.message_dropped}")
        self.message_sent += 1
        if self.message_sent % 100 == 0:
            print(
                f"[Sensor server] Message sent: {self.message_sent}, message dropped: {self.message_dropped}"
            )


class SensorClient:
    def start_client(self, server_ip: str, port: int, timeout_ms: int | None = None) -> None:
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.setsockopt_string(zmq.SUBSCRIBE, "")
        self.socket.setsockopt(zmq.CONFLATE, True)
        self.socket.setsockopt(zmq.RCVHWM, 3)
        if timeout_ms is not None:
            self.socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
        self.socket.connect(f"tcp://{server_ip}:{port}")

    def stop_client(self) -> None:
        self.socket.close()
        self.context.term()

    def receive_message(self) -> dict[str, Any] | None:
        try:
            packed = self.socket.recv()
        except zmq.Again:
            return None
        return msgpack.unpackb(packed, object_hook=m.decode)


class ImageUtils:
    @staticmethod
    def is_depth_image(image: np.ndarray) -> bool:
        return image.dtype == np.uint16 and image.ndim == 2

    @staticmethod
    def encode_image(image: np.ndarray) -> str:
        _, color_buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return base64.b64encode(color_buffer).decode("utf-8")

    @staticmethod
    def encode_depth_image(image: np.ndarray) -> str:
        depth_compressed = cv2.imencode(".png", image)[1].tobytes()
        return base64.b64encode(depth_compressed).decode("utf-8")

    @staticmethod
    def decode_image(image: str) -> np.ndarray:
        color_data = base64.b64decode(image)
        color_array = np.frombuffer(color_data, dtype=np.uint8)
        return cv2.imdecode(color_array, cv2.IMREAD_COLOR)

    @staticmethod
    def decode_depth_image(image: str) -> np.ndarray:
        depth_data = base64.b64decode(image)
        depth_array = np.frombuffer(depth_data, dtype=np.uint8)
        return cv2.imdecode(depth_array, cv2.IMREAD_UNCHANGED)

    @staticmethod
    def encode_typed_image(image: np.ndarray) -> dict[str, str]:
        if ImageUtils.is_depth_image(image):
            return {"encoding": "png_depth_base64", "data": ImageUtils.encode_depth_image(image)}
        return {"encoding": "jpg_base64", "data": ImageUtils.encode_image(image)}

    @staticmethod
    def decode_typed_image(image: str | dict[str, str]) -> np.ndarray:
        if isinstance(image, str):
            return ImageUtils.decode_image(image)

        encoding = image.get("encoding")
        payload = image.get("data")
        if encoding == "png_depth_base64":
            return ImageUtils.decode_depth_image(payload)
        if encoding == "jpg_base64":
            return ImageUtils.decode_image(payload)
        raise ValueError(f"Unsupported image encoding: {encoding}")
