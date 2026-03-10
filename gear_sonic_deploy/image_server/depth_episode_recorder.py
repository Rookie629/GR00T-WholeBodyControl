#!/usr/bin/env python3
"""Record D435 RGBD frames into per-episode sidecar folders.

This recorder listens to the same `/Gr00tKeyboardListener` control messages as
the existing dataset exporter:
- `c`: start recording / stop and save current episode
- `x`: discard current episode

Frames are saved under:
  <save_root>/depth_sidecar/episode_000000/
or, if discarded:
  <save_root>/depth_sidecar_discarded/episode_000000/
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import time

import cv2
import rclpy

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from gear_sonic_deploy.sonic_data.keyboard import KeyboardListenerSubscriber

from image_client import ImageClient


class DepthEpisodeRecorder:
    def __init__(
        self,
        save_root: Path,
        image_server_ip: str,
        image_server_port: int,
    ) -> None:
        self.save_root = save_root
        self.sidecar_root = save_root / "depth_sidecar"
        self.discarded_root = save_root / "depth_sidecar_discarded"
        self.sidecar_root.mkdir(parents=True, exist_ok=True)
        self.discarded_root.mkdir(parents=True, exist_ok=True)

        self.client = ImageClient(
            image_show=False,
            server_address=image_server_ip,
            port=image_server_port,
        )

        rclpy.init(args=None)
        self.node = rclpy.create_node("depth_episode_recorder")
        self.keyboard = KeyboardListenerSubscriber()

        self.recording = False
        self.current_episode_index = self._infer_next_episode_index()
        self.current_episode_dir: Path | None = None
        self.current_meta: list[dict] = []
        self.current_frame_index = 0

    def _infer_next_episode_index(self) -> int:
        existing = sorted(self.sidecar_root.glob("episode_*"))
        discarded = sorted(self.discarded_root.glob("episode_*"))
        max_index = -1
        for path in existing + discarded:
            try:
                max_index = max(max_index, int(path.name.split("_")[-1]))
            except ValueError:
                continue

        episodes_jsonl = self.save_root / "meta" / "episodes.jsonl"
        if episodes_jsonl.exists():
            try:
                with episodes_jsonl.open("r", encoding="utf-8") as handle:
                    line_count = sum(1 for _ in handle)
                max_index = max(max_index, line_count - 1)
            except OSError:
                pass
        return max_index + 1

    def _start_episode(self) -> None:
        self.current_episode_dir = self.sidecar_root / f"episode_{self.current_episode_index:06d}.tmp"
        if self.current_episode_dir.exists():
            shutil.rmtree(self.current_episode_dir)
        self.current_episode_dir.mkdir(parents=True, exist_ok=True)
        self.current_meta = []
        self.current_frame_index = 0
        self.recording = True
        print(f"[DepthRecorder] Started episode {self.current_episode_index:06d}")

    def _finalize_episode(self, discarded: bool) -> None:
        if self.current_episode_dir is None:
            return

        final_root = self.discarded_root if discarded else self.sidecar_root
        final_dir = final_root / f"episode_{self.current_episode_index:06d}"
        if final_dir.exists():
            shutil.rmtree(final_dir)

        meta_path = self.current_episode_dir / "meta.json"
        with meta_path.open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "episode_index": self.current_episode_index,
                    "discarded": discarded,
                    "frames": self.current_meta,
                },
                handle,
                indent=2,
            )

        shutil.move(str(self.current_episode_dir), str(final_dir))
        print(
            f"[DepthRecorder] {'Discarded' if discarded else 'Saved'} "
            f"episode {self.current_episode_index:06d} -> {final_dir}"
        )

        self.current_episode_index += 1
        self.current_episode_dir = None
        self.current_meta = []
        self.current_frame_index = 0
        self.recording = False

    def _discard_in_progress(self) -> None:
        if self.current_episode_dir is None:
            return
        self._finalize_episode(discarded=True)

    def _save_in_progress(self) -> None:
        if self.current_episode_dir is None:
            return
        self._finalize_episode(discarded=False)

    def _handle_keyboard(self) -> None:
        key = self.keyboard.read_msg()
        if key == "c":
            if not self.recording:
                self._start_episode()
            else:
                self._save_in_progress()
        elif key == "x" and self.recording:
            self._discard_in_progress()

    def _record_frame(self) -> None:
        if not self.recording or self.current_episode_dir is None:
            return

        message = self.client._socket.recv()
        ts, frame_id, color, depth = self.client._decode_payload(message)
        frame_prefix = f"{self.current_frame_index:06d}"

        color_path = self.current_episode_dir / f"{frame_prefix}_color.jpg"
        cv2.imwrite(str(color_path), color)

        depth_rel = None
        if depth is not None:
            depth_path = self.current_episode_dir / f"{frame_prefix}_depth.png"
            cv2.imwrite(str(depth_path), depth)
            depth_rel = depth_path.name

        self.current_meta.append(
            {
                "frame_index": self.current_frame_index,
                "source_frame_id": int(frame_id),
                "source_timestamp": float(ts),
                "color_file": color_path.name,
                "depth_file": depth_rel,
            }
        )
        self.current_frame_index += 1

    def run(self) -> None:
        print(f"[DepthRecorder] Waiting for control on save root: {self.save_root}")
        try:
            while rclpy.ok():
                rclpy.spin_once(self.node, timeout_sec=0.01)
                self._handle_keyboard()
                if self.recording:
                    self._record_frame()
                else:
                    time.sleep(0.01)
        except KeyboardInterrupt:
            print("[DepthRecorder] stopped by user")
            if self.recording:
                self._discard_in_progress()
        finally:
            self.client._close()
            self.node.destroy_node()
            rclpy.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--save-root", required=True)
    parser.add_argument("--image-server-ip", default="127.0.0.1")
    parser.add_argument("--image-server-port", type=int, default=5555)
    args = parser.parse_args()

    recorder = DepthEpisodeRecorder(
        save_root=Path(args.save_root),
        image_server_ip=args.image_server_ip,
        image_server_port=args.image_server_port,
    )
    recorder.run()


if __name__ == "__main__":
    main()
