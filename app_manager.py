# app_manager.py
# Hayeong's unified process manager.
#
# WHAT THIS DOES:
#   Single manager for every process Hayeong owns or depends on —
#   her own internal subprocesses AND external applications.
#
#   type="internal" — Python scripts (or node scripts) she runs directly.
#                     Managed by her. Tracked for auto-restart.
#   type="external" — Third-party applications (ComfyUI, Ollama, etc.)
#                     Started via start_cmd. Same API.
#
# HOW IT WORKS:
#   - Reads the "applications" section of capability_registry.json
#   - Starts processes on request or auto-start
#   - Monitors auto_restart=true processes in a background thread
#   - ensure_for_capability() starts everything a capability needs,
#     including wildcard needed_by=["*"] entries like Ollama
#
# CLOSE PHILOSOPHY:
#   Only closes processes she started herself — won't kill something
#   James launched manually. The vram_cost and idle_ok fields exist
#   for when she develops the judgment to close things proactively.

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


def _make_startupinfo() -> subprocess.STARTUPINFO:
    """Windows: open new console minimized, do not steal focus."""
    si = subprocess.STARTUPINFO()
    si.dwFlags    = subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 6  # SW_MINIMIZE
    return si


class AppManager:
    """
    Unified process manager for all of Hayeong's processes.

    Usage
    -----
    mgr = get_app_manager()

    # Auto-start what a capability needs (called by capability_loader)
    ok, msgs = mgr.ensure_for_capability("image_gen")

    # Explicit start/close
    ok, msg = mgr.start("voice_server")
    ok, msg = mgr.close("comfyui")

    # Status
    running = mgr.is_running("discord")
    all_status = mgr.status()
    """

    def __init__(self):
        self._apps:  dict[str, dict]             = {}  # id → registry entry
        self._procs: dict[str, subprocess.Popen] = {}  # id → process we started
        self._starting: set                      = set()  # app_ids currently in the process of starting
        self._lock    = threading.Lock()
        self._running = False
        self._load()

    # ─────────────────────────────────────────
    # LOAD / RELOAD
    # ─────────────────────────────────────────

    def _load(self):
        """Read all application entries from capability_registry.json."""
        if not REGISTRY_FILE.exists():
            log.warning("Registry not found — no applications loaded")
            return
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                registry = json.load(f)
            apps = registry.get("applications", {}).get("apps", [])
            self._apps = {a["id"]: a for a in apps}
            log.info(f"AppManager loaded {len(self._apps)} entries: {list(self._apps.keys())}")
        except Exception as e:
            log.error(f"Failed to load applications: {e}")

    def reload(self):
        """Hot-reload registry. Called by capability_loader watcher."""
        self._load()

    # ─────────────────────────────────────────
    # START / STOP BACKGROUND MONITOR
    # ─────────────────────────────────────────

    def start_monitor(self):
        """Start the background auto-restart monitor thread."""
        self._running = True
        t = threading.Thread(target=self._auto_restart_loop, daemon=True, name="app_monitor")
        t.start()
        log.info("AppManager monitor started")

    def stop_monitor(self):
        self._running = False

    def _auto_restart_loop(self):
        """Background thread — detects crashes and notifies the reasoning LLM.
        Does NOT restart; restarts are Hayeong's decision."""
        STARTUP_GRACE = 60
        time.sleep(STARTUP_GRACE)

        while self._running:
            time.sleep(10)
            for app_id, app in list(self._apps.items()):
                crashed = False
                with self._lock:
                    if app_id in self._starting:
                        continue
                    proc = self._procs.get(app_id)
                    if proc is None:
                        continue
                    if proc.poll() is not None:
                        del self._procs[app_id]
                        crashed = True

                if crashed:
                    log.warning(f"{app['name']} crashed — notifying reasoning LLM")
                    try:
                        from hayeong_state import push_system_alert
                        push_system_alert(
                            app_id, "crashed",
                            reason=f"{app['name']} process exited unexpectedly",
                        )
                    except Exception as e:
                        log.error(f"Could not push system alert for {app_id}: {e}")

    # ─────────────────────────────────────────
    # IS RUNNING
    # ─────────────────────────────────────────

    def is_running(self, app_id: str) -> bool:
        """
        Check if a process is currently running.
        Tries HTTP health check → process we own → process name check.
        """
        # A process that is starting is considered running — prevents duplicate spawns
        # while Whisper/Kokoro are loading (can take 30s+, health check fails during this window)
        with self._lock:
            if app_id in self._starting:
                return True

        app = self._apps.get(app_id)
        if not app:
            return False

        check_url = app.get("check_url")
        if check_url:
            try:
                import urllib.request
                urllib.request.urlopen(check_url, timeout=2)
                return True
            except Exception:
                pass

        with self._lock:
            proc = self._procs.get(app_id)
            if proc and proc.poll() is None:
                return True

        check_proc = app.get("check_process")
        if check_proc:
            return self._process_name_running(check_proc)

        return False

    def _process_name_running(self, name: str) -> bool:
        """Check if a process with this name exists (Windows)."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}"],
                capture_output=True, text=True, timeout=5,
            )
            return name.lower() in result.stdout.lower()
        except Exception:
            return False

    # ─────────────────────────────────────────
    # START
    # ─────────────────────────────────────────

    def start(self, app_id: str) -> tuple[bool, str]:
        """
        Start a process by id.
        Returns (success, message).
        """
        app = self._apps.get(app_id)
        if not app:
            return False, f"'{app_id}' isn't in my application registry."

        if self.is_running(app_id):
            return True, f"{app['name']} is already running."

        return self._do_start(app_id)

    def _do_start(self, app_id: str) -> tuple[bool, str]:
        """Internal start — no duplicate check. Safe to call from auto-restart."""
        # Concurrent start protection — voice server takes 30s+ to load Whisper+Kokoro.
        # Health check fails during loading; without this guard every failure spawns a new instance.
        with self._lock:
            if app_id in self._starting:
                name = self._apps.get(app_id, {}).get("name", app_id)
                log.info(f"[AppManager] {app_id} is already starting — skipping duplicate start")
                return True, f"{name} is already starting."
            self._starting.add(app_id)

        try:
            app = self._apps.get(app_id)
            if not app:
                return False, f"No registry entry for '{app_id}'."

            app_type = app.get("type", "external")

            try:
                if app_type == "internal":
                    proc = self._start_internal(app_id, app)
                else:
                    proc = self._start_external(app_id, app)

                if proc is None:
                    return False, f"Failed to launch {app['name']}."

                with self._lock:
                    self._procs[app_id] = proc

                return self._wait_for_ready(app_id, app)

            except Exception as e:
                log.error(f"Failed to start {app['name']}: {e}")
                return False, f"I tried to start {app['name']} but got an error: {e}"

        finally:
            # Always release the starting lock — success or failure
            with self._lock:
                self._starting.discard(app_id)

    def _start_internal(self, app_id: str, app: dict) -> Optional[subprocess.Popen]:
        """
        Start an internal subprocess.
        If the entry has start_cmd, use it directly (e.g. node discord_hayeong.js).
        Otherwise derive [sys.executable, script_path] from the script field.
        """
        start_cmd = app.get("start_cmd")
        if start_cmd:
            cmd = list(start_cmd)
            # Resolve relative paths — the first token might be a filename
            if len(cmd) > 1:
                candidate = BASE_DIR / cmd[-1]
                if candidate.exists():
                    cmd[-1] = str(candidate)
            log.info(f"Starting internal [{app_id}]: {' '.join(cmd)}")
        else:
            script = app.get("script")
            if not script:
                raise ValueError(f"Internal app '{app_id}' has no script or start_cmd.")
            script_path = BASE_DIR / script
            if not script_path.exists():
                raise FileNotFoundError(f"Script not found: {script_path}")
            cmd = [sys.executable, str(script_path)]
            log.info(f"Starting internal [{app_id}]: {' '.join(cmd)}")

        _env = os.environ.copy()
        _env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            env=_env,
        )

    def _start_external(self, app_id: str, app: dict) -> Optional[subprocess.Popen]:
        """Start an external application via start_cmd."""
        start_cmd = app.get("start_cmd")
        if not start_cmd:
            raise ValueError(f"External app '{app_id}' has no start_cmd.")

        if isinstance(start_cmd, str):
            start_cmd = [start_cmd]

        cmd_path = Path(start_cmd[0])
        if cmd_path.suffix in (".bat", ".exe", ".py") and not cmd_path.exists():
            raise FileNotFoundError(f"Start file not found: {start_cmd[0]}")

        use_shell = start_cmd[0].endswith(".bat")
        cwd = str(cmd_path.parent) if cmd_path.exists() else None
        log.info(f"Starting external [{app_id}]: {' '.join(str(c) for c in start_cmd)}")

        _env = os.environ.copy()
        _env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.Popen(
            start_cmd[0] if use_shell else start_cmd,
            shell=use_shell,
            cwd=cwd,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            env=_env,
        )

    def _wait_for_ready(self, app_id: str, app: dict) -> tuple[bool, str]:
        """Wait for an app to become ready after launch."""
        check_url  = app.get("check_url")
        wait_secs  = app.get("start_wait", 5)

        if check_url:
            deadline = time.time() + wait_secs + 30
            log.info(f"Waiting for {app['name']} at {check_url}...")
            while time.time() < deadline:
                time.sleep(2)
                if self.is_running(app_id):
                    log.info(f"{app['name']} ready.")
                    return True, f"{app['name']} is up and ready."
            return False, f"{app['name']} started but didn't respond in time. It may still be loading."
        else:
            time.sleep(wait_secs)
            return True, f"{app['name']} started."

    # ─────────────────────────────────────────
    # CLOSE
    # ─────────────────────────────────────────

    def close(self, app_id: str) -> tuple[bool, str]:
        """
        Close a process.
        Only closes processes Hayeong started — won't touch ones James launched.
        Returns (success, message).
        """
        app  = self._apps.get(app_id)
        name = app["name"] if app else app_id

        with self._lock:
            proc = self._procs.get(app_id)

        if not proc:
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

    def stop_all(self):
        """Terminate all processes Hayeong started. Used on shutdown."""
        with self._lock:
            ids = list(self._procs.keys())
        for app_id in ids:
            self.close(app_id)
        log.info("All managed processes stopped")

    # ─────────────────────────────────────────
    # ENSURE FOR CAPABILITY
    # Called by capability_loader before dispatch.
    # ─────────────────────────────────────────

    def ensure_for_capability(self, capability_id: str) -> tuple[bool, list[str]]:
        """
        Start all applications needed by a capability.
        Supports wildcard needed_by=["*"] for things every capability needs.
        Returns (all_ok, list_of_messages).
        """
        messages = []
        all_ok   = True

        for app_id, app in self._apps.items():
            needed_by = app.get("needed_by", [])
            if capability_id not in needed_by and "*" not in needed_by:
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
        """Return running status of all registered processes."""
        return {
            app_id: {
                "name":       app["name"],
                "type":       app.get("type", "external"),
                "running":    self.is_running(app_id),
                "we_started": app_id in self._procs,
                "vram_cost":  app.get("vram_cost", "unknown"),
                "idle_ok":    app.get("idle_ok", True),
            }
            for app_id, app in self._apps.items()
        }

    def list_running(self) -> list[str]:
        """Return ids of all processes currently running (that we know about)."""
        with self._lock:
            return [app_id for app_id, proc in self._procs.items()
                    if proc.poll() is None]

    def needs_for_capability(self, capability_id: str) -> list[str]:
        """Return app ids needed by this capability (including wildcard matches)."""
        return [
            app_id for app_id, app in self._apps.items()
            if capability_id in app.get("needed_by", [])
            or "*" in app.get("needed_by", [])
        ]

    # ─────────────────────────────────────────
    # PROPOSE (future — Hayeong discovers she needs something new)
    # ─────────────────────────────────────────

    def propose_app(self, entry: dict) -> dict:
        """
        Propose adding a new application to the registry.
        Returns a proposal dict for James to approve via self-mod system.
        """
        required = ["id", "name"]
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
