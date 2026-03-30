from __future__ import annotations

import logging

from gear_sonic_deploy.vuer_ego_stream.config import build_arg_parser, stream_config_from_args
from gear_sonic_deploy.vuer_ego_stream.frame_source import (
    ColorSpace,
    LatestFrameReader,
    OpenCVFrameSource,
    SonicBridgeFrameSource,
)
from gear_sonic_deploy.vuer_ego_stream.vuer_app import EgoCameraVuerApp


def configure_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    config = stream_config_from_args(args)
    configure_logging(config.log_level)

    logger = logging.getLogger("vuer_ego_stream")
    logger.info("Starting Vuer ego-camera streamer with config: %s", config)

    if config.source_type == "sonic_bridge":
        source = SonicBridgeFrameSource(
            host=config.camera_host,
            port=config.camera_port,
            logger=logger,
        )
    else:
        source = OpenCVFrameSource(
            source=config.source,
            color_space=ColorSpace(config.input_color_space),
            capture_width=config.capture_width,
            capture_height=config.capture_height,
            logger=logger,
        )
    frame_reader = LatestFrameReader(
        source=source,
        stats_interval_sec=config.stats_interval_sec,
        logger=logger,
    )
    app = EgoCameraVuerApp(config=config, frame_reader=frame_reader, logger=logger)

    try:
        app.run()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, shutting down.")
    finally:
        app.shutdown()


if __name__ == "__main__":
    main()
