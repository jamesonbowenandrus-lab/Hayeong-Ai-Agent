# app_manager.py
# Hayeong's application manager.
#
# WHAT THIS DOES:
#   Gives Hayeong the ability to start and close external applications
#   she needs to complete tasks — ComfyUI, Ollama, browsers, tools, etc.
#
#   She doesn't manage her own internal subprocesses here (that's ProcessManager).
#   This is for external programs she depends on to do work.
#
# HOW IT WORKS:
#   - Reads the "applications" section of capability_registry.json
#   - Checks if an app is running via HTTP health check or process name
#   - Starts it if needed, closes it when asked
#   - Tells capability_loader what each capability needs before dispatch
#
# CLOSE PHILOSOPHY:
#   Closing is not automatic. Hayeong can close an app when:
#     - James asks her to
#     - She decides to (future — based on vram_cost, idle_ok, session context)
#   For now close is always explicit. The registry fields (vram_cost, idle_ok)
#   are there for when she develops the judgment to use them herself.
#
# TOOL DISCOVERY (future):
#   When she encounters a task that needs an unknown application,
#   she can research it, propose adding it to the registry, and
#   James approves before it gets added. The registry entry format
#   is designed to be writable by her self-mod system.

import json
import os
import subprocess
import sys
import threading
import time
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("app_manager")

BASE_DIR      = Path(__file__).parent
REGISTRY_FILE = BASE_DIR / "capability_registry.json"


# ─────────────────────────────────────────────
# APPLICATION REGISTRY ENTRY SCHEMA
#
# Each entry in capability_registry.json "applications" section:
# {
#   "id":         "comfyui",              — unique snake_case id
#   "name":       "ComfyUI",              — human readable
#   "start_cmd":  ["H:/ComfyUI/run.bat"], — command to launch (list)
#   "check_url":  "http://localhost:8188", — HTTP ping to confirm running
#   "check_process": "python",             — OR process name to look for
#   "needed_by":  ["image_gen"],           — capability ids that need this
#   "vram_cost":  "high",                  — "high" | "medium" | "low" | "none"
#   "idle_ok":    false,                   — ok to leave running between tasks?
#   "start_wait": 8,                       — seconds to wait after launch
#   "notes":      "..."                    — for her to read and understand
# }
# ─────────────────────────────────────────────


