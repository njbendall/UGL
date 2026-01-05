from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable

from .config import LauncherConfig
from .environment import Environment, load_environments
from .filesystem import normalise_path, safe_folder_key
from .json_store import load_json
from .logging_utils import TranscriptLogger
from .services import (
    EnvironmentExistsError,
    EnvironmentNotFoundError,
    EnvironmentPathError,
    GAM_COMMANDS,
    LauncherService,
    script_directory,
)


def _display_banner(logger) -> None:
    logger.info("------------------------------------------------------------")
    logger.info("Universal GAM Launcher v4.6")
    logger.info("Created by Danny and Lewis")
    logger.info("------------------------------------------------------------")
    logger.info("")


def _show_menu(logger, environments: Iterable[Environment]) -> None:
    _display_banner(logger)
    env_list = list(environments)
    if not env_list:
        logger.info("No environments configured.")
        logger.info("")
    else:
        logger.info("Configured Environments:")
        for index, env in enumerate(env_list, start=1):
            logger.info(f"[{index}] {env.name} - {normalise_path(env.path)}")
        logger.info("")

    logger.info("[N] Create New Environment")
    logger.info("[D] Delete Existing Environment")
    logger.info("[V] Validate / Sanitise JSON")
    logger.info("[Q] Quit")
    logger.info("")


def _prompt(prompt: str) -> str:
    return input(prompt)


def _create_environment(service: LauncherService, logger) -> None:
    logger.info("")
    logger.info("Create New GAM Environment")
    logger.info("-------------------------------------------")

    name = _prompt("Enter Environment Name (e.g., WMAT-ROD - Rodborough School): ").strip()
    if not name:
        logger.info("Name required.")
        return

    logger.info("Auto-generated folder:")
    logger.info(f"  {service.config.clients_root / safe_folder_key(name)}")

    admin = _prompt("Enter Google Admin Email (optional): ").strip() or None
    color = _prompt("Enter Display Colour (optional): ").strip() or None

    try:
        result = service.create_environment(name=name, admin=admin, color=color)
    except EnvironmentExistsError as exc:
        logger.info(str(exc))
        return

    logger.info("")
    logger.info(f"Using template: {service.config.template_path}")
    if result.template_source:
        logger.info(f"Cloning template from: {result.template_source}")
    for warning in result.warnings:
        logger.info(warning)
        if "No valid GAM template" in warning:
            logger.info(f"Expected gam.exe under: {service.config.template_path}")
            logger.info("Place gam.exe in the new environment manually.")

    if result.backup_path:
        logger.info(f"JSON backup saved to: {result.backup_path}")
    logger.info(f"Saved JSON to: {service.config.json_path}")

    logger.info("")
    logger.info("Environment created:")
    logger.info(f"Name : {result.environment.name}")
    logger.info(f"Path : {result.environment.path}")

    if result.gam_exe_present:
        logger.info("gam.exe detected.")
    else:
        logger.info("gam.exe NOT found. Add it manually to:")
        logger.info(f"  {result.environment.path}")


def _delete_environment(service: LauncherService, logger) -> None:
    environments = service.list_environments()
    if not environments:
        logger.info("No environments to delete.")
        return

    logger.info("")
    logger.info("Delete Environment")
    logger.info("-------------------------------------------")

    for index, env in enumerate(environments, start=1):
        logger.info(f"[{index}] {env.name} - {env.path}")

    choice_raw = _prompt("Select an environment number to delete (Enter to cancel): ").strip()
    if not choice_raw:
        return

    if not choice_raw.isdigit():
        logger.info("Invalid selection.")
        return

    choice = int(choice_raw)
    if choice < 1 or choice > len(environments):
        logger.info("Invalid selection.")
        return

    target = environments[choice - 1]

    logger.info("")
    logger.info("You are about to delete:")
    logger.info(f"Name: {target.name}")
    logger.info(f"Path: {target.path}")
    confirm = _prompt("Type YES to confirm: ").strip()
    if confirm != "YES":
        logger.info("Cancelled.")
        return

    try:
        result = service.delete_environment(target.name)
    except EnvironmentNotFoundError as exc:
        logger.info(str(exc))
        return

    if result.backup_path:
        logger.info(f"JSON backup saved to: {result.backup_path}")
    logger.info(f"Saved JSON to: {service.config.json_path}")
    logger.info("Environment removed from configuration.")

    delete_folder = _prompt("Delete environment folder on disk? (Y/N): ").strip()
    if delete_folder.upper() == "Y" and Path(target.path).exists():
        try:
            shutil.rmtree(Path(target.path))
            logger.info("Folder deleted.")
        except OSError as exc:
            logger.info(f"Error deleting folder: {exc}")
    else:
        logger.info("Folder retained.")


