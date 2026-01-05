# UGL

Universal GAM Launcher for Windows.

## Python version

This repository now includes a Python implementation that mirrors the PowerShell launcher
while splitting the logic into a structured project.

### Run

```bash
python -m ugl
```

### Layout

- `ugl/config.py` – default paths and configuration
- `ugl/json_store.py` – JSON load/save and backups
- `ugl/filesystem.py` – filesystem helpers and template cloning
- `ugl/launcher.py` – menu flow and command session
