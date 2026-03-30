from __future__ import annotations

import asyncio
import logging
import time

from gear_sonic_deploy.vuer_ego_stream.config import StreamConfig
from gear_sonic_deploy.vuer_ego_stream.frame_source import LatestFrameReader
from gear_sonic_deploy.vuer_ego_stream.preprocess import PreprocessConfig, preprocess_frame


class EgoCameraVuerApp:
    """Owns the Vuer server and continuously upserts ImageBackground frames."""

    def __init__(
        self,
        config: StreamConfig,
        frame_reader: LatestFrameReader,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.frame_reader = frame_reader
        self.logger = logger or logging.getLogger(__name__)

    def run(self) -> None:
        try:
            from vuer import Vuer
            from vuer.schemas import ImageBackground, Scene
        except ModuleNotFoundError as exc:
            if exc.name == "vuer":
                raise ModuleNotFoundError(
                    "vuer is not installed in the active Python environment. "
                    "Activate .venv_teleop and install it with:\n"
                    "  uv pip install 'vuer==0.1.4'\n"
                    "or:\n"
                    "  python -m pip install 'vuer==0.1.4'"
                ) from exc
            raise

        self.frame_reader.start()
        if not self.frame_reader.wait_for_first_frame(self.config.startup_frame_timeout_sec):
            self.logger.warning(
                "No frame arrived within %.1fs. The Vuer app will still start, "
                "but the page will stay blank until frames begin arriving.",
                self.config.startup_frame_timeout_sec,
            )

        self.frame_reader.raise_if_failed()

        app = Vuer(host=self.config.host, port=self.config.port)

        @app.spawn(start=True)
        async def stream_background(session) -> None:
            # Minimal scene setup. The background image will be added into bgChildren.
            session.set @ Scene()
            self.logger.info("Browser session connected. Starting ImageBackground updates.")

            preprocess_config = PreprocessConfig(
                output_width=self.config.output_width,
                output_height=self.config.output_height,
            )
            target_period = 1.0 / self.config.fps
            last_stats_time = time.perf_counter()
            frames_sent = 0
            first_frame_logged = False
            last_no_frame_log = 0.0

            while True:
                loop_start = time.perf_counter()
                self.frame_reader.raise_if_failed()
                packet = self.frame_reader.get_latest()

                if packet is None:
                    now = time.perf_counter()
                    if now - last_no_frame_log >= self.config.no_frame_warn_interval_sec:
                        self.logger.warning("No frame available yet for Vuer upsert")
                        last_no_frame_log = now
                    await asyncio.sleep(min(target_period, 0.1))
                    continue

                processed = preprocess_frame(packet, preprocess_config)
                if not first_frame_logged:
                    self.logger.info(
                        "First Vuer frame prepared: raw_shape=%s raw_dtype=%s processed_shape=%s",
                        processed.input_shape,
                        packet.image.dtype,
                        processed.output_shape,
                    )
                    first_frame_logged = True

                # Assumption based on the official Vuer HUD example:
                # ImageBackground accepts a numpy HxWx3 uint8 image as the first positional arg.
                session.upsert(
                    ImageBackground(
                        processed.image_rgb,
                        format="jpeg",
                        quality=self.config.jpeg_quality,
                        key=self.config.background_key,
                        interpolate=self.config.interpolate,
                        fixed=self.config.fixed,
                        distanceToCamera=self.config.distance_to_camera,
                        scale=self.config.background_scale,
                        position=list(self.config.position),
                    ),
                    to="bgChildren",
                )

                frames_sent += 1
                now = time.perf_counter()
                if now - last_stats_time >= self.config.stats_interval_sec:
                    elapsed = now - last_stats_time
                    effective_fps = frames_sent / elapsed if elapsed > 0 else 0.0
                    self.logger.info(
                        "Vuer stats: effective_fps=%.2f output_shape=%s jpeg_quality=%d scale=%.2f rgb_only=%s",
                        effective_fps,
                        processed.output_shape,
                        self.config.jpeg_quality,
                        self.config.background_scale,
                        True,
                    )
                    frames_sent = 0
                    last_stats_time = now

                elapsed = time.perf_counter() - loop_start
                await asyncio.sleep(max(0.0, target_period - elapsed))

        self._log_open_instructions()
        self._start_vuer(app)

    def shutdown(self) -> None:
        self.frame_reader.stop()

    def _start_vuer(self, app) -> None:
        # Vuer 0.1.x prefers start(); older examples still show run().
        if hasattr(app, "start"):
            app.start()
        else:  # pragma: no cover - compatibility fallback
            app.run()

    def _log_open_instructions(self) -> None:
        local_http_url = f"http://127.0.0.1:{self.config.port}"
        vuer_browser_url = f"https://vuer.ai?ws=ws://127.0.0.1:{self.config.port}"
        self.logger.info("Local self-hosted page: %s", local_http_url)
        self.logger.info("Vuer hosted client page: %s", vuer_browser_url)
        self.logger.info(
            "For Pico later, bind to 0.0.0.0 and expose the websocket as wss://..., "
            "then open: https://vuer.ai?ws=wss://YOUR_PUBLIC_ENDPOINT"
        )
