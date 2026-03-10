#!/usr/bin/env python3
"""Headless RealSense probe for checking camera availability on G1."""

from __future__ import annotations

import argparse
import sys

try:
    import pyrealsense2 as rs
except Exception as exc:
    print(f"ERROR: failed to import pyrealsense2: {exc}")
    sys.exit(1)


def list_devices() -> list[tuple[str, str]]:
    ctx = rs.context()
    devices: list[tuple[str, str]] = []
    for dev in ctx.devices:
        try:
            name = dev.get_info(rs.camera_info.name)
            serial = dev.get_info(rs.camera_info.serial_number)
            devices.append((name, serial))
        except Exception:
            continue
    return devices


def open_and_grab_one_frame(serial: str, width: int, height: int, fps: int) -> None:
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_device(serial)
    config.enable_stream(rs.stream.color, width, height, rs.format.bgr8, fps)
    config.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)

    try:
        pipeline.start(config)
        for _ in range(30):
            frames = pipeline.wait_for_frames()
            color_frame = frames.get_color_frame()
            depth_frame = frames.get_depth_frame()
            if color_frame and depth_frame:
                print(
                    "STREAM_OK:"
                    f" serial={serial}"
                    f" color=({color_frame.get_height()},{color_frame.get_width()},3)"
                    f" depth=({depth_frame.get_height()},{depth_frame.get_width()})"
                )
                return
        print(f"ERROR: found device {serial} but failed to get synchronized color/depth frames")
        sys.exit(3)
    finally:
        try:
            pipeline.stop()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default=None, help="RealSense serial number")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument(
        "--check-stream",
        action="store_true",
        help="Open the selected device and verify one color/depth frame can be read",
    )
    args = parser.parse_args()

    devices = list_devices()
    if not devices:
        print("NO_DEVICE")
        sys.exit(2)

    print(f"FOUND {len(devices)} REALSENSE DEVICE(S)")
    for name, serial in devices:
        print(f"DEVICE: name={name} serial={serial}")

    selected_serial = args.serial
    if selected_serial is None:
        if len(devices) == 1:
            selected_serial = devices[0][1]
        elif args.check_stream:
            print("ERROR: multiple devices found, please pass --serial for --check-stream")
            sys.exit(4)

    if args.check_stream and selected_serial is not None:
        open_and_grab_one_frame(selected_serial, args.width, args.height, args.fps)
    else:
        print("PROBE_OK")


if __name__ == "__main__":
    main()
