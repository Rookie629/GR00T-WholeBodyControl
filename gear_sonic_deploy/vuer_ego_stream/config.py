from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass(slots=True)
class StreamConfig:
    """Runtime configuration for the minimal Vuer ego-camera streamer."""

    source_type: str = "sonic_bridge"

    # Same source as the current sonic_data GUI preview.
    camera_host: str = "127.0.0.1"
    camera_port: int = 5560

    # Optional OpenCV fallback source for local testing or future replacement.
    source: str = "0"
    input_color_space: str = "bgr"

    # Resize target for the frame sent to Vuer.
    output_width: int = 640
    output_height: int = 480

    # Optional attempt to ask the capture backend for a given resolution.
    capture_width: int | None = None
    capture_height: int | None = None

    fps: float = 15.0
    jpeg_quality: int = 70

    host: str = "0.0.0.0"
    port: int = 8012

    # ImageBackground HUD placement controls.
    distance_to_camera: float = 1.0
    background_scale: float = 2.0
    position: tuple[float, float, float] = (0.0, 0.0, -3.0)
    fixed: bool = True
    interpolate: bool = True

    background_key: str = "ego-camera-background"
    stats_interval_sec: float = 2.0
    no_frame_warn_interval_sec: float = 2.0
    startup_frame_timeout_sec: float = 5.0
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        self.source_type = self.source_type.lower()
        if self.source_type not in {"sonic_bridge", "opencv"}:
            raise ValueError("source_type must be 'sonic_bridge' or 'opencv'")

        self.input_color_space = self.input_color_space.lower()
        if self.input_color_space not in {"rgb", "bgr"}:
            raise ValueError("input_color_space must be 'rgb' or 'bgr'")

        if self.camera_port <= 0:
            raise ValueError("camera_port must be positive")

        if self.background_scale <= 0:
            raise ValueError("background_scale must be positive")

        if self.output_width <= 0 or self.output_height <= 0:
            raise ValueError("output_width and output_height must be positive")

        if not (1 <= self.jpeg_quality <= 100):
            raise ValueError("jpeg_quality must be in [1, 100]")

        if self.fps <= 0:
            raise ValueError("fps must be positive")

        if self.stats_interval_sec <= 0:
            raise ValueError("stats_interval_sec must be positive")

        if self.no_frame_warn_interval_sec <= 0:
            raise ValueError("no_frame_warn_interval_sec must be positive")

        if self.startup_frame_timeout_sec <= 0:
            raise ValueError("startup_frame_timeout_sec must be positive")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stream a monocular camera feed into Vuer using ImageBackground. "
            "Default input matches the current sonic_data GUI preview source "
            "(ComposedCameraClientSensor over the bridged ego_view stream)."
        )
    )
    parser.add_argument(
        "--source-type",
        choices=("sonic_bridge", "opencv"),
        default="sonic_bridge",
        help=(
            "Frame source backend. 'sonic_bridge' matches the current GUI preview "
            "stream. 'opencv' keeps the earlier local webcam/file fallback."
        ),
    )
    parser.add_argument(
        "--camera-host",
        default="127.0.0.1",
        help="Host for ComposedCameraClientSensor. This is the same source used by the GUI preview.",
    )
    parser.add_argument(
        "--camera-port",
        type=int,
        default=5560,
        help="Port for ComposedCameraClientSensor. The GUI preview default is 5560.",
    )
    parser.add_argument(
        "--source",
        default="0",
        help=(
            "OpenCV source used only when --source-type opencv. Use '0' for the default "
            "webcam, an integer camera index, a video file path, or a network stream URL."
        ),
    )
    parser.add_argument(
        "--input-color-space",
        choices=("rgb", "bgr"),
        default="bgr",
        help="Color format returned by the frame provider. OpenCV usually returns BGR.",
    )
    parser.add_argument("--output-width", type=int, default=640, help="Output frame width in pixels.")
    parser.add_argument("--output-height", type=int, default=480, help="Output frame height in pixels.")
    parser.add_argument(
        "--capture-width",
        type=int,
        default=None,
        help="Optional width to request from OpenCV VideoCapture.",
    )
    parser.add_argument(
        "--capture-height",
        type=int,
        default=None,
        help="Optional height to request from OpenCV VideoCapture.",
    )
    parser.add_argument("--fps", type=float, default=15.0, help="Target Vuer update FPS.")
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=70,
        help="JPEG quality passed to Vuer ImageBackground.",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind host for the local Vuer server. Use 0.0.0.0 for later LAN/Pico access.",
    )
    parser.add_argument("--port", type=int, default=8012, help="Bind port for the Vuer server.")
    parser.add_argument(
        "--distance-to-camera",
        type=float,
        default=1.0,
        help="ImageBackground distanceToCamera.",
    )
    parser.add_argument(
        "--background-scale",
        type=float,
        default=2.0,
        help="ImageBackground scale factor in the browser. Increase this to enlarge the RGB stream.",
    )
    parser.add_argument(
        "--position",
        type=float,
        nargs=3,
        metavar=("X", "Y", "Z"),
        default=(0.0, 0.0, -3.0),
        help="ImageBackground position offset from the camera.",
    )
    parser.add_argument(
        "--no-fixed",
        dest="fixed",
        action="store_false",
        help="Disable fixed HUD behavior on the ImageBackground.",
    )
    parser.add_argument(
        "--no-interpolate",
        dest="interpolate",
        action="store_false",
        help="Disable interpolation in ImageBackground.",
    )
    parser.set_defaults(fixed=True, interpolate=True)
    parser.add_argument(
        "--stats-interval-sec",
        type=float,
        default=2.0,
        help="Seconds between FPS/stat logging.",
    )
    parser.add_argument(
        "--startup-frame-timeout-sec",
        type=float,
        default=5.0,
        help="How long to wait for the first frame before warning.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="Python logging level.",
    )
    return parser


def stream_config_from_args(args: argparse.Namespace) -> StreamConfig:
    return StreamConfig(
        source_type=args.source_type,
        camera_host=args.camera_host,
        camera_port=args.camera_port,
        source=args.source,
        input_color_space=args.input_color_space,
        output_width=args.output_width,
        output_height=args.output_height,
        capture_width=args.capture_width,
        capture_height=args.capture_height,
        fps=args.fps,
        jpeg_quality=args.jpeg_quality,
        host=args.host,
        port=args.port,
        distance_to_camera=args.distance_to_camera,
        background_scale=args.background_scale,
        position=tuple(float(v) for v in args.position),
        fixed=args.fixed,
        interpolate=args.interpolate,
        stats_interval_sec=args.stats_interval_sec,
        startup_frame_timeout_sec=args.startup_frame_timeout_sec,
        log_level=args.log_level,
    )
