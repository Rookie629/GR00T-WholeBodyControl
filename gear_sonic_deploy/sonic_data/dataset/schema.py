from __future__ import annotations

from gear_sonic_deploy.sonic_data.constants import (
    RS_VIEW_CAMERA_HEIGHT,
    RS_VIEW_CAMERA_WIDTH,
    SONIC_DECODER_INPUT_DIM,
    SONIC_ENCODER_INPUT_DIM,
    SONIC_TOKEN_STATE_DIM,
)
from gear_sonic_deploy.sonic_data.g1_profile import G1DataProfile


def get_modality_config(
    robot_profile: G1DataProfile,
    add_stereo_camera: bool = False,
    add_depth_camera: bool = False,
) -> dict:
    left_hand_indices = sorted(robot_profile.get_joint_group_indices("left_hand"))
    right_hand_indices = sorted(robot_profile.get_joint_group_indices("right_hand"))
    left_arm_indices = sorted(robot_profile.get_joint_group_indices("left_arm"))
    right_arm_indices = sorted(robot_profile.get_joint_group_indices("right_arm"))
    waist_indices = sorted(robot_profile.get_joint_group_indices("waist"))
    left_leg_indices = sorted(robot_profile.get_joint_group_indices("left_leg"))
    right_leg_indices = sorted(robot_profile.get_joint_group_indices("right_leg"))

    modality_config = {
        "state": {
            "left_leg": {"start": left_leg_indices[0], "end": left_leg_indices[-1] + 1},
            "right_leg": {"start": right_leg_indices[0], "end": right_leg_indices[-1] + 1},
            "waist": {"start": waist_indices[0], "end": waist_indices[-1] + 1},
            "left_arm": {"start": left_arm_indices[0], "end": left_arm_indices[-1] + 1},
            "left_hand": {"start": left_hand_indices[0], "end": left_hand_indices[-1] + 1},
            "right_arm": {"start": right_arm_indices[0], "end": right_arm_indices[-1] + 1},
            "right_hand": {"start": right_hand_indices[0], "end": right_hand_indices[-1] + 1},
            "left_wrist_pos": {"start": 0, "end": 3, "original_key": "observation.eef_state"},
            "left_wrist_abs_quat": {
                "start": 3,
                "end": 7,
                "original_key": "observation.eef_state",
                "rotation_type": "quaternion",
            },
            "right_wrist_pos": {"start": 7, "end": 10, "original_key": "observation.eef_state"},
            "right_wrist_abs_quat": {
                "start": 10,
                "end": 14,
                "original_key": "observation.eef_state",
                "rotation_type": "quaternion",
            },
        },
        "action": {
            "left_leg": {"start": left_leg_indices[0], "end": left_leg_indices[-1] + 1},
            "right_leg": {"start": right_leg_indices[0], "end": right_leg_indices[-1] + 1},
            "waist": {"start": waist_indices[0], "end": waist_indices[-1] + 1},
            "left_arm": {"start": left_arm_indices[0], "end": left_arm_indices[-1] + 1},
            "left_hand": {"start": left_hand_indices[0], "end": left_hand_indices[-1] + 1},
            "right_arm": {"start": right_arm_indices[0], "end": right_arm_indices[-1] + 1},
            "right_hand": {"start": right_hand_indices[0], "end": right_hand_indices[-1] + 1},
            "left_wrist_pos": {"start": 0, "end": 3, "original_key": "action.eef"},
            "left_wrist_abs_quat": {
                "start": 3,
                "end": 7,
                "original_key": "action.eef",
                "rotation_type": "quaternion",
            },
            "right_wrist_pos": {"start": 7, "end": 10, "original_key": "action.eef"},
            "right_wrist_abs_quat": {
                "start": 10,
                "end": 14,
                "original_key": "action.eef",
                "rotation_type": "quaternion",
            },
            "base_height_command": {
                "start": 0,
                "end": 1,
                "original_key": "teleop.base_height_command",
            },
            "navigate_command": {"start": 0, "end": 3, "original_key": "teleop.navigate_command"},
        },
        "video": {"ego_view": {"original_key": "observation.images.ego_view"}},
        "annotation": {"human.task_description": {"original_key": "task_index"}},
    }
    if add_stereo_camera:
        modality_config["video"].update(
            {
                "ego_view_left_mono": {"original_key": "observation.images.ego_view_left_mono"},
                "ego_view_right_mono": {"original_key": "observation.images.ego_view_right_mono"},
            }
        )
    if add_depth_camera:
        modality_config["video"].update(
            {
                "ego_view_depth": {
                    "original_key": "observation.images.ego_view_depth",
                    "storage_dtype": "uint16",
                }
            }
        )
    return modality_config


