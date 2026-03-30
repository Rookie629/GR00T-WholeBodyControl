#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import mujoco
import mujoco.viewer
import numpy as np
import pandas as pd

from gear_sonic_deploy.sonic_data.image_utils import colorize_depth


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENE_PATH = (
    REPO_ROOT / "decoupled_wbc/control/robot_model/model_data/g1/scene_43dof.xml"
)
DEFAULT_RGB_KEY = "observation.images.ego_view"
DEFAULT_DEPTH_KEY = "observation.images.ego_view_depth"
WINDOW_NAME = "G1 RGBD Replay"


class DatasetReplayError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReplaySample:
    frame_index: int
    timestamp: float
    observation_state: np.ndarray
    rgb: np.ndarray
    depth: np.ndarray


def load_dataset_info(dataset_root: Path) -> dict[str, Any]:
    info_path = dataset_root / "meta" / "info.json"
    modality_path = dataset_root / "meta" / "modality.json"
    if not info_path.exists():
        raise FileNotFoundError(f"Dataset metadata not found: {info_path}")
    if not modality_path.exists():
        raise FileNotFoundError(f"Dataset metadata not found: {modality_path}")
    info = json.loads(info_path.read_text(encoding="utf-8"))
    json.loads(modality_path.read_text(encoding="utf-8"))
    return info


def load_episode_index(dataset_root: Path) -> pd.DataFrame:
    episode_files = sorted((dataset_root / "meta" / "episodes").glob("chunk-*/file-*.parquet"))
    if not episode_files:
        raise FileNotFoundError(
            f"No episode index parquet found under {dataset_root / 'meta' / 'episodes'}"
        )
    frames = [pd.read_parquet(path) for path in episode_files]
    return pd.concat(frames, ignore_index=True)


def load_data_file(dataset_root: Path, chunk_index: int, file_index: int) -> pd.DataFrame:
    path = dataset_root / "data" / f"chunk-{chunk_index:03d}" / f"file-{file_index:03d}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Data parquet not found: {path}")
    return pd.read_parquet(path)


def build_video_path(
    dataset_root: Path, info: dict[str, Any], video_key: str, chunk_index: int, file_index: int
) -> Path:
    template = info.get("video_path")
    if template:
        return dataset_root / template.format(
            video_key=video_key,
            chunk_index=int(chunk_index),
            file_index=int(file_index),
        )
    return (
        dataset_root
        / "videos"
        / video_key
        / f"chunk-{chunk_index:03d}"
        / f"file-{file_index:03d}.mp4"
    )


def coerce_depth_image(value: Any) -> np.ndarray:
    if isinstance(value, np.ndarray):
        if value.ndim == 2 and value.dtype != object:
            return value.astype(np.uint16, copy=False)
        if value.ndim == 1 and value.dtype == object:
            return np.stack([np.asarray(row, dtype=np.uint16) for row in value], axis=0)
    array = np.asarray(value)
    if array.ndim == 2:
        return array.astype(np.uint16, copy=False)
    if array.ndim == 1 and array.dtype == object:
        return np.stack([np.asarray(row, dtype=np.uint16) for row in array], axis=0)
    raise DatasetReplayError(f"Unsupported depth payload shape: {array.shape}, dtype={array.dtype}")


def summarize_joint_layout(joint_names: list[str]) -> tuple[int, int, int]:
    left_hand = sum(name.startswith("left_hand_") for name in joint_names)
    right_hand = sum(name.startswith("right_hand_") for name in joint_names)
    body = len(joint_names) - left_hand - right_hand
    return body, left_hand, right_hand


class EpisodeVideoReader:
    def __init__(self, video_path: Path, start_frame: int, frame_count: int):
        self.video_path = video_path
        self.start_frame = start_frame
        self.frame_count = frame_count
        self.cap = cv2.VideoCapture(str(video_path))
        if not self.cap.isOpened():
            raise DatasetReplayError(f"Failed to open RGB video: {video_path}")

        self.actual_frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if self.actual_frame_count < self.start_frame + self.frame_count:
            raise DatasetReplayError(
                f"RGB video {video_path} has {self.actual_frame_count} frames, "
                f"but replay requires frames [{self.start_frame}, {self.start_frame + self.frame_count})."
            )
        self._next_absolute_frame = 0

    def read_rgb_frame(self, local_frame_index: int) -> np.ndarray:
        if local_frame_index < 0 or local_frame_index >= self.frame_count:
            raise IndexError(
                f"Frame {local_frame_index} out of range for video of length {self.frame_count}"
            )

        absolute_frame = self.start_frame + local_frame_index
        if absolute_frame != self._next_absolute_frame:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, absolute_frame)
            self._next_absolute_frame = absolute_frame

        ok, frame_bgr = self.cap.read()
        if not ok or frame_bgr is None:
            raise DatasetReplayError(
                f"Failed to decode frame {absolute_frame} from RGB video {self.video_path}"
            )

        self._next_absolute_frame = absolute_frame + 1
        return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

    def close(self) -> None:
        self.cap.release()