def _validate_and_sanitise(service: LauncherService, logger) -> None:
    result = service.validate_paths()

    if not result.issues:
        logger.info("JSON paths look clean.")
        return

    logger.info("")
    logger.info("The following path issues were found:")
    for issue in result.issues:
        logger.info(f"[{issue.index + 1}] {issue.name}")
        logger.info(f"  Original: {issue.original}")
        logger.info(f"  Clean   : {issue.clean}")
        logger.info("")

    apply_changes = _prompt("Apply these fixes now? (Y/N): ").strip()
    if apply_changes.upper() != "Y":
        logger.info("No changes made.")
        return

    applied = service.validate_paths(apply_changes=True)
    if applied.backup_path:
        logger.info(f"JSON backup saved to: {applied.backup_path}")
    logger.info(f"Saved JSON to: {service.config.json_path}")
    logger.info("Sanitisation complete.")


def _resolve_environment_choice(choice: str, environments: list[Environment]) -> Environment | None:
    if not choice.isdigit():
        return None
    index = int(choice)
    if index < 1 or index > len(environments):
        return None
    return environments[index - 1]


def _interactive_session(
    service: LauncherService, env: Environment, logger
) -> tuple[bool, str | None]:
    try:
        session = service.prepare_session(env)
    except EnvironmentPathError as exc:
        logger.info(str(exc))
        return False, None

    os.environ["GAMCFGDIR"] = str(session.gam_dir)
    logger.info(f"GAMCFGDIR set to: {session.gam_dir}")

    if session.gam_available:
        logger.info(f"Global GAM runner bound to: {session.gam_exe}")
        logger.info("GAM commands can now be run directly (with or without leading 'gam')")
    else:
        logger.info(f"gam.exe not found in {session.gam_path}")
        logger.info("The 'gam' command cannot run until gam.exe is added.")

    logger.info("")
    logger.info(f"Environment active: {env.name}")
    logger.info(f"Directory set to: {session.gam_path}")
    logger.info("GAM commands can now be run directly using 'gam'.")
    logger.info("Type 'switch <name>' to jump to another environment or 'switch' to return to the menu.")

    while True:
        raw_command = _prompt("GAM> ").strip()
        if not raw_command:
            continue

        if raw_command.lower() == "exit":
            return True, None

        if raw_command.lower().startswith("switch"):
            parts = raw_command.split(maxsplit=1)
            return False, parts[1].strip() if len(parts) > 1 else None

        service.run_command(session, raw_command, logger)


def run_launcher() -> None:
    script_dir = script_directory()
    if script_dir and script_dir.exists():
        os.chdir(script_dir)

    config = LauncherConfig.default(base_dir=Path.cwd())

    service = LauncherService(config)
    transcript = TranscriptLogger.create(config.log_root)
    transcript.start_new_transcript()
    logger = transcript.logger

    pending_target: str | None = None
    exit_requested = False

    while not exit_requested:
        data = load_json(config.json_path)
        if data is None:
            logger.info("Error loading JSON configuration.")
            return

        environments = load_environments(data)
        _show_menu(logger, environments)

        choice_raw = None
        if pending_target:
            target_index = next(
                (
                    idx
                    for idx, env in enumerate(environments, start=1)
                    if env.name.lower() == pending_target.lower()
                ),
                None,
            )
            if target_index:
                choice_raw = str(target_index)
                logger.info(f"Switching to: {environments[target_index - 1].name}")
            else:
                logger.info(
                    f"Requested environment '{pending_target}' not found. Returning to menu."
                )
            pending_target = None

        if choice_raw is None:
            choice_raw = _prompt("Select option: ").strip()

        if not choice_raw:
            continue

        choice = choice_raw.strip()

        if choice.lower() == "q":
            exit_requested = True
            break

        if choice.lower() == "n":
            _create_environment(service, logger)
            continue

        if choice.lower() == "d":
            _delete_environment(service, logger)
            continue

        if choice.lower() == "v":
            _validate_and_sanitise(service, logger)
            continue

        selected_env = _resolve_environment_choice(choice, environments)
        if selected_env is None:
            logger.info("Invalid option.")
            continue

        exit_requested, pending_target = _interactive_session(service, selected_env, logger)
        if exit_requested:
            break

        transcript.start_new_transcript()

    logger.info("Exiting Universal GAM Launcher v4.6")
