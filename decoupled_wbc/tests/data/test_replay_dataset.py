from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("cv2")
pytest.importorskip("mujoco")
pytest.importorskip("pandas")

from gear_sonic_deploy.sonic_data.replay_dataset import (
    DEFAULT_SCENE_PATH,
    DatasetEpisodeReader,
    MujocoReplayModel,
    summarize_joint_layout,
)


@pytest.fixture
def sample_dataset_root() -> Path:
    dataset_root = (
        Path(__file__).resolve().parents[3]
        / "outputs/g1_rgbd/2026-03-16-13-41-29-g1"
    )
    if not dataset_root.exists():
        pytest.skip(f"Sample dataset not found: {dataset_root}")
    return dataset_root


def test_episode_reader_parses_sample_dataset(sample_dataset_root: Path):
    reader = DatasetEpisodeReader(sample_dataset_root, episode_index=0)
    try:
        assert reader.episode_index == 0
        assert reader.length == 60
        assert reader.fps == pytest.approx(20.0)
        assert reader.video_path.exists()
    finally:
        reader.close()


def test_episode_reader_returns_rgb_and_depth_frames(sample_dataset_root: Path):
    reader = DatasetEpisodeReader(sample_dataset_root, episode_index=0)
    try:
        sample = reader.get_sample(0)
        assert sample.frame_index == 0
        assert sample.rgb.shape == (480, 640, 3)
        assert sample.depth.shape == (480, 640)
        assert sample.depth.dtype == np.uint16
        assert sample.observation_state.shape == (43,)
    finally:
        reader.close()


def test_mujoco_mapping_matches_observation_state(sample_dataset_root: Path):
    reader = DatasetEpisodeReader(sample_dataset_root, episode_index=0)
    try:
        model = MujocoReplayModel(DEFAULT_SCENE_PATH, reader.joint_names)
        body_count, left_hand_count, right_hand_count = summarize_joint_layout(reader.joint_names)
        assert (body_count, left_hand_count, right_hand_count) == (29, 7, 7)

        sample = reader.get_sample(0)
        model.set_joint_state(sample.observation_state)
        np.testing.assert_allclose(model.data.qpos[model.qpos_indices], sample.observation_state)
    finally:
        reader.close()