class DatasetEpisodeReader:
    def __init__(
        self,
        dataset_root: str | Path,
        episode_index: int = 0,
        rgb_key: str = DEFAULT_RGB_KEY,
        depth_key: str = DEFAULT_DEPTH_KEY,
    ):
        self.dataset_root = Path(dataset_root).expanduser().resolve()
        if not self.dataset_root.exists():
            raise FileNotFoundError(f"Dataset root does not exist: {self.dataset_root}")

        self.rgb_key = rgb_key
        self.depth_key = depth_key
        self.info = load_dataset_info(self.dataset_root)
        self.fps = float(self.info["fps"])
        self.episode_df = load_episode_index(self.dataset_root)
        self.episode_row = self._select_episode_row(episode_index)
        self.episode_index = int(self.episode_row["episode_index"])
        self.length = int(self.episode_row["length"])

        features = self.info["features"]
        if "observation.state" not in features:
            raise DatasetReplayError("Dataset is missing observation.state in meta/info.json")
        if self.depth_key not in features:
            raise DatasetReplayError(f"Dataset is missing {self.depth_key} in meta/info.json")
        self.joint_names = list(features["observation.state"]["names"])

        data_chunk_index = int(self.episode_row["data/chunk_index"])
        data_file_index = int(self.episode_row["data/file_index"])
        data_df = load_data_file(self.dataset_root, data_chunk_index, data_file_index)
        self.data_df = self._select_episode_frames_from_data_file(data_df)

        video_chunk_index = int(self.episode_row[f"videos/{self.rgb_key}/chunk_index"])
        video_file_index = int(self.episode_row[f"videos/{self.rgb_key}/file_index"])
        self.video_path = build_video_path(
            self.dataset_root,
            self.info,
            self.rgb_key,
            video_chunk_index,
            video_file_index,
        )
        if not self.video_path.exists():
            raise FileNotFoundError(f"RGB video not found: {self.video_path}")

        from_timestamp = float(self.episode_row[f"videos/{self.rgb_key}/from_timestamp"])
        to_timestamp = float(self.episode_row[f"videos/{self.rgb_key}/to_timestamp"])
        self.video_start_frame = int(round(from_timestamp * self.fps))
        self.video_end_frame = int(round(to_timestamp * self.fps)) + 1
        self.video_frame_count = self.video_end_frame - self.video_start_frame

        if len(self.data_df) != self.length:
            raise DatasetReplayError(
                f"Episode {self.episode_index} expected {self.length} parquet rows, found {len(self.data_df)}"
            )
        if self.video_frame_count != self.length:
            raise DatasetReplayError(
                f"Episode {self.episode_index} expected {self.length} RGB frames from metadata, "
                f"found {self.video_frame_count}"
            )

        self.video_reader = EpisodeVideoReader(
            video_path=self.video_path,
            start_frame=self.video_start_frame,
            frame_count=self.video_frame_count,
        )
        if self.video_start_frame != 0 or self.video_reader.actual_frame_count != self.video_frame_count:
            raise DatasetReplayError(
                "Replay currently expects one RGB video shard per episode. "
                f"Episode {self.episode_index} maps to frames [{self.video_start_frame}, "
                f"{self.video_end_frame}) inside a video with "
                f"{self.video_reader.actual_frame_count} total frames."
            )

    def _select_episode_row(self, episode_index: int) -> pd.Series:
        row = self.episode_df.loc[self.episode_df["episode_index"] == episode_index]
        if row.empty:
            available = self.episode_df["episode_index"].tolist()
            raise DatasetReplayError(
                f"Episode {episode_index} not found under {self.dataset_root}. Available episodes: {available}"
            )
        return row.iloc[0]

    def _select_episode_frames_from_data_file(self, data_df: pd.DataFrame) -> pd.DataFrame:
        # Prefer filtering by episode index. This works for both one-episode-per-file
        # layouts and multi-episode shared parquet shards.
        if "episode_index" in data_df.columns:
            episode_df = data_df.loc[data_df["episode_index"] == self.episode_index].reset_index(
                drop=True
            )
            if len(episode_df) == self.length:
                return episode_df

        # Fall back to the global dataset index range recorded in meta/episodes.
        dataset_from_index = int(self.episode_row.get("dataset_from_index", 0))
        dataset_to_index = int(self.episode_row.get("dataset_to_index", dataset_from_index))
        expected_length = dataset_to_index - dataset_from_index
        if expected_length != self.length:
            raise DatasetReplayError(
                f"Episode {self.episode_index} metadata length mismatch: "
                f"length={self.length}, dataset range=[{dataset_from_index}, {dataset_to_index})"
            )

        if "index" in data_df.columns:
            episode_df = data_df.loc[
                (data_df["index"] >= dataset_from_index) & (data_df["index"] < dataset_to_index)
            ].reset_index(drop=True)
            if len(episode_df) == self.length:
                return episode_df

        # Last-resort fallback for parquet files that store only the current episode.
        if len(data_df) == self.length:
            return data_df.reset_index(drop=True)

        raise DatasetReplayError(
            f"Episode {self.episode_index} expected {self.length} parquet rows, found {len(data_df)}"
        )

    def get_sample(self, frame_index: int) -> ReplaySample:
        if frame_index < 0 or frame_index >= self.length:
            raise IndexError(f"Frame {frame_index} out of range for episode length {self.length}")

        row = self.data_df.iloc[frame_index]
        observation_state = np.asarray(row["observation.state"], dtype=np.float64)
        if observation_state.shape != (len(self.joint_names),):
            raise DatasetReplayError(
                f"Unexpected observation.state shape {observation_state.shape}; "
                f"expected {(len(self.joint_names),)}"
            )

        return ReplaySample(
            frame_index=int(row["frame_index"]),
            timestamp=float(row["timestamp"]),
            observation_state=observation_state,
            rgb=self.video_reader.read_rgb_frame(frame_index),
            depth=coerce_depth_image(row[self.depth_key]),
        )

    def close(self) -> None:
        self.video_reader.close()


