from __future__ import annotations

from collections import deque
from datetime import datetime
import time

import numpy as np
import rclpy

from gear_sonic_deploy.sonic_data.camera_client import ComposedCameraClientSensor
from gear_sonic_deploy.sonic_data.configs import DataExporterConfig
from gear_sonic_deploy.sonic_data.constants import BUCKET_BASE_PATH
from gear_sonic_deploy.sonic_data.dataset import (
    DataCollectionInfo,
    Gr00tDataExporter,
    get_dataset_features,
    get_modality_config,
)
from gear_sonic_deploy.sonic_data.episode_state import EpisodeState
from gear_sonic_deploy.sonic_data.g1_profile import G1DataProfile
from gear_sonic_deploy.sonic_data.keyboard import KeyboardListenerSubscriber
from gear_sonic_deploy.sonic_data.ros_utils import ROSMsgSubscriber
from gear_sonic_deploy.sonic_data.telemetry import Telemetry
from gear_sonic_deploy.sonic_data.text_to_speech import TextToSpeech
from gear_sonic_deploy.sonic_data.topics import ROBOT_CONFIG_TOPIC, STATE_TOPIC_NAME


class TimeDeltaException(Exception):
    def __init__(self, failure_count: int, reset_timeout_sec: float):
        self.failure_count = failure_count
        self.reset_timeout_sec = reset_timeout_sec
        self.message = f"{self.failure_count} failures in {self.reset_timeout_sec} seconds"
        super().__init__(self.message)


class TimingThresholdMonitor:
    def __init__(self, max_failures=3, reset_timeout_sec=5, time_delta=0.2, raise_exception=False):
        self.max_failures = max_failures
        self.reset_timeout_sec = reset_timeout_sec
        self.failure_count = 0
        self.last_failure_time = 0
        self.time_delta = time_delta
        self.raise_exception = raise_exception

    def reset(self):
        self.failure_count = 0
        self.last_failure_time = 0

    def log_time_delta(self, time_delta_sec: float):
        time_delta = abs(time_delta_sec)
        if time_delta > self.time_delta:
            self.failure_count += 1
            self.last_failure_time = time.monotonic()

        if self.is_threshold_exceeded():
            print(
                f"Time delta exception: {self.failure_count} failures in {self.reset_timeout_sec} seconds"
                f", time delta: {time_delta}"
            )
            if self.raise_exception:
                raise TimeDeltaException(self.failure_count, self.reset_timeout_sec)

    def is_threshold_exceeded(self):
        if self.failure_count >= self.max_failures:
            return True
        if time.monotonic() - self.last_failure_time > self.reset_timeout_sec:
            self.reset()
        return False


