# Agent Notes For `gear_sonic_deploy`

## Validation Environment

All automated verification in this repo should run inside:

```bash
source .venv_teleop/bin/activate
```

Do not use the system Python or a different virtual environment for:

- import checks
- smoke tests
- script validation
- GUI launch checks
- pip installs related to collector-side Python code

Recommended execution pattern:

```bash
bash -lc 'cd /home/yangke/KY/GR00T-WholeBodyControl && source .venv_teleop/bin/activate && <command>'
```

## ROS Commands

If a validation command also needs ROS 2, keep `.venv_teleop` as the active
Python environment and then source ROS:

```bash
bash -lc "cd /home/yangke/KY/GR00T-WholeBodyControl && \
source .venv_teleop/bin/activate && \
source /opt/ros/humble/setup.bash && \
<command>"
```

## Package Installation Rule

When installing Python packages for collector-side tools, always install into
`.venv_teleop`:

```bash
bash -lc 'cd /home/yangke/KY/GR00T-WholeBodyControl && source .venv_teleop/bin/activate && python -m pip install -r gear_sonic_deploy/sonic_data/requirements.txt'
```

Use `python -m pip`, not bare `pip`.