def build_mujoco_joint_mapping(model: mujoco.MjModel, joint_names: list[str]) -> np.ndarray:
    qpos_indices = []
    for joint_name in joint_names:
        joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
        if joint_id < 0:
            raise DatasetReplayError(f"Joint {joint_name!r} not found in MuJoCo model")
        qpos_indices.append(int(model.jnt_qposadr[joint_id]))
    return np.asarray(qpos_indices, dtype=np.int32)


class MujocoReplayModel:
    def __init__(self, scene_path: str | Path, joint_names: list[str]):
        self.scene_path = Path(scene_path).expanduser().resolve()
        if not self.scene_path.exists():
            raise FileNotFoundError(f"MuJoCo scene does not exist: {self.scene_path}")
        self.model = mujoco.MjModel.from_xml_path(str(self.scene_path))
        self.data = mujoco.MjData(self.model)
        self.default_qpos = self.data.qpos.copy()
        self.default_qvel = self.data.qvel.copy()
        self.qpos_indices = build_mujoco_joint_mapping(self.model, joint_names)

    def set_joint_state(self, joint_positions: np.ndarray) -> None:
        if joint_positions.shape != (len(self.qpos_indices),):
            raise ValueError(
                f"Expected joint_positions shape {(len(self.qpos_indices),)}, got {joint_positions.shape}"
            )
        self.data.qpos[:] = self.default_qpos
        self.data.qvel[:] = self.default_qvel
        self.data.qpos[self.qpos_indices] = joint_positions
        mujoco.mj_forward(self.model, self.data)


