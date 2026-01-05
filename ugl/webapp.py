from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for

from .services import (
    ConfigManager,
    EnvironmentNotFoundError,
    EnvironmentPathError,
    LauncherService,
    LauncherServiceError,
)


@dataclass
class CommandTask:
    task_id: str
    environment: str
    command: str
    status: str = "queued"
    output: list[str] = field(default_factory=list)
    error: str | None = None


class TaskLogger:
    def __init__(self, task: CommandTask) -> None:
        self.task = task

    def info(self, message: str) -> None:
        self.task.output.append(message)


class TaskManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, CommandTask] = {}

    def start(self, service: LauncherService, environment: str, command: str) -> CommandTask:
        task_id = uuid.uuid4().hex
        task = CommandTask(task_id=task_id, environment=environment, command=command, status="running")
        with self._lock:
            self._tasks[task_id] = task
        thread = threading.Thread(
            target=self._run_task,
            args=(task, service),
            daemon=True,
        )
        thread.start()
        return task

    def list_tasks(self) -> list[CommandTask]:
        with self._lock:
            return list(self._tasks.values())

    def _run_task(self, task: CommandTask, service: LauncherService) -> None:
        logger = TaskLogger(task)
        try:
            env = service.get_environment_by_name(task.environment)
            session = service.prepare_session(env)
            service.run_command(session, task.command, logger)
            task.status = "completed"
        except (EnvironmentNotFoundError, EnvironmentPathError) as exc:
            task.status = "failed"
            task.error = str(exc)
        except LauncherServiceError as exc:
            task.status = "failed"
            task.error = str(exc)


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY="ugl",
        UGL_BASE_DIR=Path.cwd(),
    )
    if config_overrides:
        app.config.update(config_overrides)

    app.extensions["config_manager"] = ConfigManager(
        base_dir=Path(app.config["UGL_BASE_DIR"])
    )
    app.extensions["task_manager"] = TaskManager()

    @app.get("/")
    def index():
        service = _get_service(app)
        environments = service.list_environments()
        tasks = app.extensions["task_manager"].list_tasks()
        return render_template("index.html", environments=environments, tasks=tasks)

    @app.post("/launch")
    def launch():
        environment = request.form.get("environment", "").strip()
        command = request.form.get("command", "").strip()
        if not environment or not command:
            flash("Environment and command are required.")
            return redirect(url_for("index"))

        service = _get_service(app)
        task = app.extensions["task_manager"].start(service, environment, command)
        flash(f"Launch started for {task.environment}.")
        return redirect(url_for("index"))

    @app.get("/config")
    def config():
        manager = app.extensions["config_manager"]
        config_state = manager.load()
        override_path = manager.override_path
        return render_template(
            "config.html",
            config=config_state,
            override_path=override_path,
        )

    @app.post("/config")
    def update_config():
        manager = app.extensions["config_manager"]
        updates = {
            "template_path": request.form.get("template_path", "").strip(),
            "clients_root": request.form.get("clients_root", "").strip(),
            "log_root": request.form.get("log_root", "").strip(),
        }
        manager.update_overrides(updates)
        flash("Configuration updated.")
        return redirect(url_for("config"))

    return app


def _get_service(app: Flask) -> LauncherService:
    config_manager = app.extensions["config_manager"]
    return LauncherService(config_manager.load())


app = create_app()
