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

from decoupled_wbc.control.main.teleop.configs.configs import DataExporterConfig
from decoupled_wbc.control.main.teleop.run_g1_data_exporter import main


if __name__ == "__main__":
    config = tyro.cli(DataExporterConfig)
    main(config)
