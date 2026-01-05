from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .config import LauncherConfig
from .environment import Environment, load_environments, sanitise_environment_paths
from .filesystem import (
    clone_template,
    ensure_directories,
    ensure_gam_structure,
    normalise_path,
    remove_oauth_tokens,
    safe_folder_key,
)
from .json_store import ensure_json_exists, load_json, save_json, set_environments

GAM_COMMANDS = {
    "adminrole",
    "alert",
    "alias",
    "browser",
    "building",
    "chatevent",
    "chatmember",
    "chatmessage",
    "chatspace",
    "chromeapp",
    "chromeprofile",
    "chromeprofilecommand",
    "chromeschema",
    "cigroup",
    "cigroupmembers",
    "contact",
    "course",
    "courses",
    "cros",
    "crostelemetry",
    "currentprojectid",
    "customer",
    "datatransfer",
    "device",
    "deviceuser",
    "deviceuserstate",
    "domain",
    "domainalias",
    "domaincontact",
    "drivefileacl",
    "drivelabel",
    "group",
    "groupmembers",
    "inboundssoassignment",
    "inboundssocredential",
    "inboundssoprofile",
    "instance",
    "mobile",
    "org",
    "orgs",
    "peoplecontact",
    "peopleprofile",
    "policy",
    "printer",
    "resoldcustomer",
    "resoldsubscription",
    "resource",
    "resources",
    "schema",
    "shareddrive",
    "site",
    "siteacl",
    "user",
    "userinvitation",
    "users",
    "vaultexport",
    "vaulthold",
    "vaultmatter",
    "vaultquery",
    "verify",
}

CONFIG_OVERRIDE_FILENAME = "launcher_config.json"


class LauncherServiceError(Exception):
    pass


class EnvironmentExistsError(LauncherServiceError):
    pass


class EnvironmentNotFoundError(LauncherServiceError):
    pass


class EnvironmentPathError(LauncherServiceError):
    pass


@dataclass(frozen=True)
class PathIssue:
    index: int
    name: str
    original: str
    clean: str


@dataclass(frozen=True)
class CreateEnvironmentResult:
    environment: Environment
    backup_path: Path | None
    template_source: Path | None
    gam_exe_present: bool
    warnings: list[str]


@dataclass(frozen=True)
class DeleteEnvironmentResult:
    backup_path: Path | None
    folder_deleted: bool


@dataclass(frozen=True)
class ValidationResult:
    issues: list[PathIssue]
    applied: bool
    backup_path: Path | None


@dataclass(frozen=True)
class EnvironmentSession:
    environment: Environment
    gam_path: Path
    gam_dir: Path
    gam_exe: Path
    gam_available: bool
    session_env: dict[str, str]


def script_directory() -> Path | None:
    candidates = [
        Path(__file__).resolve(),
        Path(os.path.abspath(os.sys.argv[0])) if os.sys.argv else None,
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        if candidate.exists():
            return candidate.parent
    return None


def select_template_source(template_path: Path) -> Path | None:
    if (template_path / "gam.exe").exists():
        return template_path
    if template_path.exists():
        for child in template_path.iterdir():
            if child.is_dir() and (child / "gam.exe").exists():
                return child
    return None


def run_subprocess(command: list[str], env: dict[str, str], cwd: Path, logger) -> int:
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if process.stdout:
        for line in process.stdout:
            logger.info(line.rstrip())
    return process.wait()


def run_shell_command(command: str, env: dict[str, str], cwd: Path, logger) -> int:
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        shell=True,
    )
    if process.stdout:
        for line in process.stdout:
            logger.info(line.rstrip())
    return process.wait()


class ConfigManager:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path.cwd()

    @property
    def override_path(self) -> Path:
        config_root = LauncherConfig.default(self.base_dir).config_root
        return config_root / CONFIG_OVERRIDE_FILENAME

    def load(self) -> LauncherConfig:
        config = LauncherConfig.default(self.base_dir)
        overrides = self._read_overrides()
        if overrides:
            config = LauncherConfig(
                config_root=config.config_root,
                json_path=Path(overrides.get("json_path", config.json_path)),
                log_root=Path(overrides.get("log_root", config.log_root)),
                template_path=Path(overrides.get("template_path", config.template_path)),
                json_backup_root=Path(overrides.get("json_backup_root", config.json_backup_root)),
                clients_root=Path(overrides.get("clients_root", config.clients_root)),
            )
        return config

    def update_overrides(self, updates: dict[str, str]) -> LauncherConfig:
        overrides = self._read_overrides()
        for key, value in updates.items():
            if value:
                overrides[key] = value
            else:
                overrides.pop(key, None)
        self.override_path.parent.mkdir(parents=True, exist_ok=True)
        self.override_path.write_text(json.dumps(overrides, indent=2), encoding="utf-8")
        return self.load()

    def _read_overrides(self) -> dict[str, str]:
        if not self.override_path.exists():
            return {}
        try:
            data = json.loads(self.override_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(key): str(value) for key, value in data.items()}


