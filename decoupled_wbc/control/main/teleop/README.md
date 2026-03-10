# Teleop Data Export

## Purpose

This directory contains the teleoperation-side runtime that turns live robot
state and live camera frames into dataset episodes.

For this workflow, the key entrypoint is `run_g1_data_exporter.py`.

## Changes In This Work

This work extended the exporter so the existing teleop collector can record the
G1 D435 RGBD stream, not only RGB:

- `run_g1_data_exporter.py`
  - now accepts depth-capable image messages
  - writes all configured `observation.images.*` fields instead of assuming only
    a fixed RGB subset
- `configs/configs.py`
  - adds `add_depth_camera` to `DataExporterConfig`

## Main Runtime Path

`run_g1_data_exporter.py` does four things:

1. subscribes to robot state from ROS2
2. subscribes to camera frames from `ComposedCameraClientSensor`
3. synchronizes by sampling the latest state and latest image in the same loop
4. writes frames into `Gr00tDataExporter`

The exporter records:

- `observation.state`
- `observation.eef_state`
- `action`
- `action.eef`
- `teleop.navigate_command`
- `teleop.base_height_command`
- `observation.img_state_delta`
- `observation.images.ego_view`
- `observation.images.ego_view_depth` when enabled

## D435 Usage

Typical command:

```bash
python3 decoupled_wbc/control/main/teleop/run_g1_data_exporter.py \
  --camera_host 127.0.0.1 \
  --camera_port 5560 \
  --data_collection_frequency 20 \
  --root_output_dir outputs/g1_rgbd \
  --no-add_stereo_camera \
  --add_depth_camera
```

Recommended for the D435 bridge path:

- disable stereo cameras
- enable depth camera

## Recording Control

Episode control still comes from `/Gr00tKeyboardListener`:

- `c`: start recording, or stop and save the current episode
- `x`: discard the current recording

## Notes

- synchronization is soft-sync based on latest available state and image
- `observation.img_state_delta` records the state-image timing gap per frame
- if the depth key is declared in dataset features but not present in the image
  message, the exporter raises an error instead of silently dropping it
