# GR00T WholeBodyControl Bring-Up Notes

This file captures the environment-specific fixes and validation steps that were required to bring up `gear_sonic_deploy` on this machine. Use it as a checklist when configuring another computer.

## Scope

These notes are for `gear_sonic_deploy` only.

Main issues encountered:

1. Shell mismatch (`zsh` terminal, but scripts assume `bash`)
2. ROS include path pollution during CMake configure/build
3. ONNX Runtime header/library version mismatch
4. Runtime DDS library mismatch (`libddsc` / `libddscxx`)
5. DDS domain creation failures in `sim` mode on loopback

## Assumed Host Environment

Tested host assumptions on this machine:

1. Ubuntu Linux
2. CUDA toolkit available at `/usr/local/cuda`
3. ROS 2 Humble installed under `/opt/ros/humble`
4. ONNX Runtime installed under `/opt/onnxruntime`
5. TensorRT unpacked under `$HOME/TensorRT`

## Shell Rules

The scripts are written for `bash`.

Use these rules:

1. Run scripts with `bash`, even if your interactive shell is `zsh`
2. Do not `source scripts/setup_env.sh` directly from `zsh`
3. Set persistent environment variables in your real shell rc file

For `zsh`:

```bash
echo 'export TensorRT_ROOT=$HOME/TensorRT' >> ~/.zshrc
source ~/.zshrc
```

Recommended execution pattern:

```bash
bash -lc 'cd /path/to/GR00T-WholeBodyControl/gear_sonic_deploy && source scripts/setup_env.sh && just build'
```

## Required Source Patches

These source changes are required to avoid ROS include collisions.

### 1. Filter ROS include subdirectories

File: `gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/cmake/ROS2.cmake`

Problem:

`ROS2.cmake` originally appended `/opt/ros/<distro>/include` and every child directory to the compiler include path. That accidentally pulled in:

1. `dds`, `ddsc`, `ddscxx`
2. `idl`
3. `onnxruntime`
4. `unitree`

This caused:

1. `features.h` collisions with glibc
2. `unitree` header collisions with bundled `unitree_sdk2`
3. ONNX Runtime API 20 headers from ROS mixing with ONNX Runtime 1.16.3 from `/opt/onnxruntime`

Patch:

```cmake
set(ROS2_INCLUDE_DIRS "")
file(GLOB ROS2_INCLUDE_SUBDIRS "${ros2_include_path}/*")
foreach(subdir ${ROS2_INCLUDE_SUBDIRS})
  if(IS_DIRECTORY ${subdir})
    get_filename_component(subdir_name "${subdir}" NAME)
    if(subdir_name STREQUAL "dds" OR
       subdir_name STREQUAL "ddsc" OR
       subdir_name STREQUAL "ddscxx" OR
       subdir_name STREQUAL "idl" OR
       subdir_name STREQUAL "onnxruntime" OR
       subdir_name STREQUAL "unitree")
      continue()
    endif()
    list(APPEND ROS2_INCLUDE_DIRS ${subdir})
  endif()
endforeach()
```

### 2. Prefer bundled Unitree headers

File: `gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/CMakeLists.txt`

Problem:

Even after filtering ROS includes, explicit `#include <unitree/...>` can still resolve to ROS-installed headers if include priority is wrong.

Patch:

```cmake
target_include_directories(${EXECUTABLE_NAME} BEFORE PRIVATE ${PROJECT_SOURCE_DIR}/thirdparty/unitree_sdk2/include)
```

This forces the build to use the repo's bundled Unitree SDK headers first.

## Build-Time Validation

After patching, use a clean rebuild:

```bash
cd /path/to/GR00T-WholeBodyControl/gear_sonic_deploy
rm -rf build
rm -f target/release/g1_deploy_onnx_ref
bash -lc 'source scripts/setup_env.sh && just build'
```

Expected result:

1. Build completes successfully
2. No `__GLIBC_PREREQ` compile errors
3. No `ORT API version [20]` mismatch during runtime caused by build products

## ONNX Runtime Rule

This machine has two ONNX Runtime installations:

1. ROS copy under `/opt/ros/humble/include/onnxruntime` with `ORT_API_VERSION 20`
2. Local copy under `/opt/onnxruntime` with ONNX Runtime `1.16.3` and `ORT_API_VERSION 16`

The executable must use `/opt/onnxruntime` consistently.

Checks:

