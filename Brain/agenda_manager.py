"""
Brain/agenda_manager.py
Read/write interface for Brain/inner_agenda.json
Pattern: same as core_manager.py — FileLock, utf-8, load-before-write
"""

import json
import uuid
import datetime
from pathlib import Path

from filelock import FileLock

from brain.config import INNER_AGENDA_PATH

_AGENDA_PATH = Path(INNER_AGENDA_PATH)
_LOCK_PATH   = str(_AGENDA_PATH) + ".lock"

_DEFAULT_AGENDA = {
    "current_focus":      "I am just waking up. I am reading my situation and forming my first thoughts.",
    "unresolved":         [],
    "wants":              [],
    "mood_context":       {"state": "present and orienting", "reason": "First session with inner agenda active."},
    "threads":            [],
    "notification_queue": [],
    "last_thought_at":    None,
    "last_interaction_at": None,
}


# ── Raw I/O (no lock — callers hold the lock before calling these) ───────────

def _read_raw() -> dict:
    if not _AGENDA_PATH.exists():
        return dict(_DEFAULT_AGENDA)
    try:
        with open(_AGENDA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dict(_DEFAULT_AGENDA)


def _write_raw(agenda: dict) -> None:
    _AGENDA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_AGENDA_PATH, "w", encoding="utf-8") as f:
        json.dump(agenda, f, indent=2, ensure_ascii=False)


# ── Public API ────────────────────────────────────────────────────────────────

def load_agenda() -> dict:
    """Load and return the full inner agenda. Returns default structure if file missing."""
    return _read_raw()


def save_agenda(agenda: dict) -> None:
    """Save agenda dict to inner_agenda.json. Always utf-8. Always FileLock."""
    lock = FileLock(_LOCK_PATH, timeout=10)
    with lock:
        _write_raw(agenda)


def update_focus(focus: str) -> None:
    """Update current_focus field."""
    lock = FileLock(_LOCK_PATH, timeout=10)
    with lock:
        agenda = _read_raw()
        agenda["current_focus"] = focus
        _write_raw(agenda)


def add_thread(content: str, weight: str = "medium",
               moment_sensitive: bool = False, trigger_condition: str = None) -> str:
    """Add a new cognitive thread. Returns the thread id."""
    thread_id = f"thread_{uuid.uuid4().hex[:6]}"
    thread = {
        "id":                thread_id,
        "content":           content,
        "weight":            weight,
        "moment_sensitive":  moment_sensitive,
        "trigger_condition": trigger_condition,
        "created_at":        datetime.datetime.now().isoformat(),
        "last_attended_at":  None,
    }
    lock = FileLock(_LOCK_PATH, timeout=10)
    with lock:
        agenda = _read_raw()
        agenda.setdefault("threads", []).append(thread)
        _write_raw(agenda)
    return thread_id


def remove_thread(thread_id: str) -> None:
    """Remove a thread by id."""
    lock = FileLock(_LOCK_PATH, timeout=10)
    with lock:
        agenda = _read_raw()
        agenda["threads"] = [t for t in agenda.get("threads", []) if t.get("id") != thread_id]
        _write_raw(agenda)


def update_thread_attended(thread_id: str) -> None:
    """Update last_attended_at on a thread to now."""
    lock = FileLock(_LOCK_PATH, timeout=10)
    with lock:
        agenda = _read_raw()
        for thread in agenda.get("threads", []):
            if thread.get("id") == thread_id:
                thread["last_attended_at"] = datetime.datetime.now().isoformat()
                break
        _write_raw(agenda)


def add_to_unresolved(item: str) -> None:
    """Append an item to the unresolved list. Does not duplicate."""
    lock = FileLock(_LOCK_PATH, timeout=10)
    with lock:
        agenda = _read_raw()
        unresolved = agenda.setdefault("unresolved", [])
        if item not in unresolved:
            unresolved.append(item)
        _write_raw(agenda)


