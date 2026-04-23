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
    },
    "system": {
        "active_scripts":  [],
        "pending_results": [],
        "priority_flags":  [],
        "models_loaded":   [],
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
