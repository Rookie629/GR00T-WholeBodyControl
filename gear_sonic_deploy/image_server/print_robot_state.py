#!/usr/bin/env python3
"""Print decoded robot state messages from the ROS2 msgpack topic."""

from __future__ import annotations

import argparse
from pathlib import Path
import pprint
import sys
import time

import numpy as np

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from gear_sonic_deploy.sonic_data.ros_utils import ROSManager, ROSMsgSubscriber
from gear_sonic_deploy.sonic_data.topics import ROBOT_CONFIG_TOPIC, STATE_TOPIC_NAME


def summarize_value(value):
    if isinstance(value, np.ndarray):
        flat = value.reshape(-1)
        preview = flat[: min(6, flat.size)].tolist()
        return {
            "shape": tuple(value.shape),
            "dtype": str(value.dtype),
            "preview": preview,
        }
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default=STATE_TOPIC_NAME)
    parser.add_argument("--full", action="store_true", help="Print full decoded message")
    parser.add_argument("--once", action="store_true", help="Exit after first decoded message")
    parser.add_argument(
        "--show-config",
        action="store_true",
        help=f"Fetch and print {ROBOT_CONFIG_TOPIC} once before subscribing",
    )
    args = parser.parse_args()

    if args.show_config:
        config_subscriber = ROSMsgSubscriber(
            ROBOT_CONFIG_TOPIC,
            transient_local=True,
            reliable=True,
        )
        config = config_subscriber.wait_for_msg(timeout_sec=5.0)
        if config is None:
            raise RuntimeError(f"Timed out waiting for topic {ROBOT_CONFIG_TOPIC}")
        print("robot_config:")
        pprint.pprint(config, sort_dicts=False)

    subscriber = ROSMsgSubscriber(args.topic)
    print(f"subscribed to {args.topic}")

    try:
        while ROSManager.ok():
            msg = subscriber.get_msg()
            if msg is None:
                time.sleep(0.05)
                continue

            if args.full:
                pprint.pprint(msg, sort_dicts=False)
            else:
                summary = {key: summarize_value(value) for key, value in msg.items()}
                pprint.pprint(summary, sort_dicts=False)
            print("-" * 80)

            if args.once:
                break
    except KeyboardInterrupt:
        pass
    finally:
        ROSManager.shutdown()


if __name__ == "__main__":
    main()