def get_dataset_features(
    robot_profile: G1DataProfile,
    add_stereo_camera: bool = False,
    add_depth_camera: bool = False,
) -> dict:
    dataset_features = {
        "observation.images.ego_view": {
            "dtype": "video",
            "shape": [RS_VIEW_CAMERA_HEIGHT, RS_VIEW_CAMERA_WIDTH, 3],
            "names": ["height", "width", "channel"],
        },
        "observation.state": {
            "dtype": "float64",
            "shape": (robot_profile.num_joints,),
            "names": robot_profile.joint_names,
        },
        "observation.eef_state": {
            "dtype": "float64",
            "shape": (14,),
            "names": [
                "left_wrist_pos",
                "left_wrist_abs_quat",
                "right_wrist_pos",
                "right_wrist_abs_quat",
            ],
        },
        "action": {
            "dtype": "float64",
            "shape": (robot_profile.num_joints,),
            "names": robot_profile.joint_names,
        },
        "action.eef": {
            "dtype": "float64",
            "shape": (14,),
            "names": [
                "left_wrist_pos",
                "left_wrist_abs_quat",
                "right_wrist_pos",
                "right_wrist_abs_quat",
            ],
        },
        "observation.img_state_delta": {
            "dtype": "float32",
            "shape": (1,),
            "names": "img_state_delta",
        },
        "observation.token_state": {
            "dtype": "float64",
            "shape": (SONIC_TOKEN_STATE_DIM,),
            "names": [f"token_state_{i}" for i in range(SONIC_TOKEN_STATE_DIM)],
        },
        "observation.encoder_input": {
            "dtype": "float64",
            "shape": (SONIC_ENCODER_INPUT_DIM,),
            "names": [f"encoder_input_{i}" for i in range(SONIC_ENCODER_INPUT_DIM)],
        },
        "observation.decoder_input": {
            "dtype": "float64",
            "shape": (SONIC_DECODER_INPUT_DIM,),
            "names": [f"decoder_input_{i}" for i in range(SONIC_DECODER_INPUT_DIM)],
        },
        "teleop.navigate_command": {
            "dtype": "float64",
            "shape": (3,),
            "names": ["lin_vel_x", "lin_vel_y", "ang_vel_z"],
        },
        "teleop.base_height_command": {
            "dtype": "float64",
            "shape": (1,),
            "names": "base_height_command",
        },
    }
    if add_stereo_camera:
        dataset_features.update(
            {
                "observation.images.ego_view_left_mono": {
                    "dtype": "video",
                    "shape": [RS_VIEW_CAMERA_HEIGHT, RS_VIEW_CAMERA_WIDTH, 3],
                    "names": ["height", "width", "channel"],
                },
                "observation.images.ego_view_right_mono": {
                    "dtype": "video",
                    "shape": [RS_VIEW_CAMERA_HEIGHT, RS_VIEW_CAMERA_WIDTH, 3],
                    "names": ["height", "width", "channel"],
                },
            }
        )
    if add_depth_camera:
        dataset_features.update(
            {
                "observation.images.ego_view_depth": {
                    "dtype": "uint16",
                    "shape": [RS_VIEW_CAMERA_HEIGHT, RS_VIEW_CAMERA_WIDTH],
                    "names": ["height", "width"],
                }
            }
        )
    return dataset_features
