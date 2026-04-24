"""
state_manager.py
Shared state bus connecting the Communication LLM and the Reasoning LLM.

Access rules:
  Communication LLM  — reads reasoning section, writes conversation section
  Reasoning LLM      — reads conversation section, writes reasoning section
  Scripts            — write to system.active_scripts and system.pending_results
  Both LLMs          — read system section

Uses the same file-locking pattern as hayeong_state.py.
State file: state/shared_state.json
"""

import datetime
import json
import uuid
from pathlib import Path

try:
    from filelock import FileLock
    _FILELOCK_AVAILABLE = True
except ImportError:
    _FILELOCK_AVAILABLE = False

BASE_DIR    = Path(__file__).parent
STATE_FILE  = BASE_DIR / "state" / "shared_state.json"
LOCK_FILE   = BASE_DIR / "state" / "shared_state.lock"

_EMPTY_STATE = {
    "conversation": {
        "last_james_message":    "",
        "last_hayeong_response": "",
        "current_topic":         "",
        "session_start":         "",
        "flags":                 [],
    },
    "reasoning": {
        "current_goal":               "",
        "task_queue":                 [],
        "active_task":                "",
        "active_task_status":         "",
        "last_conclusion":            "",
        "context_for_communication":  "",
        "minecraft_state":            {},
        "minecraft_session_active":    False,
        "minecraft_last_event":        "",
        "minecraft_last_event_detail": {},
        "minecraft_pending_action":    {},
        "minecraft_last_result":       "",
        "minecraft_voice_input":       "",
        "minecraft_urgency":           "normal",
    },
    "system": {
        "active_scripts":  [],
        "pending_results": [],
        "priority_flags":  [],
        "models_loaded":   [],
        "health": {
            "communication_llm": "unknown",
            "reasoning_llm":     "unknown",
            "voice_server":      "unknown",
            "whisper":           "unknown",
        },
    },
}


# ─────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────

def _lock():
    if _FILELOCK_AVAILABLE:
        return FileLock(str(LOCK_FILE), timeout=3)
    import contextlib
    return contextlib.nullcontext()


def _read() -> dict:
    if not STATE_FILE.exists():
        return json.loads(json.dumps(_EMPTY_STATE))   # deep copy
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(_EMPTY_STATE))


