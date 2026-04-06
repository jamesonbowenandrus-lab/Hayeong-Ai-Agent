# capability_loader.py
# Hayeong's dynamic capability loader.
#
# WHAT THIS IS:
#   The layer between main.py and every capability.
#   Main never imports capabilities directly anymore — it calls this.
#   This loads them, watches for changes, and hot-reloads without restart.
#
# HOW IT WORKS:
#   1. Reads capability_registry.json on startup
#   2. Imports every active capability's handler module
#   3. Watches the registry file in a background thread
#   4. When a new capability is registered, imports it live — no restart needed
#   5. dispatch(action, user_input, context) routes to the right handler
#
# CAPABILITY CONTRACT:
#   Every capability module must expose:
#
#     ACTIONS = ["action_name", ...]
#       List of action strings this capability handles.
#       Must match what context_router.py returns.
#
#     def handle(action: str, user_input: str, context: dict) -> dict:
#       Runs the capability. Returns a result dict:
#       {
#           "success":   bool,
#           "response":  str | None,   # text to inject into prompt context
#           "speak":     str | None,   # say this before generating (ack)
#           "emotion":   str,          # emotion hint for TTS ("neutral" default)
#           "data":      dict,         # any extra data the caller needs
#       }
#
# HOW TO ADD A NEW CAPABILITY:
#   1. Create capabilities/your_cap.py with ACTIONS and handle()
#   2. Add entry to capability_registry.json with "script" pointing to it
#   3. Set "status": "active"
#   That's it. No main.py changes. She picks it up within seconds.
#
# HOW HAYEONG ADDS HER OWN:
#   Same process. She writes the script, updates the registry.
#   The loader detects the registry change and imports it live.
#   Main never touched.

import importlib
import importlib.util
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("capability_loader")

# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────

BASE_DIR         = Path(__file__).parent
REGISTRY_FILE    = BASE_DIR / "capability_registry.json"
CAPABILITIES_DIR = BASE_DIR / "capabilities"

# Ensure capabilities directory exists
CAPABILITIES_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────
# RESULT HELPER
# Standard return shape for all capability handlers.
# ─────────────────────────────────────────────

def result(
    success:  bool        = True,
    response: str | None  = None,
    speak:    str | None  = None,
    emotion:  str         = "neutral",
    data:     dict        = None,
) -> dict:
    """
    Build a standard capability result dict.

    Parameters
    ----------
    success  : Whether the capability ran without error.
    response : Text context to inject into the AI prompt (e.g. search results).
               None means no context injection — AI responds normally.
    speak    : Short phrase to speak immediately (ack) before AI generates.
               None means no pre-speak.
    emotion  : TTS emotion hint for the speak phrase.
    data     : Any extra structured data the caller wants back.
    """
    return {
        "success":  success,
        "response": response,
        "speak":    speak,
        "emotion":  emotion,
        "data":     data or {},
    }


# ─────────────────────────────────────────────
# CAPABILITY LOADER
# ─────────────────────────────────────────────

