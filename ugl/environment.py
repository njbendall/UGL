from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .filesystem import normalise_path


@dataclass
class Environment:
    name: str
    path: str
    admin: str | None = None
    color: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Environment":
        return cls(
            name=str(data.get("Name", "")),
            path=str(data.get("Path", "")),
            admin=data.get("Admin"),
            color=data.get("Color"),
        )


def load_environments(data: dict[str, Any]) -> list[Environment]:
    environments = data.get("Environments") or []
    return [Environment.from_dict(item) for item in environments]


def sanitise_environment_paths(environments: list[Environment]) -> list[tuple[int, str, str, str]]:
    issues: list[tuple[int, str, str, str]] = []
    for index, env in enumerate(environments):
        clean = normalise_path(env.path) or ""
        if env.path != clean:
            issues.append((index, env.name, env.path, clean))
    return issues
