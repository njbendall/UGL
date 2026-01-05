from __future__ import annotations

import os
import shutil
import shlex
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog

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
from .launcher import GAM_COMMANDS, _script_directory, _select_template_source, _run_subprocess
from .logging_utils import TranscriptLogger


class UILogger:
    def __init__(self, logger, append_line) -> None:
        self._logger = logger
        self._append_line = append_line

    def info(self, message: str) -> None:
        self._logger.info(message)
        self._append_line(message)


class LauncherUI:
    def __init__(self, root: tk.Tk, config: LauncherConfig) -> None:
        self.root = root
        self.config = config
        self.root.title("Universal GAM Launcher")

        ensure_directories(config.config_root, config.log_root, config.json_backup_root)
        ensure_json_exists(config.json_path)

        self.transcript = TranscriptLogger.create(config.log_root, enable_console=False)
        self.transcript.start_new_transcript()

        self.env_list: list[Environment] = []
        self.active_env: Environment | None = None
        self.active_path: Path | None = None
        self.active_gam_dir: Path | None = None
        self.active_gam_exe: Path | None = None

        self._build_ui()

        self.logger = UILogger(self.transcript.logger, self._append_log)
        self.refresh_environments()

    def _build_ui(self) -> None:
        container = tk.Frame(self.root, padx=12, pady=12)
        container.pack(fill=tk.BOTH, expand=True)

        env_frame = tk.Frame(container)
        env_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False)

        tk.Label(env_frame, text="Configured Environments").pack(anchor="w")

        list_frame = tk.Frame(env_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.env_listbox = tk.Listbox(list_frame, height=14, width=40)
        self.env_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.env_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.env_listbox.configure(yscrollcommand=scrollbar.set)

        button_frame = tk.Frame(env_frame, pady=8)
        button_frame.pack(fill=tk.X)

        tk.Button(button_frame, text="Create", command=self.create_environment).pack(
            side=tk.LEFT, padx=4
        )
        tk.Button(button_frame, text="Delete", command=self.delete_environment).pack(
            side=tk.LEFT, padx=4
        )
        tk.Button(button_frame, text="Validate", command=self.validate_environments).pack(
            side=tk.LEFT, padx=4
        )
        tk.Button(button_frame, text="Activate", command=self.activate_environment).pack(
            side=tk.LEFT, padx=4
        )

        right_frame = tk.Frame(container, padx=12)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.active_label = tk.Label(right_frame, text="Active Environment: None")
        self.active_label.pack(anchor="w")

        self.log_text = tk.Text(right_frame, height=18, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=(8, 8))

        command_frame = tk.Frame(right_frame)
        command_frame.pack(fill=tk.X)

        tk.Label(command_frame, text="Command").pack(side=tk.LEFT)
        self.command_var = tk.StringVar()
        self.command_entry = tk.Entry(command_frame, textvariable=self.command_var)
        self.command_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.command_entry.bind("<Return>", self.run_command)

        tk.Button(command_frame, text="Run", command=self.run_command).pack(side=tk.LEFT)

        tk.Button(right_frame, text="Quit", command=self.root.destroy).pack(
            anchor="e", pady=(8, 0)
        )

    def _append_log(self, message: str) -> None:
        def append() -> None:
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"{message}\n")
            self.log_text.configure(state=tk.DISABLED)
            self.log_text.see(tk.END)

        self.root.after(0, append)

    def refresh_environments(self) -> None:
        data = load_json(self.config.json_path)
        if data is None:
            self.logger.info("Error loading JSON configuration.")
            return
        self.env_list = load_environments(data)
        self.env_listbox.delete(0, tk.END)
        for env in self.env_list:
            self.env_listbox.insert(tk.END, f"{env.name} - {normalise_path(env.path)}")

    def _selected_environment(self) -> Environment | None:
        selection = self.env_listbox.curselection()
        if not selection:
            return None
        return self.env_list[selection[0]]

    def create_environment(self) -> None:
        name = simpledialog.askstring(
            "Create Environment", "Enter Environment Name:", parent=self.root
        )
        if not name:
            return

        admin = simpledialog.askstring(
            "Create Environment", "Enter Google Admin Email (optional):", parent=self.root
        )
        color = simpledialog.askstring(
            "Create Environment", "Enter Display Colour (optional):", parent=self.root
        )

        admin = admin.strip() if admin else None
        color = color.strip() if color else None

        data = load_json(self.config.json_path)
        if data is None:
            self.logger.info("Error loading JSON configuration.")
            return

        environments = load_environments(data)
        safe_key = safe_folder_key(name)
        path = self.config.clients_root / safe_key

        for env in environments:
            if env.name == name or normalise_path(env.path) == str(path):
                messagebox.showerror("Create Environment", "Environment already exists.")
                return

        ensure_directories(path)

        self.logger.info("")
        self.logger.info("Create New GAM Environment")
        self.logger.info("-------------------------------------------")
        self.logger.info(f"Auto-generated folder: {path}")
        self.logger.info(f"Using template: {self.config.template_path}")

        template_source = _select_template_source(self.config.template_path)
        if template_source:
            self.logger.info(f"Cloning template from: {template_source}")
            try:
                clone_template(template_source, path)
            except OSError as exc:
                self.logger.info(f"Template copy failed: {exc}")
        else:
            self.logger.info("WARNING: No valid GAM template found.")
            self.logger.info(f"Expected gam.exe under: {self.config.template_path}")
            self.logger.info("Place gam.exe in the new environment manually.")

        gam_dir = ensure_gam_structure(path)
        remove_oauth_tokens(gam_dir)

        environments.append(Environment(name=name, path=str(path), admin=admin, color=color))
        set_environments(data, environments)
        backup_path = save_json(self.config.json_path, self.config.json_backup_root, data)

        if backup_path:
            self.logger.info(f"JSON backup saved to: {backup_path}")
        self.logger.info(f"Saved JSON to: {self.config.json_path}")

        self.logger.info("")
        self.logger.info("Environment created:")
        self.logger.info(f"Name : {name}")
        self.logger.info(f"Path : {path}")
        if gam_exe_exists(path):
            self.logger.info("gam.exe detected.")
        else:
            self.logger.info("gam.exe NOT found. Add it manually to:")
            self.logger.info(f"  {path}")

        self.refresh_environments()

    def delete_environment(self) -> None:
        env = self._selected_environment()
        if env is None:
            messagebox.showinfo("Delete Environment", "Select an environment to delete.")
            return

        confirm = messagebox.askyesno(
            "Delete Environment",
            f"Delete environment '{env.name}' from configuration?",
        )
        if not confirm:
            return

        data = load_json(self.config.json_path)
        if data is None:
            self.logger.info("Error loading JSON configuration.")
            return

        environments = [item for item in load_environments(data) if item.name != env.name]
        set_environments(data, environments)
        backup_path = save_json(self.config.json_path, self.config.json_backup_root, data)
        if backup_path:
            self.logger.info(f"JSON backup saved to: {backup_path}")
        self.logger.info(f"Saved JSON to: {self.config.json_path}")
        self.logger.info("Environment removed from configuration.")

        delete_folder = messagebox.askyesno(
            "Delete Environment",
            "Delete environment folder on disk?",
        )
        if delete_folder and Path(env.path).exists():
            try:
                shutil.rmtree(Path(env.path))
                self.logger.info("Folder deleted.")
            except OSError as exc:
                self.logger.info(f"Error deleting folder: {exc}")
        else:
            self.logger.info("Folder retained.")

        if self.active_env and self.active_env.name == env.name:
            self.active_env = None
            self.active_path = None
            self.active_gam_dir = None
            self.active_gam_exe = None
            self.active_label.configure(text="Active Environment: None")

        self.refresh_environments()

    def validate_environments(self) -> None:
        data = load_json(self.config.json_path)
        if data is None:
            self.logger.info("Error loading JSON configuration.")
            return

        environments = load_environments(data)
        issues = sanitise_environment_paths(environments)

        if not issues:
            self.logger.info("JSON paths look clean.")
            return

        self.logger.info("")
        self.logger.info("The following path issues were found:")
        for index, name, original, clean in issues:
            self.logger.info(f"[{index + 1}] {name}")
            self.logger.info(f"  Original: {original}")
            self.logger.info(f"  Clean   : {clean}")
            self.logger.info("")

        apply_changes = messagebox.askyesno(
            "Validate Paths",
            "Apply these fixes now?",
        )
        if not apply_changes:
            self.logger.info("No changes made.")
            return

        for index, _, _, clean in issues:
            environments[index].path = clean

        set_environments(data, environments)
        backup_path = save_json(self.config.json_path, self.config.json_backup_root, data)
        if backup_path:
            self.logger.info(f"JSON backup saved to: {backup_path}")
        self.logger.info(f"Saved JSON to: {self.config.json_path}")
        self.logger.info("Sanitisation complete.")
        self.refresh_environments()

    def activate_environment(self) -> None:
        env = self._selected_environment()
        if env is None:
            messagebox.showinfo("Activate Environment", "Select an environment to activate.")
            return

        gam_path = Path(normalise_path(env.path) or env.path)
        if not gam_path.exists():
            self.logger.info(f"Environment folder does not exist: {gam_path}")
            return

        gam_dir = ensure_gam_structure(gam_path)
        os.environ["GAMCFGDIR"] = str(gam_dir)
        self.active_env = env
        self.active_path = gam_path
        self.active_gam_dir = gam_dir
        self.active_gam_exe = gam_path / "gam.exe"

        self.logger.info(f"GAMCFGDIR set to: {gam_dir}")
        if self.active_gam_exe.exists():
            self.logger.info(f"Global GAM runner bound to: {self.active_gam_exe}")
            self.logger.info("GAM commands can now be run directly (with or without leading 'gam')")
        else:
            self.logger.info(f"gam.exe not found in {gam_path}")
            self.logger.info("The 'gam' command cannot run until gam.exe is added.")

        self.logger.info("")
        self.logger.info(f"Environment active: {env.name}")
        self.logger.info(f"Directory set to: {gam_path}")
        self.logger.info("GAM commands can now be run directly using 'gam'.")

        self.active_label.configure(text=f"Active Environment: {env.name}")

    def run_command(self, event=None) -> None:
        if self.active_env is None or self.active_path is None or self.active_gam_dir is None:
            messagebox.showinfo("Run Command", "Activate an environment first.")
            return

        raw_command = self.command_var.get().strip()
        if not raw_command:
            return
        self.command_var.set("")

        session_env = os.environ.copy()
        session_env["GAMCFGDIR"] = str(self.active_gam_dir)

        args = shlex.split(raw_command)
        if not args:
            return

        command_root = args[0].lower()
        use_gam = command_root == "gam" or command_root in GAM_COMMANDS

        if use_gam:
            if command_root == "gam":
                args = args[1:]
                if not args:
                    self.logger.info("No GAM command provided.")
                    return
            if self.active_gam_exe and self.active_gam_exe.exists():
                self._run_in_thread(
                    _run_subprocess,
                    [str(self.active_gam_exe)] + args,
                    session_env,
                    self.active_path,
                )
            else:
                self.logger.info("gam.exe is not available for this environment.")
            return

        self._run_in_thread(
            self._run_shell_command,
            raw_command,
            session_env,
            self.active_path,
        )

    def _run_in_thread(self, func, *args) -> None:
        thread = threading.Thread(target=func, args=(*args, self.logger), daemon=True)
        thread.start()

    def _run_shell_command(self, command: str, env: dict[str, str], cwd: Path, logger) -> int:
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


def run_ui() -> None:
    script_dir = _script_directory()
    if script_dir and script_dir.exists():
        os.chdir(script_dir)

    config = LauncherConfig.default(base_dir=Path.cwd())
    root = tk.Tk()
    LauncherUI(root, config)
    root.mainloop()
