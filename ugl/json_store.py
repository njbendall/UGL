from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .environment import Environment


def ensure_json_exists(json_path: Path) -> None:
    if not json_path.exists():
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps({"Environments": []}, indent=2), encoding="utf-8")


def load_json(json_path: Path) -> dict[str, Any] | None:
    try:
        content = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    environments = content.get("Environments")
    if environments is None:
        content["Environments"] = []
    elif isinstance(environments, dict):
        content["Environments"] = [environments]
    elif isinstance(environments, str):
        content["Environments"] = []
    elif not isinstance(environments, list):
        try:
            content["Environments"] = list(environments)
        except TypeError:
            content["Environments"] = []

    return content


def save_json(json_path: Path, backup_root: Path, data: dict[str, Any]) -> Path | None:
    backup_path: Path | None = None
    if json_path.exists():
        backup_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_root / f"GAM_Clients_{timestamp}.json"
        backup_path.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")

    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return backup_path


def set_environments(data: dict[str, Any], environments: list[Environment]) -> dict[str, Any]:
    data["Environments"] = [asdict(env) for env in environments]
    return data
