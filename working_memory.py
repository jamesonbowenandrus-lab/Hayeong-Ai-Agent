"""
working_memory.py

Maintains a small, persistent working memory that carries forward between
conversation turns. This is what Hayeong is actively "holding in mind" —
not her full memory, just what's currently relevant and alive.

Updated after every response. Read at the start of every response.
Stored in state/working_memory.json
"""

import json
import threading
from datetime import datetime
from pathlib import Path

WORKING_MEMORY_FILE = Path(__file__).parent / "state" / "working_memory.json"
_lock = threading.Lock()


def _read() -> dict:
    if not WORKING_MEMORY_FILE.exists():
        return _empty()
    try:
        with open(WORKING_MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _empty()


def _write(data: dict):
    WORKING_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(WORKING_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def _empty() -> dict:
    return {
        "current_topic":        "",
        "emotional_tone":       "neutral",
        "open_threads":         [],
        "last_james_intent":    "",
        "last_hayeong_thought": "",
        "active_domains":       [],
        "updated_at":           datetime.now().isoformat(),
    }


def get() -> dict:
    """Get current working memory."""
    return _read()


def update(
    topic: str = None,
    tone: str = None,
    open_thread: str = None,
    close_thread: str = None,
    james_intent: str = None,
    hayeong_thought: str = None,
    domains: list = None,
):
    """
    Update working memory after a conversation turn.
    Only pass fields that changed — others are preserved.
    """
    data = _read()

    if topic is not None:
        data["current_topic"] = topic
    if tone is not None:
        data["emotional_tone"] = tone
    if open_thread is not None:
        threads = data.get("open_threads", [])
        if open_thread not in threads:
            threads.append(open_thread)
        data["open_threads"] = threads[-5:]
    if close_thread is not None:
        data["open_threads"] = [
            t for t in data.get("open_threads", [])
            if close_thread.lower() not in t.lower()
        ]
    if james_intent is not None:
        data["last_james_intent"] = james_intent
    if hayeong_thought is not None:
        data["last_hayeong_thought"] = hayeong_thought
    if domains is not None:
        data["active_domains"] = domains

    data["updated_at"] = datetime.now().isoformat()
    _write(data)


def clear():
    """Clear working memory — called on clean startup."""
    _write(_empty())


def to_prompt_block() -> str:
    """
    Format working memory as a compact prompt block.
    Called by system_prompt_builder.py.
    """
    data = _read()

    lines = ["[WORKING MEMORY — what I'm currently holding in mind]"]

    if data.get("current_topic"):
        lines.append(f"Current topic: {data['current_topic']}")

    if data.get("emotional_tone") and data["emotional_tone"] != "neutral":
        lines.append(f"Conversation tone: {data['emotional_tone']}")

    if data.get("open_threads"):
        threads = data["open_threads"]
        lines.append(f"Things I said I'd follow up on: {'; '.join(threads)}")

    if data.get("last_hayeong_thought"):
        lines.append(f"What I was just thinking: {data['last_hayeong_thought']}")

    lines.append("[END WORKING MEMORY]")

    # Only return the block if it has actual content beyond the header/footer
    if len(lines) <= 2:
        return ""
    return "\n".join(lines)
