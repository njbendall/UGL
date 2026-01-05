from __future__ import annotations

from pathlib import Path

from ugl.config import LauncherConfig
from ugl.services import LauncherService


def _write_template(template_path: Path) -> None:
    template_path.mkdir(parents=True, exist_ok=True)
    (template_path / "gam.exe").write_text("stub", encoding="utf-8")
    (template_path / "readme.txt").write_text("template", encoding="utf-8")


def test_create_and_delete_environment(tmp_path: Path) -> None:
    config = LauncherConfig.default(base_dir=tmp_path)
    _write_template(config.template_path)

    service = LauncherService(config)
    result = service.create_environment("Test Env", admin="admin@example.com", color="Blue")

    assert result.environment.name == "Test Env"
    assert Path(result.environment.path).exists()
    assert (Path(result.environment.path) / "gam.exe").exists()

    environments = service.list_environments()
    assert len(environments) == 1
    assert environments[0].name == "Test Env"

    delete_result = service.delete_environment("Test Env", delete_folder=True)
    assert delete_result.backup_path is not None
    assert not Path(result.environment.path).exists()


def test_validate_paths_updates_json(tmp_path: Path) -> None:
    config = LauncherConfig.default(base_dir=tmp_path)
    _write_template(config.template_path)

    service = LauncherService(config)
    service.create_environment("Sample Env")

    result = service.validate_paths()
    assert result.issues

    applied = service.validate_paths(apply_changes=True)
    assert applied.applied
