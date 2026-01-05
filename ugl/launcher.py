from __future__ import annotations

import os
import shlex
import subprocess
import shutil
from pathlib import Path
from typing import Iterable

from .config import LauncherConfig
from .environment import Environment, load_environments, sanitise_environment_paths
from .filesystem import (
    clone_template,
    ensure_directories,
    ensure_gam_structure,
    gam_exe_exists,
    normalise_path,
    remove_oauth_tokens,
    safe_folder_key,
)
from .json_store import ensure_json_exists, load_json, save_json, set_environments
from .logging_utils import TranscriptLogger

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


def _script_directory() -> Path | None:
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


def _select_template_source(template_path: Path) -> Path | None:
    if (template_path / "gam.exe").exists():
        return template_path
    if template_path.exists():
        for child in template_path.iterdir():
            if child.is_dir() and (child / "gam.exe").exists():
                return child
    return None


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


def _create_environment(config: LauncherConfig, logger) -> None:
    logger.info("")
    logger.info("Create New GAM Environment")
    logger.info("-------------------------------------------")

    name = _prompt("Enter Environment Name (e.g., WMAT-ROD - Rodborough School): ").strip()
    if not name:
        logger.info("Name required.")
        return

    safe_key = safe_folder_key(name)
    path = config.clients_root / safe_key

    logger.info("Auto-generated folder:")
    logger.info(f"  {path}")

    admin = _prompt("Enter Google Admin Email (optional): ").strip() or None
    color = _prompt("Enter Display Colour (optional): ").strip() or None

    data = load_json(config.json_path)
    if data is None:
        logger.info("Error loading JSON configuration.")
        return

    environments = load_environments(data)
    for env in environments:
        if env.name == name or normalise_path(env.path) == str(path):
            logger.info("Environment already exists.")
            return

    ensure_directories(path)

    logger.info("")
    logger.info(f"Using template: {config.template_path}")

    template_source = _select_template_source(config.template_path)
    if template_source:
        logger.info(f"Cloning template from: {template_source}")
        try:
            clone_template(template_source, path)
        except OSError as exc:
            logger.info(f"Template copy failed: {exc}")
    else:
        logger.info("WARNING: No valid GAM template found.")
        logger.info(f"Expected gam.exe under: {config.template_path}")
        logger.info("Place gam.exe in the new environment manually.")

    gam_dir = ensure_gam_structure(path)
    remove_oauth_tokens(gam_dir)

    environments.append(Environment(name=name, path=str(path), admin=admin, color=color))
    set_environments(data, environments)
    backup_path = save_json(config.json_path, config.json_backup_root, data)

    if backup_path:
        logger.info(f"JSON backup saved to: {backup_path}")
    logger.info(f"Saved JSON to: {config.json_path}")

    logger.info("")
    logger.info("Environment created:")
    logger.info(f"Name : {name}")
    logger.info(f"Path : {path}")

    if gam_exe_exists(path):
        logger.info("gam.exe detected.")
    else:
        logger.info("gam.exe NOT found. Add it manually to:")
        logger.info(f"  {path}")


def _delete_environment(config: LauncherConfig, logger) -> None:
    data = load_json(config.json_path)
    if data is None:
        logger.info("Error loading JSON configuration.")
        return

    environments = load_environments(data)
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

    environments = [env for env in environments if env.name != target.name]
    set_environments(data, environments)
    backup_path = save_json(config.json_path, config.json_backup_root, data)
    if backup_path:
        logger.info(f"JSON backup saved to: {backup_path}")
    logger.info(f"Saved JSON to: {config.json_path}")
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


