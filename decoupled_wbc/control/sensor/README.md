# Sensor Transport

## Purpose

This directory contains the transport layer between camera producers and camera
consumers in `decoupled_wbc`.

For the G1 D435 workflow, the important file is `sensor_server.py`, which
defines the wire format used by the bridge and by `ComposedCameraClientSensor`.

## Changes In This Work

The original transport path assumed RGB-like images. This work extended it to
carry typed images so RGB and depth can travel through the same message schema.

Updated behavior in `sensor_server.py`:

- `ImageMessageSchema.serialize()` now encodes each image with an explicit
  encoding descriptor
- `ImageMessageSchema.deserialize()` accepts both:
  - old-style RGB string payloads
  - new typed payloads
- `ImageUtils` now supports:
  - JPEG base64 for RGB
  - PNG base64 for `uint16` depth

## Why This Matters

Without this change, the existing camera client path could transport RGB but had
no safe way to preserve D435 depth as `uint16`.

With the typed message path:

- RGB stays compressed as JPEG
- depth stays lossless through PNG encoding
- downstream code receives the correct dtype again after deserialization

## Expected Message Shape

Each message contains:

- `timestamps`
  - keyed by image name
- `images`
  - keyed by image name
  - value is either legacy string payload or typed payload

Typed payload format:

```python
{
    "encoding": "jpg_base64" | "png_depth_base64",
    "data": "<base64>"
}
```

## Compatibility

This transport remains backward compatible with existing RGB-only producers that
send plain strings.
