#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="/home/yangke/KY/GR00T-WholeBodyControl"
DEPLOY_DIR="$REPO_ROOT/gear_sonic_deploy"

cd "$DEPLOY_DIR"

# Source the deploy environment in the current shell so exported vars apply below.
# source scripts/setup_env.sh
bash -lc 'source scripts/setup_env.sh'

export LD_LIBRARY_PATH="$PWD/thirdparty/unitree_sdk2/thirdparty/lib/x86_64:${LD_LIBRARY_PATH:-}"

ldd target/release/g1_deploy_onnx_ref | egrep 'libddsc|libddscxx'