class CapabilityLoader:
    """
    Loads, watches, and dispatches Hayeong's capabilities.

    Usage
    -----
    loader = CapabilityLoader()
    loader.start()   # begins watching registry for changes

    result = loader.dispatch("web_search", "what's the weather?", context)
    if result["speak"]:
        speak(result["speak"])
    if result["response"]:
        inject into prompt
    """

    def __init__(self):
        self._handlers: dict[str, object]  = {}  # action → module
        self._modules:  dict[str, object]  = {}  # capability_id → module
        self._registry: dict               = {}
        self._lock      = threading.Lock()
        self._watcher   = None
        self._running   = False
        self._last_mtime = 0.0

    # ─────────────────────────────────────────
    # STARTUP
    # ─────────────────────────────────────────

    def start(self):
        """Load all active capabilities and start watching for changes."""
        self._load_registry()
        self._import_all_active()

        self._running = True
        self._watcher = threading.Thread(
            target=self._watch_registry,
            daemon=True,
            name="capability_watcher"
        )
        self._watcher.start()
        log.info(f"Capability loader started — {len(self._handlers)} actions registered")

    def stop(self):
        """Stop the registry watcher."""
        self._running = False
        log.info("Capability loader stopped")

    # ─────────────────────────────────────────
    # DISPATCH
    # ─────────────────────────────────────────

    def dispatch(self, action: str, user_input: str, context: dict) -> dict:
        """
        Route an action to the right capability handler.

        Parameters
        ----------
        action     : Action string from context_router (e.g. "web_search")
        user_input : Raw user message
        context    : Dict with memory, mood, decision data, etc.

        Returns a standard result dict. If no handler is found,
        returns a no-op result so main can fall through to conversation.
        """
        with self._lock:
            module = self._handlers.get(action)

        if module is None:
            log.debug(f"No handler for action: {action!r}")
            return result(success=False, data={"reason": "no_handler"})

        # ── Pre-dispatch: ensure required applications are running ──
        # If a capability needs ComfyUI, Ollama, etc., start them now
        # before trying to run the capability. She never hits a tool
        # that fails just because the underlying app wasn't running.
        try:
            from app_manager import get_app_manager
            mgr      = get_app_manager()
            ok, msgs = mgr.ensure_for_capability(action)
            if msgs:
                speak_fn = context.get("speak_fn")
                for msg in msgs:
                    log.info(f"  [AppManager] {msg}")
                    # Speak first message so James knows what she's doing
                    if speak_fn and msgs.index(msg) == 0:
                        speak_fn(msg, emotion="neutral")
            if not ok:
                # At least one required app failed to start — warn but proceed
                # She'll fail gracefully inside the capability if it can't connect
                log.warning(f"  [AppManager] not all required apps started for {action!r}")
        except ImportError:
            pass  # app_manager not available yet — skip silently

        try:
            return module.handle(action, user_input, context)
        except Exception as e:
            log.error(f"Capability error [{action}]: {e}")
            return result(
                success=False,
                speak="Something went wrong on my end.",
                data={"error": str(e)},
            )

    def handles(self, action: str) -> bool:
        """Return True if a handler is registered for this action."""
        with self._lock:
            return action in self._handlers

    def list_loaded(self) -> list[str]:
        """Return list of all currently loaded action names."""
        with self._lock:
            return list(self._handlers.keys())

    def list_capabilities(self) -> list[dict]:
        """Return summary of all active capabilities from registry."""
        caps = []
        registry = self._registry
        for section in ("built_in_capabilities", "self_generated_capabilities"):
            for cap in registry.get(section, {}).get("capabilities", []):
                if cap.get("status") == "active":
                    caps.append({
                        "id":     cap["id"],
                        "name":   cap["name"],
                        "loaded": cap["id"] in self._modules,
                    })
        return caps

    # ─────────────────────────────────────────
    # REGISTRY LOADING
    # ─────────────────────────────────────────

    def _load_registry(self):
        """Read capability_registry.json into memory."""
        if not REGISTRY_FILE.exists():
            log.warning(f"Registry not found: {REGISTRY_FILE}")
            self._registry = {}
            return
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                self._registry = json.load(f)
            self._last_mtime = REGISTRY_FILE.stat().st_mtime
            log.debug("Registry loaded")
        except Exception as e:
            log.error(f"Failed to load registry: {e}")
            self._registry = {}

    def _import_all_active(self):
        """Import every active capability that has a script."""
        registry = self._registry
        imported = 0
        skipped  = 0

        for section in ("built_in_capabilities", "self_generated_capabilities"):
            for cap in registry.get(section, {}).get("capabilities", []):
                if cap.get("status") != "active":
                    continue
                script = cap.get("script")
                if not script:
                    continue  # subprocess-only capability, no handler
                cap_id = cap["id"]
                ok = self._import_capability(cap_id, script)
                if ok:
                    imported += 1
                else:
                    skipped += 1

        log.info(f"Capabilities imported: {imported}, skipped (no file): {skipped}")

    def _import_capability(self, cap_id: str, script: str) -> bool:
        """
        Import a single capability module and register its action handlers.
        Returns True if successful.
        """
        # Resolve script path — check capabilities/ dir first, then base dir
        script_name = Path(script).name
        candidates  = [
            CAPABILITIES_DIR / script_name,
            BASE_DIR / script,
            BASE_DIR / script_name,
        ]
        script_path = next((p for p in candidates if p.exists()), None)

        if script_path is None:
            log.debug(f"  [{cap_id}] script not found: {script} — skipping")
            return False

        try:
            # Load the module from file path
            module_name = f"hayeong_cap_{cap_id}"
            spec   = importlib.util.spec_from_file_location(module_name, script_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Check it has the required interface
            if not hasattr(module, "handle"):
                log.debug(f"  [{cap_id}] no handle() function — not a capability handler")
                return False

            if not hasattr(module, "ACTIONS"):
                log.debug(f"  [{cap_id}] no ACTIONS list — not registering as dispatcher")
                return False

            # Register under each action it handles
            with self._lock:
                self._modules[cap_id] = module
                for action in module.ACTIONS:
                    self._handlers[action] = module
                    log.info(f"  [{cap_id}] registered action: {action!r}")

            return True

        except Exception as e:
            log.error(f"  [{cap_id}] import error: {e}")
            return False

    def _reload_capability(self, cap_id: str, script: str):
        """Hot-reload a capability that was already imported."""
        module_name = f"hayeong_cap_{cap_id}"
        if module_name in sys.modules:
            # Remove old action registrations
            old_module = sys.modules.get(module_name)
            if old_module and hasattr(old_module, "ACTIONS"):
                with self._lock:
                    for action in old_module.ACTIONS:
                        if self._handlers.get(action) is old_module:
                            del self._handlers[action]
            del sys.modules[module_name]

        return self._import_capability(cap_id, script)

    # ─────────────────────────────────────────
    # REGISTRY WATCHER
    # Background thread. Checks for registry changes every 3 seconds.
    # When the file changes, diffs against loaded state and hot-reloads
    # new or updated capabilities.
    # ─────────────────────────────────────────

    def _watch_registry(self):
        log.info("Registry watcher running")
        while self._running:
            time.sleep(3)
            try:
                if not REGISTRY_FILE.exists():
                    continue
                mtime = REGISTRY_FILE.stat().st_mtime
                if mtime <= self._last_mtime:
                    continue

                # File changed — reload
                log.info("Registry changed — checking for new capabilities")
                old_registry = self._registry.copy()
                self._load_registry()
                self._diff_and_reload(old_registry, self._registry)

            except Exception as e:
                log.error(f"Watcher error: {e}")

        log.info("Registry watcher stopped")

    def _diff_and_reload(self, old: dict, new: dict):
        """
        Compare old and new registry. Import new capabilities,
        reload changed ones, deactivate removed ones.
        """
        def get_caps(registry):
            caps = {}
            for section in ("built_in_capabilities", "self_generated_capabilities"):
                for cap in registry.get(section, {}).get("capabilities", []):
                    caps[cap["id"]] = cap
            return caps

        old_caps = get_caps(old)
        new_caps = get_caps(new)

        for cap_id, cap in new_caps.items():
            script = cap.get("script")
            if not script:
                continue

            if cap.get("status") != "active":
                # Deactivate if it was loaded
                if cap_id in self._modules:
                    self._deactivate(cap_id)
                continue

            if cap_id not in old_caps:
                # New capability — import it
                log.info(f"New capability detected: {cap_id!r} — importing")
                self._import_capability(cap_id, script)

            elif cap != old_caps.get(cap_id):
                # Changed capability — hot-reload
                log.info(f"Capability updated: {cap_id!r} — reloading")
                self._reload_capability(cap_id, script)

    def _deactivate(self, cap_id: str):
        """Remove a capability's handlers from the dispatch table."""
        module = self._modules.get(cap_id)
        if module and hasattr(module, "ACTIONS"):
            with self._lock:
                for action in module.ACTIONS:
                    if self._handlers.get(action) is module:
                        del self._handlers[action]
                del self._modules[cap_id]
            log.info(f"Capability deactivated: {cap_id!r}")


# ─────────────────────────────────────────────
# SINGLETON
# One loader instance shared across main.py
# ─────────────────────────────────────────────

_loader: Optional[CapabilityLoader] = None

def get_loader() -> CapabilityLoader:
    """Return the global loader instance, creating it if needed."""
    global _loader
    if _loader is None:
        _loader = CapabilityLoader()
    return _loader
