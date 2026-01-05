from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LauncherConfig:
    config_root: Path
    json_path: Path
    log_root: Path
    template_path: Path
    json_backup_root: Path
    clients_root: Path

    @classmethod
    def default(cls) -> "LauncherConfig":
        config_root = Path("C:/EDUIT/GAM_Configs")
        json_path = config_root / "GAM_Clients.json"
        log_root = Path("C:/EDUIT/Logs/PowerShell")
        template_path = config_root / "GAM-Template"
        json_backup_root = config_root / "GAM-JSONBackups"
        clients_root = config_root / "GAM-Clients"
        return cls(
            config_root=config_root,
            json_path=json_path,
            log_root=log_root,
            template_path=template_path,
            json_backup_root=json_backup_root,
            clients_root=clients_root,
        )
