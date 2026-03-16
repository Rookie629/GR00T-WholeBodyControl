#!/usr/bin/env python3
"""Bridge gear_sonic_deploy image_server frames to the local sonic camera schema."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import cv2

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from gear_sonic_deploy.sonic_data.constants import RS_VIEW_CAMERA_HEIGHT, RS_VIEW_CAMERA_WIDTH
from gear_sonic_deploy.sonic_data.sensor_transport import ImageMessageSchema, SensorServer

from image_client import ImageClient


class ComposedCameraBridge(SensorServer):
    def __init__(
        self,
        image_server_ip: str,
        image_server_port: int,
        output_port: int,
        include_depth: bool,
    ) -> None:
        self.client = ImageClient(
            image_show=False,
            server_address=image_server_ip,
            port=image_server_port,
        )
        self.start_server(output_port)
        self.frames_forwarded = 0
        self.include_depth = include_depth

    @staticmethod
    def _resize_color(color_rgb):
        expected_size = (RS_VIEW_CAMERA_WIDTH, RS_VIEW_CAMERA_HEIGHT)
        if color_rgb.shape[1] == expected_size[0] and color_rgb.shape[0] == expected_size[1]:
            return color_rgb
        return cv2.resize(color_rgb, expected_size, interpolation=cv2.INTER_AREA)

    @staticmethod
    def _resize_depth(depth):
        expected_size = (RS_VIEW_CAMERA_WIDTH, RS_VIEW_CAMERA_HEIGHT)
        if depth.shape[1] == expected_size[0] and depth.shape[0] == expected_size[1]:
            return depth
        return cv2.resize(depth, expected_size, interpolation=cv2.INTER_NEAREST)

    def run(self) -> None:
        print("Starting composed camera bridge...")
        try:
            while True:
                message = self.client._socket.recv()
                try:
                    ts, frame_id, color_bgr, depth = self.client._decode_payload(message)
                except Exception as exc:
                    print(f"[Bridge] decode error: {exc}")
                    continue

                if color_bgr is None:
                    continue

                color_rgb = color_bgr[:, :, ::-1]
                color_rgb = self._resize_color(color_rgb)
                timestamps = {"ego_view": ts}
                images = {"ego_view": color_rgb}
                if self.include_depth and depth is not None:
                    timestamps["ego_view_depth"] = ts
                    images["ego_view_depth"] = self._resize_depth(depth)

                bridged = ImageMessageSchema(
                    timestamps=timestamps,
                    images=images,
                ).serialize()
                self.send_message(bridged)
                self.frames_forwarded += 1

                if self.frames_forwarded % 100 == 0:
                    now = time.strftime("%H:%M:%S")
                    print(
                        f"[Bridge {now}] forwarded {self.frames_forwarded} frames "
                        f"(last frame_id={frame_id})"
                    )
        except KeyboardInterrupt:
            print("[Bridge] stopped by user")
        finally:
            self.client._close()
            self.stop_server()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-server-ip", default="127.0.0.1")
    parser.add_argument("--image-server-port", type=int, default=5555)
    parser.add_argument("--output-port", type=int, default=5560)
    parser.add_argument("--include-depth", action="store_true")
    args = parser.parse_args()

    bridge = ComposedCameraBridge(
        image_server_ip=args.image_server_ip,
        image_server_port=args.image_server_port,
        output_port=args.output_port,
        include_depth=args.include_depth,
    )
    bridge.run()


if __name__ == "__main__":
    main()
