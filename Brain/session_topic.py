"""
session_topic.py
Tracks the current conversational topic for the active session.

Hayeong updates this when she detects a significant topic shift in her response.
The presence loop injects it as a one-line context hint.

This gives the model a lightweight thread anchor without requiring it to
re-derive the current subject from full history every tick.
"""

_current_topic: str = "general conversation"
_topic_since: str   = ""


def set_topic(topic: str) -> None:
    from datetime import datetime
    global _current_topic, _topic_since
    _current_topic = topic
    _topic_since   = datetime.now().isoformat(timespec="seconds")


def get_topic() -> str:
    return _current_topic


def get_topic_line() -> str:
    """One-line string for context injection."""
    if _topic_since:
        return f"Current conversation topic: {_current_topic} (since {_topic_since})"
    return f"Current conversation topic: {_current_topic}"


def reset() -> None:
    global _current_topic, _topic_since
    _current_topic = "general conversation"
    _topic_since   = ""