def _write(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def read_state() -> dict:
    """Return a full snapshot of shared state. Safe to call from any thread."""
    with _lock():
        return _read()


def write_conversation(updates: dict):
    """
    Communication LLM writes here after generating a response.
    Accepted keys: last_james_message, last_hayeong_response,
                   current_topic, session_start, flags
    """
    with _lock():
        state = _read()
        state["conversation"].update(updates)
        _write(state)


def write_reasoning(updates: dict):
    """
    Reasoning LLM writes here after processing a turn or heartbeat.
    Accepted keys: current_goal, task_queue, active_task, active_task_status,
                   last_conclusion, context_for_communication, minecraft_state
    """
    with _lock():
        state = _read()
        state["reasoning"].update(updates)
        _write(state)


def write_system(updates: dict):
    """
    Scripts write active_scripts and pending_results here.
    Either LLM may write priority_flags or models_loaded.
    Accepted keys: active_scripts, pending_results, priority_flags, models_loaded
    """
    with _lock():
        state = _read()
        state["system"].update(updates)
        _write(state)


def flag_priority(message: str, level: str = "normal"):
    """
    Add a priority flag so the reasoning LLM picks it up on next heartbeat.
    level: "urgent" | "high" | "normal" | "background"
    """
    entry = {
        "id":        f"flag_{uuid.uuid4().hex[:8]}",
        "message":   message,
        "level":     level,
        "timestamp": datetime.datetime.now().isoformat(),
        "source":    "communication_llm",
    }
    with _lock():
        state = _read()
        state["system"]["priority_flags"].append(entry)
        _write(state)


def pop_priority_flags() -> list:
    """Remove and return all pending priority flags. Called by reasoning heartbeat."""
    with _lock():
        state = _read()
        flags = state["system"].get("priority_flags", [])
        if not flags:
            return []
        state["system"]["priority_flags"] = []
        _write(state)
    return flags


def get_communication_context() -> dict:
    """
    Pull the fields the communication LLM needs before generating a response.
    Returns a subset of shared state — only what 7b needs to inject into its prompt.
    """
    with _lock():
        state = _read()
    r = state.get("reasoning", {})
    return {
        "context_for_communication": r.get("context_for_communication", ""),
        "active_task":               r.get("active_task", ""),
        "active_task_status":        r.get("active_task_status", ""),
        "current_goal":              r.get("current_goal", ""),
    }


def mark_model_loaded(model_key: str):
    """Record that a model is loaded and ready."""
    with _lock():
        state = _read()
        loaded = state["system"].get("models_loaded", [])
        if model_key not in loaded:
            loaded.append(model_key)
        state["system"]["models_loaded"] = loaded
        _write(state)


def add_pending_result(script_name: str, result: dict):
    """Scripts call this when they produce a result for the reasoning LLM to consume."""
    entry = {
        "id":          f"result_{uuid.uuid4().hex[:8]}",
        "script":      script_name,
        "result":      result,
        "timestamp":   datetime.datetime.now().isoformat(),
    }
    with _lock():
        state = _read()
        state["system"]["pending_results"].append(entry)
        _write(state)


def pop_pending_results() -> list:
    """Remove and return all pending script results. Called by reasoning heartbeat."""
    with _lock():
        state = _read()
        results = state["system"].get("pending_results", [])
        if not results:
            return []
        state["system"]["pending_results"] = []
        _write(state)
    return results


def pop_minecraft_pending_action() -> dict:
    """Remove and return the pending Minecraft action. Called by the bridge after each event."""
    with _lock():
        state = _read()
        action = state["reasoning"].get("minecraft_pending_action", {})
        if not action:
            return {}
        state["reasoning"]["minecraft_pending_action"] = {}
        _write(state)
    return action


def consume_communication_context() -> str:
    """
    Read context_for_communication and immediately clear it.
    Called by the communication LLM (7b) before generating each response.
    Atomic — read and clear happen in the same lock acquisition.
    Returns the context string, or empty string if nothing pending.
    """
    with _lock():
        state = _read()
        ctx = state["reasoning"].get("context_for_communication", "")
        if ctx:
            state["reasoning"]["context_for_communication"] = ""
            _write(state)
    return ctx


def get_and_clear_pending_action() -> dict:
    """
    Read minecraft_pending_action and clear it atomically.
    Called by minecraft_bridge when it's ready to send the next action.
    Returns the action dict, or {} if nothing pending.
    """
    return pop_minecraft_pending_action()


def has_pending_minecraft_action() -> bool:
    """
    Returns True if there is an unexecuted action waiting for the bridge.
    The reasoning loop checks this before writing a new action so it never
    overwrites an action the bridge hasn't sent yet.
    """
    with _lock():
        state = _read()
    return bool(state["reasoning"].get("minecraft_pending_action"))


def update_health(component: str, status: str):
    """
    Update health status for a system component.
    component: 'communication_llm' | 'reasoning_llm' | 'voice_server' | 'whisper'
    status: 'healthy' | 'degraded' | 'offline' | 'unknown'
    """
    with _lock():
        state = _read()
        if "health" not in state["system"]:
            state["system"]["health"] = {}
        state["system"]["health"][component] = status
        _write(state)


def get_health() -> dict:
    """Return current health status of all components."""
    with _lock():
        state = _read()
    return state["system"].get("health", {})


def validate_and_migrate():
    """
    Called once at startup. Ensures state file has all current schema keys.
    Merges in any missing keys from _EMPTY_STATE without touching existing values.
    Safe to call multiple times.
    """
    def _deep_merge(base: dict, update: dict) -> dict:
        for k, v in update.items():
            if k not in base:
                base[k] = v
            elif isinstance(v, dict) and isinstance(base.get(k), dict):
                _deep_merge(base[k], v)
        return base

    with _lock():
        state = _read()
        merged = _deep_merge(state, json.loads(json.dumps(_EMPTY_STATE)))
        _write(merged)
    print("[state_manager] State validated and migrated.")
