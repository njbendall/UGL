from __future__ import annotations

import re
import shutil
from pathlib import Path


def normalise_path(path_value: str | None) -> str | None:
    if path_value is None:
        return None
    clean = path_value.strip().strip('"').replace("/", "\\")
    return clean


def ensure_directories(*paths: Path) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def gam_exe_exists(folder: Path) -> bool:
    return (folder / "gam.exe").exists()


def safe_folder_key(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\- ]", "", name)
    return re.sub(r"\s+", "", cleaned)


def ensure_gam_structure(base_path: Path) -> Path:
    gam_dir = base_path / ".gam"
    ensure_directories(gam_dir, gam_dir / "gamcache", gam_dir / "drive")
    return gam_dir


def remove_oauth_tokens(gam_dir: Path) -> None:
    for token in (gam_dir / "oauth2.txt", gam_dir / "oauth2service.json"):
        if token.exists():
            token.unlink()


def clone_template(template_source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in template_source.iterdir():
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
