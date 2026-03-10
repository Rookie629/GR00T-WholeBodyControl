# Sonic Data Utilities

## Purpose

This directory holds the minimal Python utilities needed to run the
`gear_sonic_deploy` RGBD collection helpers without importing runtime support
code from `decoupled_wbc`.

It contains:

- ROS topic constants
- ROS msgpack subscribers and service client helpers
- typed RGB/depth ZMQ transport
- a minimal bridged-camera client
- keyboard topic subscriber used by sidecar tools
- a thin exporter entrypoint wrapper

## Scope

This is a minimal migration layer, not a full replacement for the
`decoupled_wbc` dataset exporter stack.

What moved locally:

- bridge/runtime helper dependencies used by `gear_sonic_deploy/image_server`

What still remains outside this folder:

- the existing LeRobot exporter backend in `decoupled_wbc`

That split keeps the migration small while removing the most awkward
cross-package imports from the `gear_sonic_deploy` tools.