class Gr00tDataCollector:
    def __init__(
        self,
        node,
        camera_host: str,
        camera_port: int,
        state_topic_name: str,
        data_exporter: Gr00tDataExporter,
        text_to_speech=None,
        frequency=20,
        state_act_msg_frequency=50,
    ):
        self.text_to_speech = text_to_speech
        self.frequency = frequency
        self.data_exporter = data_exporter
        self.node = node

        self._episode_state = EpisodeState()
        self._keyboard_listener = KeyboardListenerSubscriber()
        self._state_subscriber = ROSMsgSubscriber(state_topic_name)
        self._image_subscriber = ComposedCameraClientSensor(
            server_ip=camera_host, port=camera_port, timeout_ms=100
        )

        self.obs_act_buffer = deque(maxlen=100)
        self.latest_image_msg = None
        self.latest_proprio_msg = None
        self._logged_first_proprio = False
        self._logged_first_image = False

        self.state_polling_rate = 1 / state_act_msg_frequency
        self.last_state_poll_time = time.monotonic()

        self.telemetry = Telemetry(window_size=100)
        self.timing_threshold_monitor = TimingThresholdMonitor()

        print(f"Recording to {self.data_exporter.meta.root}")

    def _try_set_latest_proprio(self, msg: dict | None) -> bool:
        if msg is None:
            return False

        normalized_msg = self._normalize_raw_state_message(msg)
        if normalized_msg is None:
            self._print_and_say(
                "State message missing required keys for export. "
                f"Available keys: {sorted(msg.keys())}",
                say=False,
            )
            return False

        self.latest_proprio_msg = normalized_msg
        if not self._logged_first_proprio:
            self._logged_first_proprio = True
            self._print_and_say(
                "Received first proprio message "
                f"with raw keys: {sorted(msg.keys())}",
                say=False,
            )
        return True

    @staticmethod
    def _normalize_raw_state_message(msg: dict) -> dict | None:
        if not isinstance(msg, dict):
            return None

        # Already normalized by an upstream adapter.
        if "q" in msg and "action" in msg and "timestamps" in msg:
            return msg

        required_keys = (
            "body_q",
            "left_hand_q",
            "right_hand_q",
            "last_action",
            "last_left_hand_action",
            "last_right_hand_action",
            "ros_timestamp",
        )
        if not all(key in msg for key in required_keys):
            return None

        body_q = np.asarray(msg["body_q"], dtype=np.float64)
        left_hand_q = np.asarray(msg["left_hand_q"], dtype=np.float64)
        right_hand_q = np.asarray(msg["right_hand_q"], dtype=np.float64)
        body_action = np.asarray(msg["last_action"], dtype=np.float64)
        left_hand_action = np.asarray(msg["last_left_hand_action"], dtype=np.float64)
        right_hand_action = np.asarray(msg["last_right_hand_action"], dtype=np.float64)

        if (
            body_q.shape != (29,)
            or left_hand_q.shape != (7,)
            or right_hand_q.shape != (7,)
            or body_action.shape != (29,)
            or left_hand_action.shape != (7,)
            or right_hand_action.shape != (7,)
        ):
            return None

        # Raw SONIC body order is:
        # left_leg(6), right_leg(6), waist(3), left_arm(7), right_arm(7).
        # Dataset order inserts hands between the left/right arms.
        q = np.concatenate(
            [
                body_q[:22],
                left_hand_q,
                body_q[22:29],
                right_hand_q,
            ]
        )
        action = np.concatenate(
            [
                body_action[:22],
                left_hand_action,
                body_action[22:29],
                right_hand_action,
            ]
        )

        normalized = {
            "q": q,
            "action": action,
            "wrist_pose": np.zeros(14, dtype=np.float64),
            "action.eef": np.zeros(14, dtype=np.float64),
            "navigate_command": np.zeros(3, dtype=np.float64),
            "base_height_command": 0.0,
            "timestamps": {"proprio": float(msg["ros_timestamp"])},
            "raw_state": msg,
        }
        return normalized

    @property
    def current_episode_index(self):
        return self.data_exporter.episode_buffer["episode_index"]

    def _print_and_say(self, message: str, say: bool = True):
        if self.text_to_speech is not None:
            self.text_to_speech.print_and_say(message, say)
        else:
            print(message)

    def _check_keyboard_input(self):
        key = self._keyboard_listener.read_msg()
        if key == "c":
            self._print_and_say("Received keyboard input: c", say=False)
            self._episode_state.change_state()
            if self._episode_state.get_state() == self._episode_state.RECORDING:
                self._print_and_say(f"Started recording {self.current_episode_index}")
            elif self._episode_state.get_state() == self._episode_state.NEED_TO_SAVE:
                self._print_and_say("Stopping recording, preparing to save")
            elif self._episode_state.get_state() == self._episode_state.IDLE:
                self._print_and_say("Saved episode and back to idle state")
        elif key == "x":
            self._print_and_say("Received keyboard input: x", say=False)
            if self._episode_state.get_state() == self._episode_state.RECORDING:
                self.data_exporter.save_episode_as_discarded()
                self._episode_state.reset_state()
                self._print_and_say("Discarded episode")

    def _add_data_frame(self):
        t_start = time.monotonic()

        if self.latest_proprio_msg is None or self.latest_image_msg is None:
            self._print_and_say(
                f"Waiting for message. "
                f"Avail msg: proprio {self.latest_proprio_msg is not None} | "
                f"image {self.latest_image_msg is not None}",
                say=False,
            )
            return False

        if self._episode_state.get_state() == self._episode_state.RECORDING:
            max_time_delta = 0
            for _, image_time in self.latest_image_msg["timestamps"].items():
                time_delta = abs(image_time - self.latest_proprio_msg["timestamps"]["proprio"])
                max_time_delta = max(max_time_delta, time_delta)

            self.timing_threshold_monitor.log_time_delta(max_time_delta)
            if (self.timing_threshold_monitor.failure_count + 1) % 100 == 0:
                self._print_and_say("Image state delta too high, please discard data")

            frame_data = {
                "observation.state": self.latest_proprio_msg["q"],
                "observation.eef_state": self.latest_proprio_msg["wrist_pose"],
                "action": self.latest_proprio_msg["action"],
                "action.eef": self.latest_proprio_msg["action.eef"],
                "observation.img_state_delta": np.array([max_time_delta], dtype=np.float32),
                "teleop.navigate_command": np.array(
                    self.latest_proprio_msg["navigate_command"], dtype=np.float64
                ),
                "teleop.base_height_command": np.array(
                    [self.latest_proprio_msg["base_height_command"]], dtype=np.float64
                ),
            }

            images = self.latest_image_msg["images"]
            for feature_name in self.data_exporter.features:
                if not feature_name.startswith("observation.images."):
                    continue

                image_key = feature_name.split(".")[-1]
                if image_key not in images:
                    raise ValueError(
                        f"Required image '{image_key}' for feature '{feature_name}' "
                        f"not found in image message. Available images: {list(images.keys())}"
                    )
                frame_data[feature_name] = images[image_key]

            self.data_exporter.add_frame(frame_data)

        t_end = time.monotonic()
        if t_end - t_start > (1 / self.frequency):
            print(f"DataExporter Missed: {t_end - t_start} sec")

        if self._episode_state.get_state() == self._episode_state.NEED_TO_SAVE:
            self.data_exporter.save_episode()
            self.timing_threshold_monitor.reset()
            self._print_and_say("Finished saving episode")
            self._episode_state.change_state()

        return True

    def save_and_cleanup(self):
        try:
            self._print_and_say("saving episode done")
            buffer_size = self.data_exporter.episode_buffer.get("size", 0)
            if buffer_size > 0:
                self.data_exporter.save_episode()
            self._print_and_say(f"Recording complete: {self.data_exporter.meta.root}", say=False)
        except Exception as exc:
            self._print_and_say(f"Error saving episode: {exc}")

        self.node.destroy_node()
        rclpy.shutdown()
        self._print_and_say("Shutting down data exporter...", say=False)

    def run(self):
        try:
            if self.latest_proprio_msg is None:
                startup_msg = self._state_subscriber.wait_for_msg(timeout_sec=2.0, poll_sec=0.05)
                if not self._try_set_latest_proprio(startup_msg):
                    self._print_and_say(
                        "Did not receive a usable proprio message during exporter startup.",
                        say=False,
                    )

            while rclpy.ok():
                t_start = time.monotonic()
                with self.telemetry.timer("total_loop"):
                    with self.telemetry.timer("poll_state"):
                        msg = self._state_subscriber.get_msg()
                        if msg is None and self.latest_proprio_msg is None:
                            msg = self._state_subscriber.wait_for_msg(timeout_sec=0.1, poll_sec=0.02)
                        self._try_set_latest_proprio(msg)

                    with self.telemetry.timer("poll_image"):
                        msg = self._image_subscriber.read()
                        if msg is not None:
                            self.latest_image_msg = msg
                            if not self._logged_first_image:
                                self._logged_first_image = True
                                self._print_and_say(
                                    "Received first image message "
                                    f"with image keys: {sorted(msg['images'].keys())}",
                                    say=False,
                                )

                    with self.telemetry.timer("check_keyboard"):
                        self._check_keyboard_input()

                    with self.telemetry.timer("add_frame"):
                        self._add_data_frame()

                    end_time = time.monotonic()

                target_period = 1 / self.frequency
                sleep_dt = max(0.0, target_period - (end_time - t_start))
                if sleep_dt > 0.0:
                    time.sleep(sleep_dt)
                if (end_time - t_start) > (1 / self.frequency):
                    self.telemetry.log_timing_info(
                        context="Data Exporter Loop Missed", threshold=0.001
                    )

        except KeyboardInterrupt:
            print("Data exporter terminated by user")
            buffer_size = self.data_exporter.episode_buffer.get("size", 0)
            if buffer_size > 0:
                self.data_exporter.save_episode_as_discarded()
        finally:
            self.save_and_cleanup()


