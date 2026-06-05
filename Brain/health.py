"""
Brain/health.py — Hayeong's system self-awareness.

Checks all core components at startup and on demand.
Results are written to the "health" section of shared state so the presence
loop can read them and tell James if something is wrong.

Exposed functions:
    run_health_check()   — run all checks, write to state, return dict
    get_health_summary() — read last result from state (no re-check)
    is_degraded()        — True if last check reported degraded status
    get_tool_errors()    — per-tool error messages from last check
"""

import importlib
import json
from datetime import datetime
from pathlib import Path

import requests

from brain.config import MEMORY_DIR, TOOLBOX_DIR

_last_tool_errors: dict = {}   # {tool_name: error_str} from last _check_tools()


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def run_health_check() -> dict:
    """
    Run all checks, write results to shared state, and return the health dict.
    Never raises — all failures are captured and returned as dict fields.
    """
    global _last_tool_errors
    _last_tool_errors = {}

    llm_presence          = _check_llm(11435)
    tools_healthy, tools_failed = _check_tools()
    memory_accessible     = _check_memory()
    state_bus_ok          = _check_state_bus()
    plugins_loaded        = _check_plugins()

    degraded_reasons = []
    if not llm_presence:
        degraded_reasons.append("presence LLM (11435) offline")
    if tools_failed:
        degraded_reasons.append(
            f"{len(tools_failed)} tool(s) failed to import: {', '.join(tools_failed)}"
        )
    if not memory_accessible:
        degraded_reasons.append("memory layer inaccessible")
    if not state_bus_ok:
        degraded_reasons.append("state bus unreadable")

    degraded = bool(degraded_reasons)

    health = {
        "checked_at":        datetime.now().isoformat(),
        "llm_presence":      llm_presence,
        "tools_healthy":     tools_healthy,
        "tools_failed":      tools_failed,
        "memory_accessible": memory_accessible,
        "state_bus_ok":      state_bus_ok,
        "plugins_loaded":    plugins_loaded,
        "degraded":          degraded,
        "degraded_reason":   ", ".join(degraded_reasons) if degraded_reasons else "",
    }

    try:
        from brain.state.core_manager import write_section
        write_section("health", health)
    except Exception as e:
        print(f"[health] Could not write health to state: {e}")

    return health


def get_health_summary() -> dict:
    """Return the last health check result from shared state. Does not re-run checks."""
    try:
        from brain.state.core_manager import read
        return read().get("health", {})
    except Exception:
        return {}


def is_degraded() -> bool:
    """True if the last health check reported any degraded condition."""
    return bool(get_health_summary().get("degraded", False))


def get_tool_errors() -> dict:
    """Return per-tool error strings from the last run_health_check() call."""
    return dict(_last_tool_errors)


# ─────────────────────────────────────────────
# CHECKS
# ─────────────────────────────────────────────

def _check_llm(port: int) -> bool:
    try:
        resp = requests.get(f"http://localhost:{port}/", timeout=3)
        return resp.status_code < 500
    except Exception:
        return False


def _check_tools() -> tuple:
    """
    Try importing each tool module from registry.json.
    Returns (healthy_names, failed_names). Populates _last_tool_errors.
    """
    healthy, failed = [], []

    try:
        registry_path = Path(TOOLBOX_DIR) / "registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[health] Could not read tool registry: {e}")
        return [], []

    for tool_name, entry in registry.items():
        module_path = entry.get("module", "")
        if not module_path:
            continue
        try:
            importlib.import_module(module_path)
            healthy.append(tool_name)
        except Exception as e:
            failed.append(tool_name)
            _last_tool_errors[tool_name] = str(e)
            print(f"[health] Tool import failed: {tool_name} — {e}")

    return healthy, failed


def _check_memory() -> bool:
    """Confirm the Memory/ directory exists and is readable. Does not load data."""
    try:
        memory_dir = Path(MEMORY_DIR)
        if not memory_dir.is_dir():
            return False
        # Listing the directory is enough to confirm it's readable
        list(memory_dir.iterdir())
        return True
    except Exception:
        return False


def _check_state_bus() -> bool:
    """
    Confirm Brain/state/core.json is readable JSON.
    Calls core_manager.read() which handles corruption and missing files gracefully.
    """
    try:
        from brain.state.core_manager import read
        state = read()
        return isinstance(state, dict)
    except Exception:
        return False


def _check_plugins() -> int:
    """Return the count of currently loaded plugins."""
    try:
        from toolbox.plugin_registry import _plugins
        return len(_plugins)
    except Exception:
        return 0