class LauncherService:
    def __init__(self, config: LauncherConfig) -> None:
        self.config = config
        ensure_directories(config.config_root, config.log_root, config.json_backup_root)
        ensure_json_exists(config.json_path)

    def list_environments(self) -> list[Environment]:
        data = self._load_data()
        return load_environments(data)

    def get_environment_by_name(self, name: str) -> Environment:
        environments = self.list_environments()
        for env in environments:
            if env.name.lower() == name.lower():
                return env
        raise EnvironmentNotFoundError(f"Environment '{name}' not found.")

    def create_environment(
        self, name: str, admin: str | None = None, color: str | None = None
    ) -> CreateEnvironmentResult:
        data = self._load_data()
        environments = load_environments(data)
        safe_key = safe_folder_key(name)
        path = self.config.clients_root / safe_key

        for env in environments:
            if env.name == name or normalise_path(env.path) == str(path):
                raise EnvironmentExistsError("Environment already exists.")

        ensure_directories(path)

        warnings: list[str] = []
        template_source = select_template_source(self.config.template_path)
        if template_source:
            try:
                clone_template(template_source, path)
            except OSError as exc:
                warnings.append(f"Template copy failed: {exc}")
        else:
            warnings.append("No valid GAM template found.")

        gam_dir = ensure_gam_structure(path)
        remove_oauth_tokens(gam_dir)

        environment = Environment(name=name, path=str(path), admin=admin, color=color)
        environments.append(environment)
        set_environments(data, environments)
        backup_path = save_json(self.config.json_path, self.config.json_backup_root, data)
        return CreateEnvironmentResult(
            environment=environment,
            backup_path=backup_path,
            template_source=template_source,
            gam_exe_present=(path / "gam.exe").exists(),
            warnings=warnings,
        )

    def delete_environment(self, name: str, delete_folder: bool = False) -> DeleteEnvironmentResult:
        data = self._load_data()
        environments = load_environments(data)
        target = next((env for env in environments if env.name == name), None)
        if target is None:
            raise EnvironmentNotFoundError("Environment not found.")

        environments = [env for env in environments if env.name != target.name]
        set_environments(data, environments)
        backup_path = save_json(self.config.json_path, self.config.json_backup_root, data)

        folder_deleted = False
        if delete_folder and Path(target.path).exists():
            try:
                shutil.rmtree(Path(target.path))
                folder_deleted = True
            except OSError:
                folder_deleted = False

        return DeleteEnvironmentResult(
            backup_path=backup_path,
            folder_deleted=folder_deleted,
        )

    def validate_paths(self, apply_changes: bool = False) -> ValidationResult:
        data = self._load_data()
        environments = load_environments(data)
        issues_raw = sanitise_environment_paths(environments)
        issues = [PathIssue(*issue) for issue in issues_raw]

        backup_path: Path | None = None
        applied = False
        if apply_changes and issues:
            for issue in issues:
                environments[issue.index].path = issue.clean
            set_environments(data, environments)
            backup_path = save_json(self.config.json_path, self.config.json_backup_root, data)
            applied = True

        return ValidationResult(issues=issues, applied=applied, backup_path=backup_path)

    def prepare_session(self, env: Environment) -> EnvironmentSession:
        gam_path = Path(normalise_path(env.path) or env.path)
        if not gam_path.exists():
            raise EnvironmentPathError(f"Environment folder does not exist: {gam_path}")

        gam_dir = ensure_gam_structure(gam_path)
        gam_exe = gam_path / "gam.exe"

        session_env = os.environ.copy()
        session_env["GAMCFGDIR"] = str(gam_dir)

        return EnvironmentSession(
            environment=env,
            gam_path=gam_path,
            gam_dir=gam_dir,
            gam_exe=gam_exe,
            gam_available=gam_exe.exists(),
            session_env=session_env,
        )

    def run_command(self, session: EnvironmentSession, raw_command: str, logger) -> int:
        args = shlex.split(raw_command)
        if not args:
            return 0

        command_root = args[0].lower()
        use_gam = command_root == "gam" or command_root in GAM_COMMANDS

        if use_gam:
            if command_root == "gam":
                args = args[1:]
                if not args:
                    logger.info("No GAM command provided.")
                    return 0
            if session.gam_available:
                return run_subprocess([str(session.gam_exe)] + args, session.session_env, session.gam_path, logger)
            logger.info("gam.exe is not available for this environment.")
            return 1

        return run_shell_command(raw_command, session.session_env, session.gam_path, logger)

    def _load_data(self) -> dict:
        data = load_json(self.config.json_path)
        if data is None:
            raise LauncherServiceError("Error loading JSON configuration.")
        return data


def format_environment_list(environments: Iterable[Environment]) -> list[str]:
    return [f"{env.name} - {normalise_path(env.path)}" for env in environments]
