from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("flask")

from ugl.config import LauncherConfig
from ugl.services import LauncherService
from ugl.webapp import create_app


def _write_template(template_path: Path) -> None:
    template_path.mkdir(parents=True, exist_ok=True)
    (template_path / "gam.exe").write_text("stub", encoding="utf-8")


def test_web_routes(tmp_path: Path) -> None:
    config = LauncherConfig.default(base_dir=tmp_path)
    _write_template(config.template_path)
    service = LauncherService(config)
    service.create_environment("Web Env")

    app = create_app({"TESTING": True, "UGL_BASE_DIR": tmp_path, "SECRET_KEY": "test"})
    client = app.test_client()

    response = client.get("/")
    assert response.status_code == 200

    response = client.get("/config")
    assert response.status_code == 200

    response = client.post(
        "/launch",
        data={"environment": "Web Env", "command": "echo hello"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    tasks = app.extensions["task_manager"].list_tasks()
    assert tasks
