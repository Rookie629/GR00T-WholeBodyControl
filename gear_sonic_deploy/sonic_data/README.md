# Sonic Data Utilities

## Purpose

This directory now holds the collector-side Python runtime for the G1 RGBD
data collection path under `gear_sonic_deploy`.

It contains:

- ROS topic constants
- ROS msgpack subscribers and service client helpers
- typed RGB/depth ZMQ transport
- a bridged-camera client
- episode state / telemetry / text-to-speech helpers
- a static G1 data profile used for dataset schema generation
- a local parquet/mp4 dataset exporter backend modeled after the
  `G1_WB_Dex5_Collect_Clothes` metadata layout
- the exporter collector loop and CLI entrypoint
- a lightweight `tkinter` collector GUI that merges preview, control, and launch actions

## Scope

This directory is now the primary runtime path for collector-side data
collection. It no longer depends on `decoupled_wbc` at runtime.

What lives here:

- `dataset/`
  - local metadata, frame buffering, episode saving, parquet writing, and video writing
- `g1_profile.py`
  - static G1 joint ordering and group metadata for schema generation
- `collector.py`
  - state/image sync loop and episode lifecycle
- `run_g1_data_exporter.py`
  - user-facing exporter entrypoint
- `gui/`
  - unified collector GUI for bridge/exporter launch, RGBD preview, and episode control

Related runtime consumers:

- `gear_sonic_deploy/image_server/`
  - raw D435 server, bridge, and standalone diagnostics

## Recommended Entry Points

Collector-side environment:

```bash
cd /home/yangke/KY/GR00T-WholeBodyControl
source .venv_teleop/bin/activate
source /opt/ros/humble/setup.bash
```

Minimal collector-side dependencies:

```bash
python -m pip install -r gear_sonic_deploy/sonic_data/requirements.txt
```

CLI path:

1. Start `deploy.sh`, `pico_manager_thread_server.py`, and `composed_camera_bridge.py`.
2. Then start the exporter below.
3. Use `c` on `/Gr00tKeyboardListener` to start/stop-save, and `x` to discard.

CLI exporter:

```bash
python3 gear_sonic_deploy/sonic_data/run_g1_data_exporter.py \
  --camera_host 127.0.0.1 \
  --camera_port 5560 \
  --data_collection_frequency 20 \
  --root_output_dir outputs/g1_rgbd \
  --no-add_stereo_camera \
  --add_depth_camera
```

Unified GUI:

```bash
python3 gear_sonic_deploy/sonic_data/gui/main.py
```

The GUI:

- starts and stops the bridge and exporter
- previews `ego_view` and `ego_view_depth`
- publishes `c` / `x` to `/Gr00tKeyboardListener`
- still leaves the standalone test tools available

Typical GUI usage:

1. Start `image_server.py` on the G1.
2. On the collector machine, open the GUI.
3. Fill `G1 IP`, `Dataset`, `Task`, and output directory.
4. Click `Start All`.
5. Confirm RGB and depth previews update.
6. Click `Record / Stop Save` to start an episode.
7. Click `Record / Stop Save` again to end and save the episode.
8. Click `Discard` to drop the current episode.

Dataset output layout:

- `meta/info.json`
- `meta/stats.json`
- `meta/tasks.parquet`
- `meta/episodes/chunk-*/file-000.parquet`
- `data/chunk-*/file-*.parquet`
- `videos/observation.images.ego_view/chunk-*/file-*.mp4`
