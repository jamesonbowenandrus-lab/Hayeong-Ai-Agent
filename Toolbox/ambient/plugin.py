"""
toolbox/ambient/plugin.py — Ambient Presence Plugin

Feeds Hayeong continuous awareness of time, James's presence, unresolved work,
and her own queued thoughts. Runs on the existing plugin heartbeat.

PERSISTENT = True — this plugin loads at startup because it provides continuous
ambient awareness that should always be present, not just when a tool is used.

Writes to core.json["ambient"] every 30 seconds. The reasoning loop and presence
loop read from this section to build context-aware prompts.

Public API:
    add_inner_note(note: str)   — reasoning loop calls this to queue a passing thought
    get_inner_notes() -> list   — returns current thought queue
    clear_inner_note(note: str) — removes a note after it has been surfaced to James
    format_ambient(ambient: dict) -> str  — formats ambient dict as human-readable paragraph
"""

import time
from datetime import datetime

from brain.config import (
    AMBIENT_JAMES_ABSENT_THRESHOLD_MINUTES,
    AMBIENT_MAX_INNER_NOTES,
)

PERSISTENT = True   # always load at startup — this is continuous ambient awareness

_inner_notes: list  = []             # in-memory queue of passing thoughts (ephemeral)
_session_start      = datetime.now() # when this session began
_last_update_at     = 0.0            # throttle: only update state every 30s
_UPDATE_INTERVAL    = 30             # seconds


# ─────────────────────────────────────────────
# PLUGIN INTERFACE
# ─────────────────────────────────────────────

def tick():
    """Called every 2 seconds by the plugin loop. Throttled internally to 30s updates."""
    global _last_update_at

    now = time.time()
    if now - _last_update_at < _UPDATE_INTERVAL:
        return
    _last_update_at = now

    try:
        from brain.state.core_manager import read, write_section
        state   = read()
        ambient = _build_ambient(state)
        write_section("ambient", ambient)
    except Exception:
        pass


def get_context_injection(state: dict = None) -> list:
    """
    Return a human-readable ambient paragraph for injection into presence context.
    Called by get_all_context_injections() in plugin_registry.py.
    """
    if state is None:
        try:
            from brain.state.core_manager import read
            state = read()
        except Exception:
            return []

    ambient = state.get("ambient", {})
    if not ambient:
        return []

    paragraph = format_ambient(ambient)
    return [paragraph] if paragraph else []


# ─────────────────────────────────────────────
# INNER NOTES QUEUE
# ─────────────────────────────────────────────

def add_inner_note(note: str):
    """Queue a passing thought. Called by the reasoning loop when something occurs to Hayeong."""
    global _inner_notes
    note = note.strip()
    if not note or note in _inner_notes:
        return
    _inner_notes.append(note)
    if len(_inner_notes) > AMBIENT_MAX_INNER_NOTES:
        _inner_notes.pop(0)   # oldest drops when queue is full


def get_inner_notes() -> list:
    """Return a copy of the current inner notes queue."""
    return list(_inner_notes)


def clear_inner_note(note: str):
    """Remove a note after it has been surfaced to James."""
    global _inner_notes
    if note in _inner_notes:
        _inner_notes.remove(note)


# ─────────────────────────────────────────────
# AMBIENT STATE BUILDER
# ─────────────────────────────────────────────

def _build_ambient(state: dict) -> dict:
    now = datetime.now()

    # ── James presence ────────────────────────────────────────────────
    situation   = state.get("situation", {})
    said_at_str = situation.get("said_at", "")

    james_present       = False
    james_last_seen     = ""
    minutes_since_james = 0

    if said_at_str:
        try:
            said_at             = datetime.fromisoformat(said_at_str)
            minutes_since_james = max(0, int((now - said_at).total_seconds() / 60))
            james_last_seen     = said_at.strftime("%H:%M")
            james_present       = minutes_since_james < AMBIENT_JAMES_ABSENT_THRESHOLD_MINUTES
        except Exception:
            pass

    # ── Unresolved work ───────────────────────────────────────────────
    last_task      = state.get("last_task", {})
    task_status    = last_task.get("status", "")
    unresolved     = 1 if task_status in ("pending", "running") else 0

    # ── Active tools ──────────────────────────────────────────────────
    active_tools = []
    if task_status in ("pending", "running"):
        tool = last_task.get("tool", "")
        if tool:
            active_tools.append(tool)

    # ── Session duration ──────────────────────────────────────────────
    session_minutes = max(0, int((now - _session_start).total_seconds() / 60))

    return {
        "james_present":            james_present,
        "james_last_seen":          james_last_seen,
        "minutes_since_james":      minutes_since_james,
        "session_duration_minutes": session_minutes,
        "unresolved_count":         unresolved,
        "active_tools":             active_tools,
        "inner_notes":              list(_inner_notes),
    }


# ─────────────────────────────────────────────
# FORMATTING
# ─────────────────────────────────────────────

def format_ambient(ambient: dict) -> str:
    """
    Convert an ambient dict to a natural-language paragraph Hayeong reads as
    self-awareness, not as a data printout.
    """
    parts = []

    minutes = ambient.get("minutes_since_james", 0)
    if ambient.get("james_present"):
        parts.append("James is present.")
    elif minutes > 0:
        s = "s" if minutes != 1 else ""
        parts.append(f"James was last present {minutes} minute{s} ago.")
    else:
        parts.append("James has not messaged yet this session.")

    unresolved = ambient.get("unresolved_count", 0)
    if unresolved:
        parts.append(f"{'1 task is' if unresolved == 1 else f'{unresolved} tasks are'} unresolved.")

    notes = ambient.get("inner_notes", [])
    if notes:
        count = len(notes)
        preview = notes[0][:80]
        label   = "1 passing thought" if count == 1 else f"{count} passing thoughts"
        parts.append(f"{label} queued: \"{preview}\"")

    tools = ambient.get("active_tools", [])
    if tools:
        label = "tool" if len(tools) == 1 else "tools"
        parts.append(f"Active {label}: {', '.join(tools)}.")

    session = ambient.get("session_duration_minutes", 0)
    if session >= 10:
        parts.append(f"Session has been running {session} minutes.")

    if not parts:
        return ""
    return "[Ambient] " + " ".join(parts)
