from __future__ import annotations

from dataclasses import dataclass


JOINT_NAMES = (
    "left_hip_pitch_joint",
    "left_hip_roll_joint",
    "left_hip_yaw_joint",
    "left_knee_joint",
    "left_ankle_pitch_joint",
    "left_ankle_roll_joint",
    "right_hip_pitch_joint",
    "right_hip_roll_joint",
    "right_hip_yaw_joint",
    "right_knee_joint",
    "right_ankle_pitch_joint",
    "right_ankle_roll_joint",
    "waist_yaw_joint",
    "waist_roll_joint",
    "waist_pitch_joint",
    "left_shoulder_pitch_joint",
    "left_shoulder_roll_joint",
    "left_shoulder_yaw_joint",
    "left_elbow_joint",
    "left_wrist_roll_joint",
    "left_wrist_pitch_joint",
    "left_wrist_yaw_joint",
    "left_hand_thumb_0_joint",
    "left_hand_thumb_1_joint",
    "left_hand_thumb_2_joint",
    "left_hand_middle_0_joint",
    "left_hand_middle_1_joint",
    "left_hand_index_0_joint",
    "left_hand_index_1_joint",
    "right_shoulder_pitch_joint",
    "right_shoulder_roll_joint",
    "right_shoulder_yaw_joint",
    "right_elbow_joint",
    "right_wrist_roll_joint",
    "right_wrist_pitch_joint",
    "right_wrist_yaw_joint",
    "right_hand_thumb_0_joint",
    "right_hand_thumb_1_joint",
    "right_hand_thumb_2_joint",
    "right_hand_middle_0_joint",
    "right_hand_middle_1_joint",
    "right_hand_index_0_joint",
    "right_hand_index_1_joint",
)


BASE_JOINT_GROUPS = {
    "waist": ("waist_yaw_joint", "waist_roll_joint", "waist_pitch_joint"),
    "left_leg": (
        "left_hip_pitch_joint",
        "left_hip_roll_joint",
        "left_hip_yaw_joint",
        "left_knee_joint",
        "left_ankle_pitch_joint",
        "left_ankle_roll_joint",
    ),
    "right_leg": (
        "right_hip_pitch_joint",
        "right_hip_roll_joint",
        "right_hip_yaw_joint",
        "right_knee_joint",
        "right_ankle_pitch_joint",
        "right_ankle_roll_joint",
    ),
    "legs": ("left_leg", "right_leg"),
    "left_arm": (
        "left_shoulder_pitch_joint",
        "left_shoulder_roll_joint",
        "left_shoulder_yaw_joint",
        "left_elbow_joint",
        "left_wrist_roll_joint",
        "left_wrist_pitch_joint",
        "left_wrist_yaw_joint",
    ),
    "right_arm": (
        "right_shoulder_pitch_joint",
        "right_shoulder_roll_joint",
        "right_shoulder_yaw_joint",
        "right_elbow_joint",
        "right_wrist_roll_joint",
        "right_wrist_pitch_joint",
        "right_wrist_yaw_joint",
    ),
    "arms": ("left_arm", "right_arm"),
    "left_hand": (
        "left_hand_index_0_joint",
        "left_hand_index_1_joint",
        "left_hand_middle_0_joint",
        "left_hand_middle_1_joint",
        "left_hand_thumb_0_joint",
        "left_hand_thumb_1_joint",
        "left_hand_thumb_2_joint",
    ),
    "right_hand": (
        "right_hand_index_0_joint",
        "right_hand_index_1_joint",
        "right_hand_middle_0_joint",
        "right_hand_middle_1_joint",
        "right_hand_thumb_0_joint",
        "right_hand_thumb_1_joint",
        "right_hand_thumb_2_joint",
    ),
    "hands": ("left_hand", "right_hand"),
    "lower_body": ("waist", "legs"),
    "upper_body_no_hands": ("arms",),
    "body": ("lower_body", "upper_body_no_hands"),
    "upper_body": ("upper_body_no_hands", "hands"),
}


@dataclass
class G1DataProfile:
    waist_location: str = "lower_body"

    def __post_init__(self):
        if self.waist_location not in {"lower_body", "upper_body", "lower_and_upper_body"}:
            raise ValueError(
                f"Invalid waist_location: {self.waist_location}. "
                "Expected one of: lower_body, upper_body, lower_and_upper_body."
            )
        self.joint_names = list(JOINT_NAMES)
        self._joint_index = {name: idx for idx, name in enumerate(self.joint_names)}
        self.joint_groups = self._build_joint_groups()

    @property
    def num_joints(self) -> int:
        return len(self.joint_names)

    def _build_joint_groups(self) -> dict[str, tuple[str, ...]]:
        groups = dict(BASE_JOINT_GROUPS)
        if self.waist_location == "upper_body":
            groups["lower_body"] = ("legs",)
            groups["upper_body_no_hands"] = ("arms", "waist")
        elif self.waist_location == "lower_and_upper_body":
            groups["upper_body_no_hands"] = ("arms", "waist")
        return groups

    def get_joint_group_indices(self, group_name: str) -> list[int]:
        if group_name not in self.joint_groups:
            raise ValueError(f"Unknown joint group: {group_name}")

        indices: list[int] = []
        for item in self.joint_groups[group_name]:
            if item in self._joint_index:
                indices.append(self._joint_index[item])
            else:
                indices.extend(self.get_joint_group_indices(item))
        return sorted(set(indices))
