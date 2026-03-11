from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class DataExporterConfig:
    """Sonic-side config for the G1 data exporter."""

    camera_port: int = 5555
    camera_host: str = "localhost"
    fps: float = 20.0

    dataset_name: Optional[str] = None
    task_prompt: str = "demo"

    state_dim: int = 43
    action_dim: int = 43

    teleoperator_username: Optional[str] = None
    support_operator_username: Optional[str] = None
    robot_id: Optional[str] = None
    lower_body_policy: Optional[str] = None
    wbc_model_path: Optional[str] = None

    data_collection_frequency: int = 20
    root_output_dir: str = "outputs"

    img_stream_viewer: bool = False
    text_to_speech: bool = True
    add_stereo_camera: bool = True
    add_depth_camera: bool = False
