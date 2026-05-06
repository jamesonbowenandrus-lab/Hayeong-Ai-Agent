# hayeong_state.py
# Shared state bus between brain, voice, and text interface processes.
#
# All reads and writes go through file locking so concurrent processes
# don't corrupt the JSON. Functions are small and intentionally simple.
#
# State file: hayeong_state.json (created automatically if missing)
# Lock file:  hayeong_state.lock

import json
import uuid
import datetime
from pathlib import Path

try:
    from filelock import FileLock
    _FILELOCK_AVAILABLE = True
except ImportError:
    _FILELOCK_AVAILABLE = False

BASE_DIR   = Path(__file__).parent
STATE_FILE = BASE_DIR / "hayeong_state.json"
LOCK_FILE  = BASE_DIR / "hayeong_state.lock"

_EMPTY_STATE = {
    "input_queue":  [],
    "output_queue": [],
    "interface_status": {
        "voice_server": "unknown",
        "voice_client": "unknown",
        "text":         "unknown",
    },
    "brain_status": "unknown",
}


# ─────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────

def _lock():
    if _FILELOCK_AVAILABLE:
        return FileLock(str(LOCK_FILE), timeout=3)
    # Fallback context manager that does nothing
    import contextlib
    return contextlib.nullcontext()


def _read() -> dict:
    if not STATE_FILE.exists():
        return {k: (v.copy() if isinstance(v, (dict, list)) else v)
                for k, v in _EMPTY_STATE.items()}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {k: (v.copy() if isinstance(v, (dict, list)) else v)
                for k, v in _EMPTY_STATE.items()}


def _write(state: dict):
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def push_input(content: str, source: str = "text") -> str:
    """Write a user message to the input queue. Returns the message id."""
    msg_id = f"msg_{uuid.uuid4().hex[:8]}"
    entry  = {
        "id":        msg_id,
        "source":    source,
        "content":   content,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    with _lock():
        state = _read()
        state["input_queue"].append(entry)
        _write(state)
    return msg_id


def pop_input() -> dict | None:
    """Remove and return the oldest input queue entry, or None if empty."""
    with _lock():
        state = _read()
        if not state["input_queue"]:
            return None
        msg = state["input_queue"].pop(0)
        _write(state)
    return msg


def push_output(reply_to: str, content: str):
    """Write a brain response to the output queue."""
    entry = {
        "id":        f"resp_{uuid.uuid4().hex[:8]}",
        "reply_to":  reply_to,
        "content":   content,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    with _lock():
        state = _read()
        state["output_queue"].append(entry)
        _write(state)


def pop_output() -> dict | None:
    """Remove and return the oldest output queue entry, or None if empty."""
    with _lock():
        state = _read()
        if not state["output_queue"]:
            return None
        resp = state["output_queue"].pop(0)
        _write(state)
    return resp


def set_brain_status(status: str):
    with _lock():
        state = _read()
        state["brain_status"] = status
        _write(state)


def set_interface_status(interface: str, status: str):
    with _lock():
        state = _read()
        state.setdefault("interface_status", {})[interface] = status
        _write(state)


def push_system_alert(interface: str, status: str, reason: str = ""):
    """Write a system alert to the state so the brain can notify James."""
    entry = {
        "id":        f"alert_{uuid.uuid4().hex[:8]}",
        "interface": interface,
        "status":    status,
        "reason":    reason,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    with _lock():
        state = _read()
        state.setdefault("system_alerts", []).append(entry)
        state.setdefault("interface_status", {})[interface] = status
        _write(state)


def pop_system_alert() -> dict | None:
    """Remove and return the oldest system alert, or None if empty."""
    with _lock():
        state = _read()
        alerts = state.get("system_alerts", [])
        if not alerts:
            return None
        alert = alerts.pop(0)
        state["system_alerts"] = alerts
        _write(state)
    return alert


def get_status() -> dict:
    with _lock():
        state = _read()
    return {
        "brain":      state.get("brain_status", "unknown"),
        "interfaces": state.get("interface_status", {}),
        "input_len":  len(state.get("input_queue", [])),
        "output_len": len(state.get("output_queue", [])),
    }