def main(config: DataExporterConfig):
    rclpy.init(args=None)
    node = rclpy.create_node("data_exporter")

    g1_profile = G1DataProfile()
    dataset_features = get_dataset_features(
        g1_profile,
        add_stereo_camera=config.add_stereo_camera,
        add_depth_camera=config.add_depth_camera,
    )
    modality_config = get_modality_config(
        g1_profile,
        add_stereo_camera=config.add_stereo_camera,
        add_depth_camera=config.add_depth_camera,
    )

    text_to_speech = TextToSpeech() if config.text_to_speech else None

    if config.robot_id is not None:
        data_collection_info = DataCollectionInfo(
            teleoperator_username=config.teleoperator_username,
            support_operator_username=config.support_operator_username,
            robot_type="g1",
            robot_id=config.robot_id,
            lower_body_policy=config.lower_body_policy,
            wbc_model_path=config.wbc_model_path,
        )
    else:
        data_collection_info = DataCollectionInfo()

    robot_config_subscriber = ROSMsgSubscriber(
        ROBOT_CONFIG_TOPIC,
        transient_local=True,
        reliable=True,
    )
    robot_config = robot_config_subscriber.wait_for_msg(timeout_sec=5.0)
    if robot_config is None:
        raise RuntimeError(
            f"Timed out waiting for robot config topic '{ROBOT_CONFIG_TOPIC}'. "
            "Ensure gear_sonic_deploy is running with --output-type ros2 or all."
        )

    data_exporter = Gr00tDataExporter.create(
        save_root=f"{config.root_output_dir}/{config.dataset_name}",
        fps=config.data_collection_frequency,
        features=dataset_features,
        modality_config=modality_config,
        task=config.task_prompt,
        upload_bucket_path=BUCKET_BASE_PATH,
        data_collection_info=data_collection_info,
        script_config=robot_config,
    )

    data_collector = Gr00tDataCollector(
        node=node,
        frequency=config.data_collection_frequency,
        data_exporter=data_exporter,
        state_topic_name=STATE_TOPIC_NAME,
        camera_host=config.camera_host,
        camera_port=config.camera_port,
        text_to_speech=text_to_speech,
    )
    data_collector.run()


def prepare_interactive_config(config: DataExporterConfig) -> DataExporterConfig:
    if config.dataset_name:
        return config

    config.task_prompt = input("Enter the task prompt: ").strip().lower()
    add_to_existing_dataset = input("Add to existing dataset? (y/n): ").strip().lower()

    if add_to_existing_dataset == "y":
        config.dataset_name = input("Enter the dataset name: ").strip().lower()
    elif add_to_existing_dataset == "n":
        config.robot_id = "sim"
        config.dataset_name = f"{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}-G1-{config.robot_id}"
        config.teleoperator_username = "NEW_USER"
        config.support_operator_username = "NEW_USER"
    else:
        raise ValueError("Expected 'y' or 'n' for dataset selection prompt.")

    return config