def add_want(want: str) -> None:
    """Append an item to the wants list. Does not duplicate."""
    lock = FileLock(_LOCK_PATH, timeout=10)
    with lock:
        agenda = _read_raw()
        wants = agenda.setdefault("wants", [])
        if want not in wants:
            wants.append(want)
        _write_raw(agenda)


def update_mood(state: str, reason: str) -> None:
    """Update mood_context."""
    lock = FileLock(_LOCK_PATH, timeout=10)
    with lock:
        agenda = _read_raw()
        agenda["mood_context"] = {"state": state, "reason": reason}
        _write_raw(agenda)


def add_notification(content: str, triggered_by: str,
                     action_taken: str = None, priority: str = "medium") -> None:
    """Add a notification to the queue for James to see on next interaction."""
    notif = {
        "id":           f"notif_{uuid.uuid4().hex[:6]}",
        "content":      content,
        "created_at":   datetime.datetime.now().isoformat(),
        "triggered_by": triggered_by,
        "action_taken": action_taken,
        "priority":     priority,
    }
    lock = FileLock(_LOCK_PATH, timeout=10)
    with lock:
        agenda = _read_raw()
        agenda.setdefault("notification_queue", []).append(notif)
        _write_raw(agenda)


def pop_notifications() -> list:
    """Return all pending notifications and clear the queue."""
    lock = FileLock(_LOCK_PATH, timeout=10)
    with lock:
        agenda = _read_raw()
        notifs = list(agenda.get("notification_queue", []))
        agenda["notification_queue"] = []
        _write_raw(agenda)
    return notifs


def update_last_thought_at() -> None:
    """Update last_thought_at to now."""
    lock = FileLock(_LOCK_PATH, timeout=10)
    with lock:
        agenda = _read_raw()
        agenda["last_thought_at"] = datetime.datetime.now().isoformat()
        _write_raw(agenda)


def update_last_interaction_at() -> None:
    """Update last_interaction_at to now."""
    lock = FileLock(_LOCK_PATH, timeout=10)
    with lock:
        agenda = _read_raw()
        agenda["last_interaction_at"] = datetime.datetime.now().isoformat()
        _write_raw(agenda)


def get_idle_minutes() -> float:
    """Return minutes since last interaction. Returns large number if last_interaction_at is null."""
    agenda = _read_raw()
    last_interaction = agenda.get("last_interaction_at")
    if not last_interaction:
        return 9999.0
    try:
        ts    = datetime.datetime.fromisoformat(last_interaction)
        delta = (datetime.datetime.now() - ts).total_seconds() / 60.0
        return max(0.0, delta)
    except Exception:
        return 9999.0


def select_tick_focus(agenda: dict) -> dict | None:
    """
    Select which thread to focus on this tick.

    Priority logic:
    1. Filter out moment_sensitive threads if no active shared task (read core.json)
    2. Sort remaining by weight (high > medium > low)
    3. Among same weight, prefer threads not recently attended
    4. Return the selected thread, or None if no threads exist

    The returned thread is a SUGGESTION — the LLM makes the final call.
    """
    threads = agenda.get("threads", [])
    if not threads:
        return None

    has_active_task = False
    try:
        from brain.state.core_manager import read as _read_core
        state = _read_core()
        task_status = state.get("last_task", {}).get("status", "")
        has_active_task = task_status in ("pending", "running")
    except Exception:
        pass

    candidates = [
        t for t in threads
        if not (t.get("moment_sensitive") and not has_active_task)
    ]
    if not candidates:
        candidates = list(threads)

    _weight_order = {"high": 0, "medium": 1, "low": 2}

    def _sort_key(t: dict):
        w        = _weight_order.get(t.get("weight", "medium"), 1)
        attended = t.get("last_attended_at") or ""
        return (w, attended)

    candidates.sort(key=_sort_key)
    return candidates[0] if candidates else None
