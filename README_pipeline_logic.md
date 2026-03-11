# G1 RGBD Data Collection Pipeline

## Goal

This document explains the runtime logic of the current G1 real-robot data
collection pipeline built from:

- `gear_sonic_deploy`
- `gear_sonic_deploy/image_server`
- `gear_sonic_deploy/sonic_data`

The pipeline collects:

- robot state
- robot action
- teleop commands
- D435 RGB
- D435 depth

and writes them into a dataset session.

## High-Level Flow

The pipeline has two machines or roles:

1. G1 side
   - opens the D435
   - publishes raw RGBD frames over ZMQ
2. Collector side
   - runs teleop and robot deployment
   - subscribes to robot ROS2 state
   - bridges camera frames into typed image messages
   - records synchronized frames into the dataset

## Component Roles

### 1. G1 D435 image source

File:

- [gear_sonic_deploy/image_server/image_server.py](/home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy/image_server/image_server.py)

Purpose:

- open the head RealSense D435 on the robot
- publish color and depth frames through ZMQ

Default role:

- runs on the G1 machine

Output:

- raw ZMQ RGBD stream, typically on `tcp://<G1_IP>:5555`

### 2. Camera bridge

File:

- [gear_sonic_deploy/image_server/composed_camera_bridge.py](/home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy/image_server/composed_camera_bridge.py)

Purpose:

- subscribe to the raw D435 ZMQ stream
- convert frames into the typed `ImageMessageSchema`
- republish them for the local dataset/exporter path

Local transport definitions:

- [gear_sonic_deploy/sonic_data/sensor_transport.py](/home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy/sonic_data/sensor_transport.py)
- [gear_sonic_deploy/sonic_data/camera_client.py](/home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy/sonic_data/camera_client.py)

Bridge outputs:

- `ego_view`
- `ego_view_depth` when `--include-depth` is enabled

Typical output port:

- `tcp://127.0.0.1:5560`

### 3. Robot state publisher

Source side:

- `gear_sonic_deploy` runtime with ROS2 output enabled

Important topics:

- `G1Env/env_state_act`
- `WBCPolicy/robot_config`

Local topic constants:

- [gear_sonic_deploy/sonic_data/topics.py](/home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy/sonic_data/topics.py)

Purpose:

- publish per-tick robot state/action as msgpack-over-ROS2
- publish one-shot robot config metadata

### 4. Dataset exporter entrypoint

User-facing entrypoint:

- [gear_sonic_deploy/sonic_data/run_g1_data_exporter.py](/home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy/sonic_data/run_g1_data_exporter.py)

Purpose:

- subscribe to robot ROS2 state
- subscribe to bridged camera messages
- build frame dictionaries
- save episodes into the dataset

The full collector/exporter backend now lives in:

- `gear_sonic_deploy/sonic_data/`

### 5. Unified collector GUI

File:

- [gear_sonic_deploy/sonic_data/gui/main.py](/home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy/sonic_data/gui/main.py)

Purpose:

- start and stop bridge and exporter from one window
- preview RGB and depth in the same collector window
- publish episode-control commands without manual `ros2 topic pub`
- keep standalone test tools available as separate windows

Implementation:

- built with standard-library `tkinter`
### 6. Optional sidecar recorder

File:

- [gear_sonic_deploy/image_server/depth_episode_recorder.py](/home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy/image_server/depth_episode_recorder.py)

Purpose:

- save raw `jpg/png` RGBD frames by episode
- follow the same episode control topic as the exporter

This is optional. The main dataset already stores depth.

## Runtime Logic

### Collector environment

All collector-side validation and runtime commands should use:

```bash
cd /home/yangke/KY/GR00T-WholeBodyControl
source .venv_teleop/bin/activate
source /opt/ros/humble/setup.bash
```

### Step 1. Start robot deployment

On the collector machine:

```bash
cd /home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy
source scripts/setup_env.sh
./deploy.sh real --input-type zmq_manager --output-type all --enable-csv-logs
```

Effect:

- SONIC deploy starts
- ROS2 state/action topics begin publishing
- optional CSV logs are also written

### Step 2. Start PICO teleop

```bash
cd /home/yangke/KY/GR00T-WholeBodyControl
source .venv_teleop/bin/activate
python3 gear_sonic/scripts/pico_manager_thread_server.py --manager
```

Effect:

- VR teleop input begins driving the upper-body teleop path

### Step 3. Start D435 image server on G1

On the G1:

```bash
rs-enumerate-devices
cd Project/image_server/
python3 image_server.py
```

Effect:

- D435 color and depth frames are published over ZMQ

### Step 4. Start bridge on collector side

```bash
cd /home/yangke/KY/GR00T-WholeBodyControl
python3 gear_sonic_deploy/image_server/composed_camera_bridge.py \
  --image-server-ip <G1_IP> \
  --image-server-port 5555 \
  --output-port 5560 \
  --include-depth
```

Effect:

- raw D435 frames are decoded
- RGB is forwarded as `ego_view`
- depth is forwarded as `ego_view_depth`
- the local typed image stream becomes available to the exporter

### Step 4.5. Optional image visualization checks

#### Check raw D435 stream from G1

```bash
cd /home/yangke/KY/GR00T-WholeBodyControl
python3 gear_sonic_deploy/image_server/image_client.py \
  --ip <G1_IP> \
  --port 5555
```

Effect:

- directly visualizes the raw RGBD stream coming from `image_server.py`
- useful for confirming the G1-side camera and network path are healthy before
  testing the bridge

#### Check bridged image stream

