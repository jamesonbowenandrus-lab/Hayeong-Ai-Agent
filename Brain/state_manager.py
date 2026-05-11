"""
state_manager.py
─────────────────
Shared state for the reasoning loop. Provides the interface reasoning_loop.py
needs, backed by its own JSON file (reasoning_state.json), independent of
core.json so the two schemas don't collide.
"""

import copy
import json
import threading
from pathlib import Path

try:
    from filelock import FileLock as _FileLock
    _LOCK_AVAILABLE = True
except ImportError:
    _LOCK_AVAILABLE = False

_BASE       = Path(__file__).parent / "state"
_STATE_FILE = _BASE / "reasoning_state.json"
_LOCK_FILE  = _BASE / "reasoning_state.lock"
_w_lock     = threading.Lock()

_EMPTY_REASONING: dict = {
    "active_task":                "",
    "active_task_status":         "",
    "current_goal":               "",
    "last_conclusion":            "",
    "context_for_communication":  "",
    "minecraft_session_active":   False,
    "minecraft_last_event":       "",
    "minecraft_last_event_detail": {},
    "minecraft_pending_action":   None,
    "minecraft_voice_input":      "",
    "priority_flags":             [],
    "pending_results":            [],
    "commitments":                [],
    "self_assessment":            "",
    "self_assessment_at":         "",
    "task_queue":                 [],
}


def _file_lock():
    if _LOCK_AVAILABLE:
        return _FileLock(str(_LOCK_FILE), timeout=3)
    import contextlib
    return contextlib.nullcontext()


def _read_raw() -> dict:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"reasoning": copy.deepcopy(_EMPTY_REASONING)}


def _write_raw(state: dict) -> None:
    _BASE.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def read_state() -> dict:
    with _file_lock():
        return _read_raw()


def write_reasoning(updates: dict) -> None:
    with _w_lock:
        with _file_lock():
            state = _read_raw()
            state.setdefault("reasoning", {}).update(updates)
            _write_raw(state)


def pop_priority_flags() -> list:
    with _w_lock:
        with _file_lock():
            state = _read_raw()
            flags = state.get("reasoning", {}).get("priority_flags", [])
            state.setdefault("reasoning", {})["priority_flags"] = []
            _write_raw(state)
            return flags


def pop_pending_results() -> list:
    with _w_lock:
        with _file_lock():
            state   = _read_raw()
            results = state.get("reasoning", {}).get("pending_results", [])
            state.setdefault("reasoning", {})["pending_results"] = []
            _write_raw(state)
            return results


def pop_minecraft_pending_action() -> dict:
    """Read and clear the pending Minecraft action written by the reasoning loop."""
    with _w_lock:
        with _file_lock():
            state  = _read_raw()
            action = state.get("reasoning", {}).get("minecraft_pending_action") or {}
            state.setdefault("reasoning", {})["minecraft_pending_action"] = None
            _write_raw(state)
            return action


def flag_priority(flag: str, **data) -> None:
    with _w_lock:
        with _file_lock():
            state = _read_raw()
            flags = state.setdefault("reasoning", {}).setdefault("priority_flags", [])
            flags.append({"flag": flag, **data})
            _write_raw(state)
