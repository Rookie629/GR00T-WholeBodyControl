# G1 RGBD Data Collection Summary

## Scope

This document summarizes the data-collection work added during this iteration.
The goal was to connect:

- `gear_sonic_deploy` real-robot teleop
- the G1 head RealSense D435
- `gear_sonic_deploy/sonic_data` exporter
- dataset storage with RGB, depth, robot state, and actions

## What Was Added

### 1. D435 acquisition and bridging

Directory:

- `gear_sonic_deploy/image_server/`
- `gear_sonic_deploy/sonic_data/`

Purpose:

- read the G1 head D435
- expose RGBD over ZMQ
- bridge RGBD into a local `gear_sonic_deploy` transport layer
- provide smoke tests and probes

See:

- [gear_sonic_deploy/image_server/README.md](/home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy/image_server/README.md)
- [gear_sonic_deploy/sonic_data/README.md](/home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy/sonic_data/README.md)

### 2. Teleop-side data collection

Directory:

- `gear_sonic_deploy/sonic_data/`

Purpose:

- subscribe to robot state and bridged camera data
- align them frame-by-frame during recording
- save episodes under operator control

See:

- [gear_sonic_deploy/sonic_data/README.md](/home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy/sonic_data/README.md)

### 3. Image transport upgrade

Directories:

- `gear_sonic_deploy/sonic_data/`
- `decoupled_wbc/control/sensor/`

Purpose:

- keep the runtime helper layer local to `gear_sonic_deploy`
- carry typed RGB/depth camera payloads through the same sensor interface

See:

- [decoupled_wbc/control/sensor/README.md](/home/yangke/KY/GR00T-WholeBodyControl/decoupled_wbc/control/sensor/README.md)

### 4. Dataset schema and exporter updates

Directory:

- `gear_sonic_deploy/sonic_data/dataset/`

Purpose:

- define how the dataset describes RGB, depth, state, and action
- write local parquet metadata inspired by `G1_WB_Dex5_Collect_Clothes`
- store RGB as mp4 and depth as `uint16` frame data

See:

- [gear_sonic_deploy/sonic_data/README.md](/home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy/sonic_data/README.md)

## End-To-End Pipeline

1. On G1, `image_server.py` opens the D435 and publishes RGBD over ZMQ.
2. On the collector machine, `composed_camera_bridge.py` converts that stream
   into `ImageMessageSchema`.
3. `gear_sonic_deploy` publishes robot state/action to ROS2.
4. `run_g1_data_exporter.py` samples the latest state and latest image, builds a
   frame, and writes it into the dataset.
5. RGB is stored as video, while depth is stored as `uint16` frame data.

## Recommended Startup Order

On G1:

1. Start `gear_sonic_deploy/image_server/image_server.py`

On collector:

1. Activate the runtime environment:
```bash
cd /home/yangke/KY/GR00T-WholeBodyControl
source .venv_teleop/bin/activate
source /opt/ros/humble/setup.bash
```
2. Start `gear_sonic_deploy/deploy.sh`
3. Start `gear_sonic/scripts/pico_manager_thread_server.py`
4. Start `gear_sonic_deploy/image_server/composed_camera_bridge.py`
5. Start either:
```bash
python3 gear_sonic_deploy/sonic_data/run_g1_data_exporter.py ...
```
or:
```bash
python3 gear_sonic_deploy/sonic_data/gui/main.py
```

## Episode Control

- `c`: start recording, or stop and save the current episode
- `x`: discard the current episode

The GUI sends these commands for you. If you use the CLI path, they are sent on
`/Gr00tKeyboardListener`.

## Runtime Components

Robot side:

- `gear_sonic_deploy/image_server/image_server.py`

Collector side:

- `gear_sonic_deploy/deploy.sh`
- `gear_sonic/scripts/pico_manager_thread_server.py`
- `gear_sonic_deploy/image_server/composed_camera_bridge.py`
- `gear_sonic_deploy/sonic_data/run_g1_data_exporter.py`

Optional visualization:

- `gear_sonic_deploy/image_server/image_client.py`
- `gear_sonic_deploy/image_server/stream_smoke_test.py`

Optional tools:

- `gear_sonic_deploy/image_server/stream_smoke_test.py`
- `gear_sonic_deploy/image_server/image_client.py`
- `gear_sonic_deploy/image_server/realsense_probe.py`
- `gear_sonic_deploy/image_server/depth_episode_recorder.py`
- `gear_sonic_deploy/image_server/print_robot_state.py`
- `gear_sonic_deploy/sonic_data/*`

## Main Data Outputs

Recorded samples now support:

- robot joint/state vectors
- wrist/eef state
- teleop action
- base and navigation commands
- RGB `ego_view`
- depth `ego_view_depth`
- optional raw RGBD sidecar files for debugging

## Current Limits

- camera intrinsics are not yet written into dataset metadata
- depth is stored as array data rather than video, by design
- if the G1 system camera service occupies the D435, the custom image server
  cannot start until that service conflict is handled
- the dataset layout is reference-compatible rather than a byte-for-byte clone
  of `lerobot`, so downstream code should target the local parquet/mp4 format
