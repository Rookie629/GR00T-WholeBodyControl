#!/usr/bin/env python3
"""Minimal RealSense viewer for checking device availability."""

from __future__ import annotations

import argparse
import sys
import time

import cv2
import numpy as np

try:
    import pyrealsense2 as rs
except Exception as exc:
    print(f"Failed to import pyrealsense2: {exc}")
    sys.exit(1)


def list_devices() -> list[str]:
    ctx = rs.context()
    serials = []
    for dev in ctx.devices:
        try:
            name = dev.get_info(rs.camera_info.name)
            serial = dev.get_info(rs.camera_info.serial_number)
            print(f"Found device: {name} serial={serial}")
            serials.append(serial)
        except Exception:
            continue
    return serials


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default=None, help="RealSense serial number")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--max-depth-mm", type=int, default=3000)
    args = parser.parse_args()

    serials = list_devices()
    if not serials:
        print("No RealSense devices found.")
        sys.exit(2)

    serial = args.serial
    if serial is None:
        if len(serials) > 1:
            print(f"Multiple devices found, please specify --serial. Available: {serials}")
            sys.exit(3)
        serial = serials[0]

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_device(serial)
    config.enable_stream(rs.stream.color, args.width, args.height, rs.format.bgr8, args.fps)
    config.enable_stream(rs.stream.depth, args.width, args.height, rs.format.z16, args.fps)

    align = rs.align(rs.stream.color)
    profile = pipeline.start(config)
    device = profile.get_device()
    depth_sensor = device.first_depth_sensor()
    depth_scale = depth_sensor.get_depth_scale()

    print(f"Using serial={serial}")
    print(f"Depth scale={depth_scale} meters/unit")
    print("Press q in the window to quit.")

    frame_count = 0
    t0 = time.monotonic()

    try:
        while True:
            frames = pipeline.wait_for_frames()
            frames = align.process(frames)

            color_frame = frames.get_color_frame()
            depth_frame = frames.get_depth_frame()
            if not color_frame or not depth_frame:
                continue

            color = np.asanyarray(color_frame.get_data())
            depth = np.asanyarray(depth_frame.get_data())

            depth_clipped = np.clip(depth, 0, args.max_depth_mm)
            depth_u8 = cv2.convertScaleAbs(depth_clipped, alpha=255.0 / args.max_depth_mm)
            depth_vis = cv2.applyColorMap(depth_u8, cv2.COLORMAP_JET)

            canvas = np.hstack([color, depth_vis])
            cv2.imshow("RealSense Smoke Test", canvas)

            frame_count += 1
            if frame_count % 30 == 0:
                dt = time.monotonic() - t0
                fps = frame_count / dt
                center_depth_mm = int(depth[depth.shape[0] // 2, depth.shape[1] // 2])
                print(f"fps={fps:.1f} color={color.shape} depth={depth.shape} center_depth_mm={center_depth_mm}")

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
