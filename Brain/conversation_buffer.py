"""
conversation_buffer.py
In-memory ring buffer of recent James <-> Hayeong exchanges.

Written to by the presence loop after each completed exchange.
Read by build_presence_context() to inject conversational thread into the LLM.

Design rules:
- No file I/O in the hot path. Buffer lives in memory only.
- On startup it is empty — that is correct. She wakes fresh each session.
- Max 20 exchanges kept. Older ones drop off automatically.
- Each entry: {"role": "james"|"hayeong", "content": str, "at": ISO timestamp}
"""

from collections import deque
from datetime import datetime
from typing import List, Dict

_BUFFER: deque = deque(maxlen=20)


def add_james(message: str) -> None:
    """Call this when James sends a message."""
    _BUFFER.append({
        "role":    "james",
        "content": message,
        "at":      datetime.now().isoformat(timespec="seconds"),
    })


def add_hayeong(response: str) -> None:
    """Call this when Hayeong completes a response."""
    _BUFFER.append({
        "role":    "hayeong",
        "content": response,
        "at":      datetime.now().isoformat(timespec="seconds"),
    })


def get_recent(n: int = 10) -> List[Dict]:
    """Return the last n entries, oldest first."""
    entries = list(_BUFFER)
    return entries[-n:] if len(entries) > n else entries


def format_for_context(n: int = 10) -> str:
    """
    Return a formatted string block ready for injection into the system prompt.
    Returns empty string if buffer is empty (fresh session).
    """
    entries = get_recent(n)
    if not entries:
        return ""

    lines = ["--- Recent conversation ---"]
    for entry in entries:
        speaker = "James" if entry["role"] == "james" else "Hayeong"
        lines.append(f"{speaker}: {entry['content']}")
    lines.append("--- End recent conversation ---")
    return "\n".join(lines)


def trim_to_recent(n: int = 6) -> None:
    """
    Keep only the n most recent entries.
    Called by session_compressor after archiving older entries.
    """
    global _BUFFER
    entries = list(_BUFFER)
    if len(entries) > n:
        _BUFFER.clear()
        for entry in entries[-n:]:
            _BUFFER.append(entry)


def clear() -> None:
    """Clear the buffer. Called on clean shutdown if needed."""
    _BUFFER.clear()
