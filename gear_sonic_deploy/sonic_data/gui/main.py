#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import pprint
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import scrolledtext, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

repo_root = Path(__file__).resolve().parents[3]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from gear_sonic_deploy.sonic_data.camera_client import ComposedCameraClientSensor
from gear_sonic_deploy.sonic_data.image_utils import colorize_depth
from gear_sonic_deploy.sonic_data.keyboard import KeyboardListenerPublisher
from gear_sonic_deploy.sonic_data.ros_utils import ROSManager, ROSMsgSubscriber
from gear_sonic_deploy.sonic_data.topics import STATE_TOPIC_NAME
from gear_sonic_deploy.sonic_data.gui.process_manager import ManagedProcess


class StreamWorker(threading.Thread):
    def __init__(self, host: str, port: int, event_queue: queue.Queue, max_depth_mm: int = 3000):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.max_depth_mm = max_depth_mm
        self.event_queue = event_queue
        self._stop_event = threading.Event()

    def update_endpoint(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        ROSManager()
        camera = ComposedCameraClientSensor(server_ip=self.host, port=self.port, timeout_ms=100)
        state_sub = ROSMsgSubscriber(STATE_TOPIC_NAME)

        latest_state = None
        image_count = 0
        state_count = 0
        image_hz = 0.0
        state_hz = 0.0
        stats_t0 = time.monotonic()

        try:
            while not self._stop_event.is_set() and ROSManager.ok():
                image_msg = camera.read()
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

                if image_msg is None:
                    continue

                image_count += 1
                images = image_msg["images"]
                if "ego_view" not in images:
                    self.event_queue.put(
                        ("log", "stream", f"Missing ego_view. Available: {sorted(images.keys())}")
                    )
                    continue

                color_bgr = cv2.cvtColor(images["ego_view"], cv2.COLOR_RGB2BGR)
                depth_bgr = None
                if "ego_view_depth" in images:
                    depth_bgr = colorize_depth(images["ego_view_depth"], self.max_depth_mm)
                    if depth_bgr.shape[:2] != color_bgr.shape[:2]:
                        depth_bgr = cv2.resize(depth_bgr, (color_bgr.shape[1], color_bgr.shape[0]))

                payload = {
                    "color_bgr": color_bgr,
                    "depth_bgr": depth_bgr,
                    "timestamps": image_msg["timestamps"],
                    "state": latest_state,
                    "camera_hz": image_hz,
                    "state_hz": state_hz,
                    "image_keys": sorted(images.keys()),
                }
                self.event_queue.put(("frame", payload))
        except Exception as exc:
            self.event_queue.put(("log", "stream", str(exc)))
        finally:
            camera.close()


class MainWindow:
    def __init__(self) -> None:
        ROSManager()
        self.keyboard_pub = KeyboardListenerPublisher()
        self.repo_root = repo_root
        self.event_queue: queue.Queue = queue.Queue()

        self.root = tk.Tk()
        self.root.title("Sonic Data Collection")
        self.root.geometry("1520x920")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.bridge_status = tk.StringVar(value="bridge: stopped")
        self.exporter_status = tk.StringVar(value="exporter: stopped")
        self.camera_status = tk.StringVar(value="camera_hz=0.0")
        self.state_status = tk.StringVar(value="state_hz=0.0")
        self.info_status = tk.StringVar(value="state: waiting")

        self.g1_ip = tk.StringVar(value="192.168.123.164")
        self.image_server_port = tk.IntVar(value=5555)
        self.bridge_output_port = tk.IntVar(value=5560)
        self.dataset_name = tk.StringVar()
        self.task_prompt = tk.StringVar(value="demo")
        self.root_output_dir = tk.StringVar(value="outputs/g1_rgbd")
        self.frequency = tk.IntVar(value=20)
        self.add_depth = tk.BooleanVar(value=True)
        self.add_stereo = tk.BooleanVar(value=False)

        self.bridge_process = ManagedProcess(
            "bridge",
            on_output=self.enqueue_log,
            on_state_change=self.enqueue_state,
        )
        self.exporter_process = ManagedProcess(
            "exporter",
            on_output=self.enqueue_log,
            on_state_change=self.enqueue_state,
        )
        self.raw_test_process = ManagedProcess(
            "raw-test",
            on_output=self.enqueue_log,
            on_state_change=self.enqueue_state,
        )
        self.bridge_test_process = ManagedProcess(
            "bridge-test",
            on_output=self.enqueue_log,
            on_state_change=self.enqueue_state,
        )
        self.proprio_test_process = ManagedProcess(
            "proprio-test",
            on_output=self.enqueue_log,
            on_state_change=self.enqueue_state,
        )

        self.rgb_photo = None
        self.depth_photo = None
        self._recording_toggle = False
        self._latest_state = None
        self._first_state = None

        self._build_ui()

        self.stream_worker = StreamWorker("127.0.0.1", self.bridge_output_port.get(), self.event_queue)
        self.stream_worker.start()
        self.root.after(50, self.poll_events)

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        controls = ttk.LabelFrame(main, text="Collector")
        controls.pack(fill=tk.X)

        ttk.Label(controls, text="G1 IP").grid(row=0, column=0, sticky=tk.W, padx=4, pady=4)
        ttk.Entry(controls, textvariable=self.g1_ip, width=18).grid(row=0, column=1, padx=4, pady=4)
        ttk.Label(controls, text="Raw Port").grid(row=0, column=2, sticky=tk.W, padx=4, pady=4)
        ttk.Spinbox(controls, from_=1, to=65535, textvariable=self.image_server_port, width=8).grid(
            row=0, column=3, padx=4, pady=4
        )
        ttk.Label(controls, text="Bridge Port").grid(row=0, column=4, sticky=tk.W, padx=4, pady=4)
        ttk.Spinbox(controls, from_=1, to=65535, textvariable=self.bridge_output_port, width=8).grid(
            row=0, column=5, padx=4, pady=4
        )
        ttk.Label(controls, text="Hz").grid(row=0, column=6, sticky=tk.W, padx=4, pady=4)
        ttk.Spinbox(controls, from_=1, to=200, textvariable=self.frequency, width=8).grid(
            row=0, column=7, padx=4, pady=4
        )

        ttk.Label(controls, text="Dataset").grid(row=1, column=0, sticky=tk.W, padx=4, pady=4)
        ttk.Entry(controls, textvariable=self.dataset_name, width=36).grid(
            row=1, column=1, columnspan=3, sticky=tk.EW, padx=4, pady=4
        )
        ttk.Label(controls, text="Task").grid(row=1, column=4, sticky=tk.W, padx=4, pady=4)
        ttk.Entry(controls, textvariable=self.task_prompt, width=28).grid(
            row=1, column=5, columnspan=3, sticky=tk.EW, padx=4, pady=4
        )

        ttk.Label(controls, text="Output Dir").grid(row=2, column=0, sticky=tk.W, padx=4, pady=4)
        ttk.Entry(controls, textvariable=self.root_output_dir, width=72).grid(
            row=2, column=1, columnspan=5, sticky=tk.EW, padx=4, pady=4
        )
        ttk.Checkbutton(controls, text="Depth", variable=self.add_depth).grid(row=2, column=6, padx=4, pady=4)
        ttk.Checkbutton(controls, text="Stereo", variable=self.add_stereo).grid(row=2, column=7, padx=4, pady=4)

        button_row = ttk.Frame(main)
        button_row.pack(fill=tk.X, pady=(10, 6))
        buttons = [
            ("Start Bridge", self.start_bridge),
            ("Stop Bridge", lambda: self.bridge_process.stop()),
            ("Start Exporter", self.start_exporter),
            ("Stop Exporter", lambda: self.exporter_process.stop()),
            ("Start All", self.start_all),
            ("Record / Stop Save", self.toggle_record),
            ("Discard", self.discard_episode),
            ("Print State", self.print_state_snapshot),
            ("Test Proprio", self.open_proprio_test),
            ("Open Raw Test", self.open_raw_test),
            ("Open Bridge Test", self.open_bridge_test),
        ]
        for label, command in buttons:
            ttk.Button(button_row, text=label, command=command).pack(side=tk.LEFT, padx=4)

        status_row = ttk.Frame(main)
        status_row.pack(fill=tk.X, pady=(0, 8))
        for variable in (
            self.bridge_status,
            self.exporter_status,
            self.camera_status,
            self.state_status,
            self.info_status,
        ):
            ttk.Label(status_row, textvariable=variable).pack(side=tk.LEFT, padx=8)

        preview_row = ttk.Frame(main)
        preview_row.pack(fill=tk.BOTH, expand=False)
        self.rgb_label = ttk.Label(preview_row, text="RGB preview", anchor=tk.CENTER)
        self.rgb_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.depth_label = ttk.Label(preview_row, text="Depth preview", anchor=tk.CENTER)
        self.depth_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)

        self.log_box = scrolledtext.ScrolledText(main, wrap=tk.WORD, height=20)
        self.log_box.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.log_box.configure(state=tk.DISABLED)

    def enqueue_log(self, source: str, payload: str) -> None:
        self.event_queue.put(("log", source, payload))

    def enqueue_state(self, source: str, state: str) -> None:
        self.event_queue.put(("state", source, state))

    def append_log(self, source: str, payload: str) -> None:
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.insert(tk.END, f"[{source}] {payload}\n")
        self.log_box.see(tk.END)
        self.log_box.configure(state=tk.DISABLED)

    def start_bridge(self) -> None:
        self.stream_worker.update_endpoint("127.0.0.1", self.bridge_output_port.get())
        args = [
            str(self.repo_root / "gear_sonic_deploy/image_server/composed_camera_bridge.py"),
            "--image-server-ip",
            self.g1_ip.get().strip(),
            "--image-server-port",
            str(self.image_server_port.get()),
            "--output-port",
            str(self.bridge_output_port.get()),
        ]
        if self.add_depth.get():
            args.append("--include-depth")
        self._log_launch_context("bridge", args)
        self.bridge_process.start(sys.executable, args, cwd=self.repo_root)

    def _resolved_dataset_name(self) -> str:
        dataset_name = self.dataset_name.get().strip()
        if dataset_name:
            return dataset_name
        auto_name = datetime.now().strftime("%Y-%m-%d-%H-%M-%S-g1")
        self.dataset_name.set(auto_name)
        return auto_name

    def start_exporter(self) -> None:
        args = [
            str(self.repo_root / "gear_sonic_deploy/sonic_data/run_g1_data_exporter.py"),
            "--camera_host",
            "127.0.0.1",
            "--camera_port",
            str(self.bridge_output_port.get()),
            "--data_collection_frequency",
            str(self.frequency.get()),
            "--root_output_dir",
            self.root_output_dir.get().strip(),
            "--dataset_name",
            self._resolved_dataset_name(),
            "--task_prompt",
            self.task_prompt.get().strip(),
        ]
        if self.add_stereo.get():
            args.append("--add_stereo_camera")
        else:
            args.append("--no-add_stereo_camera")
        if self.add_depth.get():
            args.append("--add_depth_camera")
        self._log_launch_context("exporter", args)
        self.exporter_process.start(sys.executable, args, cwd=self.repo_root)

    def start_all(self) -> None:
        self.start_bridge()
        self.root.after(500, self.start_exporter)

    def _publish_keyboard_command(self, key: str, repeats: int = 1, spacing_ms: int = 250) -> None:
        for index in range(repeats):
            self.root.after(index * spacing_ms, lambda value=key: self.keyboard_pub.publish(value))
        self.append_log("gui", f"published /Gr00tKeyboardListener='{key}' x{repeats}")

    def toggle_record(self) -> None:
        if not self.exporter_process.is_running():
            self.append_log("gui", "exporter is not running; record command still published")
        self._publish_keyboard_command("c")
        self._recording_toggle = not self._recording_toggle
        self.info_status.set("state: recording" if self._recording_toggle else "state: saving")

    def discard_episode(self) -> None:
        self._publish_keyboard_command("x")
        self._recording_toggle = False
        self.info_status.set("state: discarded")

    def print_state_snapshot(self) -> None:
        if self._first_state is None and self._latest_state is None:
            self.append_log("gui", "no robot state received yet")
            return

        if self._first_state is not None:
            self.append_log("gui", "first state frame:")
            self.append_log("gui", pprint.pformat(self._first_state, sort_dicts=False))

        if self._latest_state is not None:
            self.append_log("gui", "latest state frame:")
            self.append_log("gui", pprint.pformat(self._latest_state, sort_dicts=False))

    def open_raw_test(self) -> None:
        args = [
            str(self.repo_root / "gear_sonic_deploy/image_server/image_client.py"),
            "--ip",
            self.g1_ip.get().strip(),
            "--port",
            str(self.image_server_port.get()),
        ]
        self.raw_test_process.start_detached(sys.executable, args, cwd=self.repo_root)

    def open_bridge_test(self) -> None:
        args = [
            str(self.repo_root / "gear_sonic_deploy/image_server/stream_smoke_test.py"),
            "--camera-host",
            "127.0.0.1",
            "--camera-port",
            str(self.bridge_output_port.get()),
        ]
        self.bridge_test_process.start_detached(sys.executable, args, cwd=self.repo_root)

    def open_proprio_test(self) -> None:
        args = [
            str(self.repo_root / "gear_sonic_deploy/image_server/print_robot_state.py"),
            "--once",
        ]
        self._log_launch_context("proprio-test", args)
        self.proprio_test_process.start(sys.executable, args, cwd=self.repo_root)

    def _log_launch_context(self, name: str, args: list[str]) -> None:
        command = " ".join([sys.executable, *args])
        env_summary = {
            key: os.environ.get(key, "")
            for key in (
                "ROS_DOMAIN_ID",
                "RMW_IMPLEMENTATION",
                "CYCLONEDDS_URI",
                "AMENT_PREFIX_PATH",
                "PYTHONPATH",
            )
            if os.environ.get(key)
        }
        self.append_log("gui", f"starting {name}: {command}")
        self.append_log("gui", f"{name} env: {env_summary if env_summary else '{}'}")

    def _to_photo(self, image_bgr: np.ndarray, width: int = 480) -> ImageTk.PhotoImage:
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        aspect = image.height / image.width
        image = image.resize((width, int(width * aspect)))
        return ImageTk.PhotoImage(image)

    def update_preview(self, payload: dict) -> None:
        self.camera_status.set(f"camera_hz={payload['camera_hz']:.1f}")
        self.state_status.set(f"state_hz={payload['state_hz']:.1f}")

        image_keys = ",".join(payload["image_keys"])
        state = payload["state"]
        if state is None:
            self.info_status.set(f"state: waiting | image_keys={image_keys}")
        else:
            self._latest_state = state
            if self._first_state is None:
                self._first_state = state
            q_dim = len(state.get("q", []))
            action_dim = len(state.get("action", []))
            navigate = state.get("navigate_command")
            self.info_status.set(
                f"image_keys={image_keys} | q_dim={q_dim} | action_dim={action_dim} | navigate={navigate}"
            )

        self.rgb_photo = self._to_photo(payload["color_bgr"])
        self.rgb_label.configure(image=self.rgb_photo, text="")

        depth_bgr = payload["depth_bgr"]
        if depth_bgr is not None:
            self.depth_photo = self._to_photo(depth_bgr)
            self.depth_label.configure(image=self.depth_photo, text="")
        else:
            self.depth_label.configure(image="", text="Depth preview unavailable")

    def poll_events(self) -> None:
        try:
            while True:
                event = self.event_queue.get_nowait()
                kind = event[0]
                if kind == "log":
                    _, source, payload = event
                    self.append_log(source, payload)
                elif kind == "state":
                    _, source, state = event
                    if source == "bridge":
                        self.bridge_status.set(f"bridge: {state}")
                    elif source == "exporter":
                        self.exporter_status.set(f"exporter: {state}")
                    self.append_log(source, f"state -> {state}")
                elif kind == "frame":
                    _, payload = event
                    self.update_preview(payload)
        except queue.Empty:
            pass
        self.root.after(50, self.poll_events)

    def on_close(self) -> None:
        self.stream_worker.stop()
        self.bridge_process.stop()
        self.exporter_process.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    MainWindow().run()


if __name__ == "__main__":
    main()
