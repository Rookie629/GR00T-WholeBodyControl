# Vuer Monocular Ego Camera Prototype

This directory contains a minimal but runnable prototype for streaming a monocular RGB camera feed into a browser using `vuer` and `ImageBackground`.

The default input now matches the current `sonic_data` GUI preview source exactly:

- `ComposedCameraClientSensor`
- bridged image stream
- `ego_view`
- default endpoint `127.0.0.1:5560`

## Architecture

Pipeline:

1. A frame provider reads camera frames in Python.
2. A background reader thread keeps the latest frame available.
3. The Vuer session loop pulls the latest frame at a throttled FPS.
4. Preprocessing converts BGR to RGB when needed and resizes the frame.
5. The frame is upserted into `bgChildren` as `ImageBackground`.
6. The browser renders the frame as a camera-facing HUD/background.

This milestone intentionally uses JPEG-over-WebSocket for simplicity and debuggability.

## Files

- `config.py`: CLI and runtime configuration
- `frame_source.py`: generic frame-source interface, GUI-matching bridge source, and OpenCV fallback
- `preprocess.py`: color conversion, validation, and resize
- `vuer_app.py`: Vuer session loop and `ImageBackground` upserts
- `main.py`: runnable entrypoint

## Dependencies

Mandatory:

```bash
python3 -m pip install --upgrade pip
python3 -m pip install "vuer==0.1.4" "numpy>=1.24,<2.0"
python3 -m pip install "opencv-python>=4.9,<5.0" "pyzmq>=25,<27" "msgpack>=1,<2" "msgpack-numpy>=0.4,<1"
```

If you do not want GUI OpenCV bindings on Linux, use this instead of `opencv-python`:

```bash
python3 -m pip install "opencv-python-headless>=4.9,<5.0"
```

Optional but useful:

```bash
python3 -m pip install "ipython>=8,<9"
```

## Run

From the repo root:

First make sure the same bridge used by the GUI is running and publishing to `127.0.0.1:5560`.

Then run:

```bash
python3 -m gear_sonic_deploy.vuer_ego_stream.main
```

Example with the same GUI-style source but explicit tuning:

```bash
python3 -m gear_sonic_deploy.vuer_ego_stream.main \
  --source-type sonic_bridge \
  --camera-host 127.0.0.1 \
  --camera-port 5560 \
  --output-width 960 \
  --output-height 540 \
  --fps 15 \
  --jpeg-quality 70 \
  --host 0.0.0.0 \
  --port 8012 \
  --distance-to-camera 1.0 \
  --position 0 0 -3
```

OpenCV fallback remains available for local-only debugging:

```bash
python3 -m gear_sonic_deploy.vuer_ego_stream.main \
  --source-type opencv \
  --source 0 \
  --input-color-space bgr
```

## Open In Browser

Local desktop browser options:

1. Open the local page:

```text
http://127.0.0.1:8012
```

2. Or use the hosted Vuer client with an explicit websocket query:

```text
https://vuer.ai?ws=ws://127.0.0.1:8012
```

The app logs both URLs on startup.

## Tuning

Edit defaults in `config.py`, or override via CLI:

- `--source`
- `--source-type`
- `--camera-host`
- `--camera-port`
- `--input-color-space`
- `--output-width`
- `--output-height`
- `--capture-width`
- `--capture-height`
- `--fps`
- `--jpeg-quality`
- `--host`
- `--port`
- `--distance-to-camera`
- `--position`
- `--no-fixed`
- `--no-interpolate`

## Pico Later

Do not use WebRTC yet for this milestone.

For later Pico testing:

1. Bind the server on `0.0.0.0`.
2. Expose the websocket securely as `wss://...` using a tunnel or reverse proxy.
3. Open the headset browser at:

```text
https://vuer.ai?ws=wss://YOUR_PUBLIC_ENDPOINT
```

This matches the official Vuer guidance that headsets generally need `wss://` rather than plain `ws://`.

## Debug Checklist

If no frames arrive:

- Verify `composed_camera_bridge.py` is running on the same host/port as the GUI.
- Verify the GUI itself can already see frames from `127.0.0.1:5560`.
- Verify the camera can be opened by OpenCV.
- If using OpenCV fallback, check that `--source` is correct.
- Watch for `Frame source returned no frame` warnings.

If colors are wrong:

- Switch `--input-color-space` between `bgr` and `rgb`.
- OpenCV capture usually needs `bgr`.

If the page loads but the image does not update:

- Confirm logs show `Vuer stats: effective_fps=...`
- Confirm logs show `First Vuer frame prepared`.
- Try the explicit hosted-client URL: `https://vuer.ai?ws=ws://127.0.0.1:8012`

If performance is poor:

- Lower `--output-width` and `--output-height`
- Lower `--fps`
- Lower `--jpeg-quality`
- Use `opencv-python-headless` on headless systems

## Upgrade Path

The module boundaries are set up so you can later:

- keep `frame_source.py` for monocular, stereo, ROS2, or RealSense providers
- keep `preprocess.py` for color conversion and resize
- replace only the Vuer presentation layer in `vuer_app.py`

That means the later move to `WebRTCVideoPlane` or stereo streaming should mostly be a transport/view rewrite, not a full pipeline rewrite.