class AppManager:
    """
    Manages external applications Hayeong needs for her tasks.

    Usage
    -----
    app_mgr = AppManager()

    # Check and auto-start what a capability needs
    ok, msg = app_mgr.ensure_for_capability("image_gen")

    # Explicit start/close
    ok, msg = app_mgr.start("comfyui")
    ok, msg = app_mgr.close("comfyui")

    # Status check
    running = app_mgr.is_running("comfyui")
    """

    def __init__(self):
        self._apps: dict[str, dict] = {}       # id → app entry
        self._procs: dict[str, subprocess.Popen] = {}  # id → process we started
        self._lock  = threading.Lock()
        self._load()

    # ─────────────────────────────────────────
    # LOAD
    # ─────────────────────────────────────────

    def _load(self):
        """Read application entries from capability_registry.json."""
        if not REGISTRY_FILE.exists():
            log.warning("Registry not found — no applications loaded")
            return
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                registry = json.load(f)
            apps = registry.get("applications", {}).get("apps", [])
            self._apps = {a["id"]: a for a in apps}
            log.info(f"AppManager loaded {len(self._apps)} application(s): {list(self._apps.keys())}")
        except Exception as e:
            log.error(f"Failed to load applications: {e}")

    def reload(self):
        """Hot-reload application registry. Called by capability_loader watcher."""
        self._load()

    # ─────────────────────────────────────────
    # STATUS CHECK
    # ─────────────────────────────────────────

    def is_running(self, app_id: str) -> bool:
        """
        Check if an application is currently running.
        Tries HTTP health check first, then process name check.
        """
        app = self._apps.get(app_id)
        if not app:
            return False

        # Check via HTTP if check_url is defined
        check_url = app.get("check_url")
        if check_url:
            try:
                import urllib.request
                urllib.request.urlopen(check_url, timeout=2)
                return True
            except Exception:
                pass

        # Check via process name if check_process is defined
        check_proc = app.get("check_process")
        if check_proc:
            return self._process_name_running(check_proc)

        # Check if we started it ourselves and it's still alive
        with self._lock:
            proc = self._procs.get(app_id)
            if proc and proc.poll() is None:
                return True

        return False

    def _process_name_running(self, name: str) -> bool:
        """Check if a process with this name is running on Windows."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}"],
                capture_output=True, text=True, timeout=5
            )
            return name.lower() in result.stdout.lower()
        except Exception:
            return False

    # ─────────────────────────────────────────
    # START
    # ─────────────────────────────────────────

    def start(self, app_id: str) -> tuple[bool, str]:
        """
        Start an application.
        Returns (success, message).
        """
        app = self._apps.get(app_id)
        if not app:
            return False, f"I don't know how to start '{app_id}'. It's not in my application registry."

        # Already running — nothing to do
        if self.is_running(app_id):
            return True, f"{app['name']} is already running."

        start_cmd = app.get("start_cmd")
        if not start_cmd:
            return False, f"No start command defined for {app['name']}."

        # Resolve path if it's a single file path
        if isinstance(start_cmd, str):
            start_cmd = [start_cmd]

        # Check the file exists if it's a local path
        cmd_path = Path(start_cmd[0])
        if cmd_path.suffix in (".bat", ".exe", ".py") and not cmd_path.exists():
            return False, f"Start file not found: {start_cmd[0]}"

        try:
            log.info(f"Starting {app['name']}: {' '.join(start_cmd)}")

            # .bat files need shell=True on Windows
            use_shell = start_cmd[0].endswith(".bat")

            proc = subprocess.Popen(
                start_cmd[0] if use_shell else start_cmd,
                shell=use_shell,
                cwd=str(cmd_path.parent) if cmd_path.exists() else None,
                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
            )

            with self._lock:
                self._procs[app_id] = proc

            # Wait for it to become ready
            wait_secs = app.get("start_wait", 5)
            check_url = app.get("check_url")

            if check_url:
                # Poll until HTTP responds or timeout
                deadline = time.time() + wait_secs + 30  # generous timeout
                log.info(f"Waiting for {app['name']} to become ready at {check_url}...")
                while time.time() < deadline:
                    time.sleep(2)
                    if self.is_running(app_id):
                        log.info(f"{app['name']} is ready.")
                        return True, f"{app['name']} is up and ready."
                return False, f"{app['name']} started but didn't respond in time. It may still be loading."
            else:
                # Just wait the defined time
                time.sleep(wait_secs)
                return True, f"{app['name']} started."

        except Exception as e:
            log.error(f"Failed to start {app['name']}: {e}")
            return False, f"I tried to start {app['name']} but ran into an error: {e}"

    # ─────────────────────────────────────────
    # CLOSE
    # ─────────────────────────────────────────

    def close(self, app_id: str) -> tuple[bool, str]:
        """
        Close an application.
        Only closes processes Hayeong started herself — won't kill
        something James launched manually.
        Returns (success, message).
        """
        app = self._apps.get(app_id)
        name = app["name"] if app else app_id

        with self._lock:
            proc = self._procs.get(app_id)

        if not proc:
            # She didn't start it — don't touch it
            if self.is_running(app_id):
                return False, f"{name} is running but I didn't start it — I won't close it without your say-so."
            return False, f"{name} isn't running."

        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)
            with self._lock:
                del self._procs[app_id]
            log.info(f"Closed {name}")
            return True, f"{name} closed."
        except Exception as e:
            return False, f"Had trouble closing {name}: {e}"

    # ─────────────────────────────────────────
    # ENSURE FOR CAPABILITY
    # Called by capability_loader before dispatch.
    # Starts anything the capability needs that isn't running.
    # ─────────────────────────────────────────

    def ensure_for_capability(self, capability_id: str) -> tuple[bool, list[str]]:
        """
        Start all applications needed by a capability.
        Returns (all_ok, list_of_messages).

        Called automatically before capability dispatch.
        """
        messages = []
        all_ok   = True

        for app_id, app in self._apps.items():
            needed_by = app.get("needed_by", [])
            if capability_id not in needed_by:
                continue

            if self.is_running(app_id):
                log.debug(f"  [{capability_id}] {app['name']} already running")
                continue

            log.info(f"  [{capability_id}] needs {app['name']} — starting...")
            ok, msg = self.start(app_id)
            messages.append(msg)
            if not ok:
                all_ok = False
                log.warning(f"  [{capability_id}] failed to start {app['name']}: {msg}")

        return all_ok, messages

    # ─────────────────────────────────────────
    # STATUS
    # ─────────────────────────────────────────

    def status(self) -> dict:
        """Return running status of all known applications."""
        return {
            app_id: {
                "name":       app["name"],
                "running":    self.is_running(app_id),
                "we_started": app_id in self._procs,
                "vram_cost":  app.get("vram_cost", "unknown"),
                "idle_ok":    app.get("idle_ok", True),
            }
            for app_id, app in self._apps.items()
        }

    def needs_for_capability(self, capability_id: str) -> list[str]:
        """Return list of app ids needed by this capability."""
        return [
            app_id for app_id, app in self._apps.items()
            if capability_id in app.get("needed_by", [])
        ]

    # ─────────────────────────────────────────
    # REGISTRY — for future self-registration
    # Hayeong can call this to propose adding a new application.
    # James approves before it's saved.
    # ─────────────────────────────────────────

    def propose_app(self, entry: dict) -> dict:
        """
        Propose adding a new application to the registry.
        Returns a proposal dict for James to approve via self-mod system.

        Future use — when Hayeong discovers she needs an unknown tool.
        """
        required = ["id", "name", "start_cmd"]
        missing  = [f for f in required if f not in entry]
        if missing:
            return {"success": False, "reason": f"Missing required fields: {missing}"}

        return {
            "success":  True,
            "proposal": {
                "type":        "new_application",
                "entry":       entry,
                "status":      "pending_james",
                "description": f"Hayeong wants to add '{entry['name']}' to her application registry.",
            }
        }


# ─────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────

_app_manager: Optional[AppManager] = None

def get_app_manager() -> AppManager:
    global _app_manager
    if _app_manager is None:
        _app_manager = AppManager()
    return _app_manager
