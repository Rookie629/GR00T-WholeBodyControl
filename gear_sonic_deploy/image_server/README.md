# G1 D435 Image Server

## Purpose

This directory contains the RealSense D435 side of the G1 data collection path.
Its job is to:

- open the G1 head D435 on the robot
- publish RGBD frames over ZMQ
- bridge those frames into the local `gear_sonic_deploy.sonic_data` camera message format
- provide small validation tools for stream, ROS state, and recording checks

This is the camera-facing half of the end-to-end collection pipeline.

## Changes In This Work

The original `image_server.py` only exposed the raw RealSense stream. This work
added the pieces needed to use it in the existing exporter path, and also moved
the bridge/runtime helper dependencies under `gear_sonic_deploy/sonic_data`:

- `composed_camera_bridge.py`
  - converts the raw D435 stream into `ImageMessageSchema`
  - supports `ego_view` RGB and optional `ego_view_depth`
- `depth_episode_recorder.py`
  - optional sidecar recorder for raw per-frame RGB and depth files
- `stream_smoke_test.py`
  - visual check for bridge output and ROS robot-state topics
- `realsense_smoke_test.py`
  - local GUI test for D435 color and depth
- `realsense_probe.py`
  - headless probe for checking whether the G1-side D435 exists and can open
- `print_robot_state.py`
  - decodes `G1Env/env_state_act` for quick terminal inspection
- `requirements.txt`
  - minimal pip dependencies for this folder's Python tools
- `../sonic_data/`
  - local ROS topic, transport, keyboard, and bridged camera client helpers

## Directory Roles

- `image_server.py`
  - runs on the machine physically connected to the D435, usually the G1
- `image_client.py`
  - visualizes the raw ZMQ RGBD stream directly from `image_server.py`
- `composed_camera_bridge.py`
  - runs on the collector machine and republishes images in the format expected
    by `ComposedCameraClientSensor`
- `depth_episode_recorder.py`
  - optional backup recorder for raw RGBD frames aligned to episode control

## Recommended Runtime Layout

Robot side:

- run `image_server.py` on the G1 if the D435 is plugged into the G1

Collector side:

- run `gear_sonic_deploy/deploy.sh`
- run `pico_manager_thread_server.py`
- run `composed_camera_bridge.py`
- run `run_g1_data_exporter.py`

Recommended ports:

- `5555`: raw D435 RGBD stream from `image_server.py`
- `5560`: bridged image stream for `run_g1_data_exporter.py`

## Typical Commands

### 1. On G1

```bash
python3 gear_sonic_deploy/image_server/image_server.py
```

### 2. On collector machine

```bash
python3 gear_sonic_deploy/image_server/composed_camera_bridge.py \
  --image-server-ip <G1_IP> \
  --image-server-port 5555 \
  --output-port 5560 \
  --include-depth
```

### 3. Quick visualization

```bash
python3 gear_sonic_deploy/image_server/stream_smoke_test.py \
  --camera-host 127.0.0.1 \
  --camera-port 5560
```

## Output Contract

The bridge publishes these image keys:

- `ego_view`
- `ego_view_depth` when `--include-depth` is enabled

Downstream, those keys are consumed by the exporter path. The helper transport
layer now lives locally under:

- `gear_sonic_deploy/sonic_data/`

The current dataset writer backend still lives in:

- `decoupled_wbc/control/main/teleop/run_g1_data_exporter.py`

The recommended entrypoint from the `gear_sonic_deploy` side is now:

- `gear_sonic_deploy/sonic_data/run_g1_data_exporter.py`

## Known Limits

- camera intrinsics are not yet included in exporter metadata
- depth is forwarded as `uint16` array data, not encoded as video
- if the G1 system service is already using the D435, `image_server.py` cannot
  open the device until that conflict is resolved
- the LeRobot exporter backend itself has not yet been fully migrated out of
  `decoupled_wbc`