def _validate_and_sanitise(config: LauncherConfig, logger) -> None:
    data = load_json(config.json_path)
    if data is None:
        logger.info("Error loading JSON configuration.")
        return

    environments = load_environments(data)
    issues = sanitise_environment_paths(environments)

    if not issues:
        logger.info("JSON paths look clean.")
        return

    logger.info("")
    logger.info("The following path issues were found:")
    for index, name, original, clean in issues:
        logger.info(f"[{index + 1}] {name}")
        logger.info(f"  Original: {original}")
        logger.info(f"  Clean   : {clean}")
        logger.info("")

    apply_changes = _prompt("Apply these fixes now? (Y/N): ").strip()
    if apply_changes.upper() != "Y":
        logger.info("No changes made.")
        return

    for index, _, _, clean in issues:
        environments[index].path = clean

    set_environments(data, environments)
    backup_path = save_json(config.json_path, config.json_backup_root, data)
    if backup_path:
        logger.info(f"JSON backup saved to: {backup_path}")
    logger.info(f"Saved JSON to: {config.json_path}")
    logger.info("Sanitisation complete.")


def _resolve_environment_choice(choice: str, environments: list[Environment]) -> Environment | None:
    if not choice.isdigit():
        return None
    index = int(choice)
    if index < 1 or index > len(environments):
        return None
    return environments[index - 1]


def _run_subprocess(command: list[str], env: dict[str, str], cwd: Path, logger) -> int:
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


def _interactive_session(env: Environment, logger) -> tuple[bool, str | None]:
    gam_path = Path(normalise_path(env.path) or env.path)
    if not gam_path.exists():
        logger.info(f"Environment folder does not exist: {gam_path}")
        return False, None

    gam_dir = ensure_gam_structure(gam_path)
    os.environ["GAMCFGDIR"] = str(gam_dir)
    logger.info(f"GAMCFGDIR set to: {gam_dir}")

    gam_exe = gam_path / "gam.exe"
    gam_available = gam_exe.exists()
    if gam_available:
        logger.info(f"Global GAM runner bound to: {gam_exe}")
        logger.info("GAM commands can now be run directly (with or without leading 'gam')")
    else:
        logger.info(f"gam.exe not found in {gam_path}")
        logger.info("The 'gam' command cannot run until gam.exe is added.")

    logger.info("")
    logger.info(f"Environment active: {env.name}")
    logger.info(f"Directory set to: {gam_path}")
    logger.info("GAM commands can now be run directly using 'gam'.")
    logger.info("Type 'switch <name>' to jump to another environment or 'switch' to return to the menu.")

    session_env = os.environ.copy()
    session_env["GAMCFGDIR"] = str(gam_dir)

    while True:
        raw_command = _prompt("GAM> ").strip()
        if not raw_command:
            continue

        if raw_command.lower() == "exit":
            return True, None

        if raw_command.lower().startswith("switch"):
            parts = raw_command.split(maxsplit=1)
            return False, parts[1].strip() if len(parts) > 1 else None

        args = shlex.split(raw_command)
        if not args:
            continue

        command_root = args[0].lower()
        use_gam = command_root == "gam" or command_root in GAM_COMMANDS

        if use_gam:
            if command_root == "gam":
                args = args[1:]
                if not args:
                    logger.info("No GAM command provided.")
                    continue
            if gam_available:
                _run_subprocess([str(gam_exe)] + args, session_env, gam_path, logger)
            else:
                logger.info("gam.exe is not available for this environment.")
            continue

        subprocess.run(raw_command, cwd=str(gam_path), env=session_env, shell=True, check=False)


def run_launcher() -> None:
    script_dir = _script_directory()
    if script_dir and script_dir.exists():
        os.chdir(script_dir)

    config = LauncherConfig.default(base_dir=Path.cwd())

    ensure_directories(config.config_root, config.log_root, config.json_backup_root)
    ensure_json_exists(config.json_path)

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
            _create_environment(config, logger)
            continue

        if choice.lower() == "d":
            _delete_environment(config, logger)
            continue

        if choice.lower() == "v":
            _validate_and_sanitise(config, logger)
            continue

        selected_env = _resolve_environment_choice(choice, environments)
        if selected_env is None:
            logger.info("Invalid option.")
            continue

        exit_requested, pending_target = _interactive_session(selected_env, logger)
        if exit_requested:
            break

        transcript.start_new_transcript()

    logger.info("Exiting Universal GAM Launcher v4.6")
