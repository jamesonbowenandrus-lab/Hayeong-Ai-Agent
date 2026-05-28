"""
context_manager.py
Manages the lifecycle of conversation context across a session.

Responsibilities:
- Monitors the conversation buffer for compression thresholds
- Maintains a session summary string for context injection
- Keeps the live buffer lean and relevant

Design rules:
- No LLM calls here — that's session_compressor's job
- Falls back gracefully — if unavailable, context assembly continues normally
- Thread-safe reads and writes via a lock
"""

import threading
from datetime import datetime
from typing import Optional

_session_summary: str = ""
_summary_lock = threading.Lock()
_last_compression_at: Optional[str] = None

# Compress when buffer reaches this many entries
COMPRESSION_THRESHOLD = 14
# Always keep this many recent entries raw (never compress these)
KEEP_RAW_RECENT = 6


def get_session_summary() -> str:
    """Return the current session summary. Thread-safe."""
    with _summary_lock:
        return _session_summary


def set_session_summary(summary: str) -> None:
    """Update the session summary. Thread-safe."""
    global _session_summary, _last_compression_at
    with _summary_lock:
        _session_summary = summary
        _last_compression_at = datetime.now().isoformat(timespec="seconds")


def should_compress(buffer_size: int) -> bool:
    """Return True when the buffer is large enough to compress."""
    return buffer_size >= COMPRESSION_THRESHOLD


def get_compressible_block(entries: list) -> list:
    """
    Return the entries that can be compressed — everything except
    the most recent KEEP_RAW_RECENT entries.
    """
    if len(entries) <= KEEP_RAW_RECENT:
        return []
    return entries[:-KEEP_RAW_RECENT]


def format_summary_for_context() -> str:
    """
    Return the session summary formatted for context injection.
    Returns empty string when no summary exists yet.
    """
    summary = get_session_summary()
    if not summary:
        return ""
    ts = _last_compression_at or "earlier this session"
    return f"--- Earlier this session (summarized at {ts}) ---\n{summary}\n--- End summary ---"
