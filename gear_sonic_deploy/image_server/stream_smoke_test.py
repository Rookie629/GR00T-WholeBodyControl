#!/usr/bin/env python3
"""Minimal viewer for G1 state and D435 bridge streams."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import cv2
import numpy as np

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from gear_sonic_deploy.sonic_data.camera_client import ComposedCameraClientSensor
from gear_sonic_deploy.sonic_data.ros_utils import ROSManager, ROSMsgSubscriber
from gear_sonic_deploy.sonic_data.topics import STATE_TOPIC_NAME


def colorize_depth(depth: np.ndarray, max_depth_mm: int) -> np.ndarray:
    clipped = np.clip(depth, 0, max_depth_mm)
    depth_u8 = cv2.convertScaleAbs(clipped, alpha=255.0 / max_depth_mm)
    return cv2.applyColorMap(depth_u8, cv2.COLORMAP_JET)


def draw_text(image: np.ndarray, lines: list[str]) -> np.ndarray:
    canvas = image.copy()
    y = 28
    for line in lines:
        cv2.putText(
            canvas,
            line,
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            line,
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (20, 20, 20),
            1,
            cv2.LINE_AA,
        )
        y += 26
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera-host", default="127.0.0.1")
    parser.add_argument("--camera-port", type=int, default=5560)
    parser.add_argument("--state-topic", default=STATE_TOPIC_NAME)
    parser.add_argument("--max-depth-mm", type=int, default=3000)
    parser.add_argument("--window-name", default="G1 Stream Smoke Test")
    args = parser.parse_args()

    camera = ComposedCameraClientSensor(server_ip=args.camera_host, port=args.camera_port)
    state_sub = ROSMsgSubscriber(args.state_topic)

    latest_state = None
    state_count = 0
    image_count = 0
    state_hz = 0.0
    image_hz = 0.0
    stats_t0 = time.monotonic()

    print(f"Listening camera tcp://{args.camera_host}:{args.camera_port}")
    print(f"Listening state topic {args.state_topic}")
    print("Press q in the OpenCV window to quit.")

    try:
        while ROSManager.ok():
            image_msg = camera.read()
            image_count += 1

            state_msg = state_sub.get_msg()
            if state_msg is not None:
                latest_state = state_msg
                state_count += 1

            now = time.monotonic()
            dt = now - stats_t0
            if dt >= 1.0:
                image_hz = image_count / dt
                state_hz = state_count / dt
                image_count = 0
                state_count = 0
                stats_t0 = now

            images = image_msg["images"]
            timestamps = image_msg["timestamps"]

            if "ego_view" not in images:
                available = ", ".join(sorted(images.keys()))
                raise RuntimeError(f"Missing ego_view in camera stream. Available keys: {available}")

            color_rgb = images["ego_view"]
            color_bgr = cv2.cvtColor(color_rgb, cv2.COLOR_RGB2BGR)

            panels = [color_bgr]
            if "ego_view_depth" in images:
                depth = images["ego_view_depth"]
                depth_vis = colorize_depth(depth, args.max_depth_mm)
                if depth_vis.shape[:2] != color_bgr.shape[:2]:
                    depth_vis = cv2.resize(depth_vis, (color_bgr.shape[1], color_bgr.shape[0]))
                panels.append(depth_vis)

            canvas = np.hstack(panels)

            if latest_state is None:
                state_line = "state: waiting"
                q_line = "q/action: waiting"
            else:
                q = np.asarray(latest_state.get("q", []))
                action = np.asarray(latest_state.get("action", []))
                q_line = f"q_dim={q.size} action_dim={action.size}"
                state_line = (
                    "state:"
                    f" base_height={latest_state.get('base_height_command', 'n/a')}"
                    f" nav={np.asarray(latest_state.get('navigate_command', []))}"
                )

            overlay_lines = [
                f"camera_hz={image_hz:.1f} state_hz={state_hz:.1f}",
                f"image_keys={','.join(sorted(images.keys()))}",
                f"img_ts={','.join(f'{k}:{v:.3f}' for k, v in sorted(timestamps.items()))}",
                q_line,
                state_line,
            ]
            canvas = draw_text(canvas, overlay_lines)

            cv2.imshow(args.window_name, canvas)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
    except KeyboardInterrupt:
        pass
    finally:
        camera.close()
        cv2.destroyAllWindows()
        ROSManager.shutdown()


if __name__ == "__main__":
    main()
