#!/usr/bin/env python3
"""Thin exporter entrypoint under gear_sonic_deploy.

This keeps the user-facing launch path inside `gear_sonic_deploy` while the
current exporter backend is still provided by `decoupled_wbc`.
"""

from __future__ import annotations

from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import tyro

from gear_sonic_deploy.sonic_data.collector import main, prepare_interactive_config
from gear_sonic_deploy.sonic_data.configs import DataExporterConfig


if __name__ == "__main__":
    config = tyro.cli(DataExporterConfig)
    config = prepare_interactive_config(config)
    main(config)