```bash
cd /home/yangke/KY/GR00T-WholeBodyControl
source /opt/ros/humble/setup.bash
python3 gear_sonic_deploy/image_server/stream_smoke_test.py \
  --camera-host 127.0.0.1 \
  --camera-port 5560
```

Effect:

- visualizes bridged `ego_view` and `ego_view_depth`
- overlays `camera_hz` and `state_hz`
- confirms both the image bridge and ROS2 robot state path are alive
- exits with `q`, `Esc`, window close, or automatically via `--max-seconds` / `--max-frames`

### Step 5. Start exporter

```bash
python3 gear_sonic_deploy/sonic_data/run_g1_data_exporter.py \
  --camera_host 127.0.0.1 \
  --camera_port 5560 \
  --data_collection_frequency 20 \
  --root_output_dir outputs/g1_rgbd \
  --no-add_stereo_camera \
  --add_depth_camera
```

Effect:

- the exporter waits for both:
  - latest robot state
  - latest bridged camera message
- once recording starts, it writes frame-by-frame data into the dataset

### Step 5A. Start the unified GUI instead of manual bridge/exporter launch

```bash
python3 gear_sonic_deploy/sonic_data/gui/main.py
```

Effect:

- one window launches the bridge and exporter
- one window previews RGB and depth
- one window publishes episode control commands

Recommended GUI flow:

1. Fill `G1 IP`, `Dataset`, `Task`, and output directory.
2. Click `Start All`.
3. Wait for RGB/depth preview to update.
4. Click `Record / Stop Save` to start.
5. Click `Record / Stop Save` again to save.
6. Click `Discard` to drop the current episode.

### Step 5.5. Optional unified GUI

```bash
cd /home/yangke/KY/GR00T-WholeBodyControl
source /opt/ros/humble/setup.bash
python3 gear_sonic_deploy/sonic_data/gui/main.py
```

Effect:

- collector-side launch is reduced to a single window
- `composed_camera_bridge.py` and `run_g1_data_exporter.py` can be started from the GUI
- RGBD preview and episode controls are embedded in the same window
- raw and bridged stream tests remain available as separate scripts
### Step 6. Optional sidecar

```bash
cd /home/yangke/KY/GR00T-WholeBodyControl
source /opt/ros/humble/setup.bash
python3 gear_sonic_deploy/image_server/depth_episode_recorder.py \
  --save-root outputs/g1_rgbd/<dataset_name> \
  --image-server-ip <G1_IP> \
  --image-server-port 5555
```

Effect:

- raw RGBD frames are saved alongside the main dataset

## Synchronization Logic

The pipeline does not hard-trigger all sensors from one clock. It uses a
latest-message sampling model.

Runtime behavior in the exporter:

1. poll latest robot state from `G1Env/env_state_act`
2. poll latest bridged image message from port `5560`
3. when both exist, construct one frame
4. compute the largest timestamp gap between image timestamps and proprio timestamp
5. write that gap as `observation.img_state_delta`

This is a soft-sync design:

- robot state and image stream are asynchronous
- exporter samples both at `data_collection_frequency`
- sync quality is tracked, not assumed

## Episode Control Logic

Episode control uses ROS topic:

- `/Gr00tKeyboardListener`

The same control topic can drive:

- main exporter
- optional depth sidecar recorder

Commands:

- `c`
  - if idle: start recording
  - if recording: stop and save current episode
- `x`
  - discard current episode

Example:

```bash
ros2 topic pub /Gr00tKeyboardListener std_msgs/msg/String "{data: 'c'}" --once
```

## What Gets Stored

Main dataset contains:

- `observation.state`
- `observation.eef_state`
- `action`
- `action.eef`
- `teleop.navigate_command`
- `teleop.base_height_command`
- `observation.img_state_delta`
- `observation.images.ego_view`
- `observation.images.ego_view_depth`

Storage behavior:

- RGB is stored as video
- depth is stored as `uint16` array data
- robot state/action are stored in tabular dataset fields

Optional sidecar contains:

- per-frame `*_color.jpg`
- per-frame `*_depth.png`
- episode-level `meta.json`

## Validation Tools

Raw image check:

- [gear_sonic_deploy/image_server/image_client.py](/home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy/image_server/image_client.py)

Bridge + state visualization:

- [gear_sonic_deploy/image_server/stream_smoke_test.py](/home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy/image_server/stream_smoke_test.py)

Headless D435 probe:

- [gear_sonic_deploy/image_server/realsense_probe.py](/home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy/image_server/realsense_probe.py)

Decoded robot state print:

- [gear_sonic_deploy/image_server/print_robot_state.py](/home/yangke/KY/GR00T-WholeBodyControl/gear_sonic_deploy/image_server/print_robot_state.py)

## Current Migration Boundary

This pipeline is now fully migrated into `gear_sonic_deploy` for collector-side
runtime and dataset export.

The exporter no longer depends on `lerobot`. It writes a local dataset with the
same top-level structure as the reference `G1_WB_Dex5_Collect_Clothes` dataset:

- `meta/info.json`
- `meta/stats.json`
- `meta/tasks.parquet`
- `meta/episodes/chunk-*/file-000.parquet`
- `data/chunk-*/file-*.parquet`
- `videos/<video_key>/chunk-*/file-*.mp4`

## Common Failure Points

### D435 cannot open

Likely causes:

- G1 system camera service already occupies the device
- another RealSense process is running

### Bridge shows frames but exporter records nothing

Check:

- `G1Env/env_state_act` is being published
- exporter is connected to `--camera_port 5560`
- `--add_depth_camera` matches the bridge output

### No GUI available

Use:

- `realsense_probe.py`
- `print_robot_state.py`

instead of OpenCV window-based tools.
