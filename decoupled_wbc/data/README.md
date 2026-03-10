# Data Export Format

## Purpose

This directory owns dataset feature definitions and episode export behavior for
the `decoupled_wbc` collection stack.

For this workflow, the relevant files are:

- `utils.py`
- `exporter.py`

## Changes In This Work

This work extended the exporter to store D435 depth inside the main dataset
instead of only using an external sidecar.

### `utils.py`

Added depth-aware dataset description:

- `get_modality_config(..., add_depth_camera=True)`
  - declares `ego_view_depth`
- `get_dataset_features(..., add_depth_camera=True)`
  - defines `observation.images.ego_view_depth`
  - stored as `uint16` with shape `[H, W]`

### `exporter.py`

Updated the data writer to handle mixed RGB-video and array-image features:

- RGB still follows the existing video path
- depth is stored as array data, not as video
- feature/stat handling skips image-array fields where video-style stats do not
  make sense
- dtype handling was extended so `uint16` can be preserved during save/load

## Resulting Dataset Contract

The main dataset can now contain:

- proprioception and action in parquet/tabular data
- RGB `ego_view` in video shards
- depth `ego_view_depth` in dataset tables as `uint16`

## Why Depth Is Stored This Way

Depth is not a normal RGB image:

- it must preserve `uint16`
- lossy video encoding would damage values

So this path keeps RGB and depth separated by storage type while preserving the
same frame-level logical sample.