```bash
rg -n "#define ORT_API_VERSION" /opt/onnxruntime/include/onnxruntime_c_api.h
rg -n "#define ORT_API_VERSION" /opt/ros/humble/include/onnxruntime/onnxruntime_c_api.h
ldd target/release/g1_deploy_onnx_ref | grep onnxruntime
```

Expected runtime link:

```bash
libonnxruntime.so.1.16.3 => /opt/onnxruntime/lib/libonnxruntime.so.1.16.3
```

## Runtime DDS Rule

The executable must use the bundled DDS libraries from `unitree_sdk2`, not the ROS copies.

Without this, runtime can crash with:

1. `free(): invalid next size (fast)`
2. `corrupted size vs. prev_size`

Root cause:

`scripts/setup_env.sh` sources ROS, which adds ROS library paths to `LD_LIBRARY_PATH`. If ROS `libddsc.so.0` and `libddscxx.so.0` load first, ABI mismatches occur.

### Required runtime override

Before running `deploy.sh`, prepend the bundled DDS library path:

```bash
cd /path/to/GR00T-WholeBodyControl/gear_sonic_deploy
export TensorRT_ROOT=$HOME/TensorRT
export LD_LIBRARY_PATH="$PWD/thirdparty/unitree_sdk2/thirdparty/lib/x86_64:$LD_LIBRARY_PATH"
```

Verify:

```bash
ldd target/release/g1_deploy_onnx_ref | egrep 'libddsc|libddscxx'
```

Expected:

```bash
libddsc.so.0 => .../gear_sonic_deploy/thirdparty/unitree_sdk2/thirdparty/lib/x86_64/libddsc.so.0
libddscxx.so.0 => .../gear_sonic_deploy/thirdparty/unitree_sdk2/thirdparty/lib/x86_64/libddscxx.so.0
```

If `ldd` shows `/opt/ros/humble/...`, fix `LD_LIBRARY_PATH` before running.

## Recommended Run Commands

### Build

```bash
cd /path/to/GR00T-WholeBodyControl/gear_sonic_deploy
export TensorRT_ROOT=$HOME/TensorRT
bash -lc 'source scripts/setup_env.sh && just build'
```

### Sim bring-up (minimal path)

Use ZMQ-only first to reduce the number of moving parts:

```bash
cd /path/to/GR00T-WholeBodyControl/gear_sonic_deploy
export TensorRT_ROOT=$HOME/TensorRT
export LD_LIBRARY_PATH="$PWD/thirdparty/unitree_sdk2/thirdparty/lib/x86_64:$LD_LIBRARY_PATH"
bash deploy.sh sim --input-type zmq --output-type zmq
```

### Real bring-up

`deploy.sh real` does not edit any robot config files. It only:

1. Auto-selects an interface on `192.168.123.x` if available
2. Builds the local binary
3. Runs `g1_deploy_onnx_ref` with the selected interface and current CLI options

Recommended:

```bash
cd /path/to/GR00T-WholeBodyControl/gear_sonic_deploy
export TensorRT_ROOT=$HOME/TensorRT
export LD_LIBRARY_PATH="$PWD/thirdparty/unitree_sdk2/thirdparty/lib/x86_64:$LD_LIBRARY_PATH"
bash deploy.sh real
```

## Known Remaining Runtime Issue

After the fixes above, `sim` mode may still fail with a clean DDS error:

1. `failed to enumerate interfaces for "udp": -1`
2. `Failed to create domain explicitly`

This is a separate issue from the earlier heap corruption. It indicates CycloneDDS domain creation is failing on the host network environment, often when using the loopback interface.

Meaning:

1. The compile-time and ABI mismatches are fixed
2. The remaining blocker is DDS/network setup, not ONNX Runtime or the ROS include patch

## Quick Debug Checklist

Run these in order on a new machine:

```bash
cd /path/to/GR00T-WholeBodyControl/gear_sonic_deploy
echo "$TensorRT_ROOT"
ldd target/release/g1_deploy_onnx_ref | grep onnxruntime
ldd target/release/g1_deploy_onnx_ref | egrep 'libddsc|libddscxx'
```

Expected:

1. `TensorRT_ROOT` points to a real TensorRT directory
2. `onnxruntime` resolves to `/opt/onnxruntime/lib/libonnxruntime.so.1.16.3`
3. `libddsc` and `libddscxx` resolve to `thirdparty/unitree_sdk2/thirdparty/lib/x86_64`

If any of these fail, do not keep debugging application logic. Fix the environment first.