def compose_preview(
    sample: ReplaySample,
    *,
    episode_index: int,
    playback_fps: float,
    speed: float,
    max_depth_mm: int,
) -> np.ndarray:
    rgb_bgr = cv2.cvtColor(sample.rgb, cv2.COLOR_RGB2BGR)
    depth_bgr = colorize_depth(sample.depth, max_depth_mm)
    if depth_bgr.shape[:2] != rgb_bgr.shape[:2]:
        depth_bgr = cv2.resize(depth_bgr, (rgb_bgr.shape[1], rgb_bgr.shape[0]))
    canvas = np.concatenate([rgb_bgr, depth_bgr], axis=1)

    lines = [
        f"episode={episode_index} frame={sample.frame_index}",
        f"timestamp={sample.timestamp:.3f}s fps={playback_fps:.2f} speed={speed:.2f}x",
        "keys: space pause | , prev | . next | r reset | q quit",
    ]
    for idx, line in enumerate(lines):
        y = 30 + idx * 30
        cv2.putText(
            canvas,
            line,
            (20, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 0),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            line,
            (20, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return canvas


def clamp_frame(frame_index: int, start_frame: int, end_frame: int) -> int:
    return max(start_frame, min(end_frame, frame_index))


def run_replay(args: argparse.Namespace) -> None:
    reader = DatasetEpisodeReader(
        dataset_root=args.dataset_root,
        episode_index=args.episode,
        rgb_key=args.rgb_key,
        depth_key=args.depth_key,
    )
    player = MujocoReplayModel(scene_path=args.scene_path, joint_names=reader.joint_names)

    body_count, left_hand_count, right_hand_count = summarize_joint_layout(reader.joint_names)
    if (body_count, left_hand_count, right_hand_count) != (29, 7, 7):
        raise DatasetReplayError(
            "Unexpected joint layout for observation.state. "
            f"Expected (29, 7, 7), got {(body_count, left_hand_count, right_hand_count)}"
        )

    start_frame = clamp_frame(args.start_frame, 0, reader.length - 1)
    end_frame = (
        reader.length - 1
        if args.end_frame is None
        else clamp_frame(args.end_frame, 0, reader.length - 1)
    )
    if start_frame > end_frame:
        raise DatasetReplayError(
            f"Invalid frame range: start_frame={start_frame} is greater than end_frame={end_frame}"
        )

    playback_fps = float(args.fps) if args.fps is not None else reader.fps
    if playback_fps <= 0:
        raise DatasetReplayError(f"Playback fps must be positive, got {playback_fps}")
    if args.speed <= 0:
        raise DatasetReplayError(f"Playback speed must be positive, got {args.speed}")

    frame_period = 1.0 / (playback_fps * args.speed)
    current_frame = start_frame
    paused = False
    needs_redraw = True
    next_tick = time.monotonic()

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    try:
        with mujoco.viewer.launch_passive(
            player.model,
            player.data,
            show_left_ui=False,
            show_right_ui=False,
        ) as viewer:
            viewer.cam.azimuth = 120
            viewer.cam.elevation = -25
            viewer.cam.distance = 2.5
            viewer.cam.lookat = np.array([0.0, 0.0, 0.6])

            while viewer.is_running():
                if needs_redraw:
                    sample = reader.get_sample(current_frame)
                    player.set_joint_state(sample.observation_state)
                    viewer.sync()
                    cv2.imshow(
                        WINDOW_NAME,
                        compose_preview(
                            sample,
                            episode_index=reader.episode_index,
                            playback_fps=playback_fps,
                            speed=args.speed,
                            max_depth_mm=args.max_depth_mm,
                        ),
                    )
                    needs_redraw = False
                else:
                    viewer.sync()

                if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                    break

                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord(" "):
                    paused = not paused
                    next_tick = time.monotonic() + frame_period
                elif key == ord(","):
                    paused = True
                    current_frame = clamp_frame(current_frame - 1, start_frame, end_frame)
                    needs_redraw = True
                elif key == ord("."):
                    paused = True
                    current_frame = clamp_frame(current_frame + 1, start_frame, end_frame)
                    needs_redraw = True
                elif key == ord("r"):
                    current_frame = start_frame
                    needs_redraw = True
                    next_tick = time.monotonic() + frame_period

                if paused:
                    continue

                now = time.monotonic()
                if now < next_tick:
                    continue

                if current_frame < end_frame:
                    current_frame += 1
                    needs_redraw = True
                    next_tick += frame_period
                    if next_tick < now - frame_period:
                        next_tick = now + frame_period
                    continue

                if args.loop:
                    current_frame = start_frame
                    needs_redraw = True
                    next_tick = now + frame_period
                else:
                    paused = True
    finally:
        reader.close()
        cv2.destroyAllWindows()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay a G1 RGBD dataset episode with synchronized MuJoCo and RGBD views."
    )
    parser.add_argument("--dataset-root", required=True, help="Path to outputs/g1_rgbd/<dataset>")
    parser.add_argument("--episode", type=int, default=0, help="Episode index to replay")
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier")
    parser.add_argument("--fps", type=float, default=None, help="Override playback fps")
    parser.add_argument("--start-frame", type=int, default=0, help="Episode-local start frame")
    parser.add_argument("--end-frame", type=int, default=None, help="Episode-local end frame")
    parser.add_argument("--loop", action="store_true", help="Loop between start and end frames")
    parser.add_argument(
        "--scene-path",
        default=str(DEFAULT_SCENE_PATH),
        help="MuJoCo scene xml. Defaults to scene_43dof.xml",
    )
    parser.add_argument("--rgb-key", default=DEFAULT_RGB_KEY, help="RGB video feature key")
    parser.add_argument("--depth-key", default=DEFAULT_DEPTH_KEY, help="Depth feature key")
    parser.add_argument(
        "--max-depth-mm",
        type=int,
        default=3000,
        help="Max depth for pseudo-color visualization",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    run_replay(parser.parse_args())


if __name__ == "__main__":
    main()
