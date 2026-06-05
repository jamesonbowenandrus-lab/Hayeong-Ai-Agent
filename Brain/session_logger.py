"""
Brain/session_logger.py

Append-only SQLite session log. Records all significant system events
across sessions. Used for observability, development analysis, and
eventually fine-tuning data enrichment.

Usage:
    from brain.session_logger import log_event, SESSION_ID

    log_event("tick_fired", source="tick", detail="3 threads evaluated")
    log_event("tool_dispatched", source="tick", tool="blender", detail="material experiment")
    log_event("task_completed", source="task_loop", tool="blender", outcome="success")
    log_event("james_interaction", source="presence", detail="message received and responded")
"""

import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

from brain.config import BRAIN_DIR

DB_PATH    = Path(BRAIN_DIR) / "session_log.db"
SESSION_ID = str(uuid.uuid4())[:8]

_lock = threading.Lock()


def _get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(DB_PATH))


def _ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            timestamp   TEXT NOT NULL,
            date        TEXT NOT NULL,
            event_type  TEXT NOT NULL,
            source      TEXT,
            tool        TEXT,
            detail      TEXT,
            outcome     TEXT
        )
    """)
    conn.commit()


def log_event(
    event_type: str,
    source: str = "",
    tool: str = "",
    detail: str = "",
    outcome: str = "",
) -> None:
    """
    Append one event to the session log. Never raises — log failures are
    printed but do not affect the caller.
    """
    try:
        now = datetime.now()
        with _lock:
            conn = _get_conn()
            _ensure_table(conn)
            conn.execute(
                """
                INSERT INTO session_events
                    (session_id, timestamp, date, event_type, source, tool, detail, outcome)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    SESSION_ID,
                    now.isoformat(),
                    now.strftime("%Y-%m-%d"),
                    event_type,
                    source,
                    tool,
                    detail[:500] if detail else "",
                    outcome[:200] if outcome else "",
                ),
            )
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"[session_logger] Log write failed: {e}")


def _ensure_cc_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cc_sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      TEXT NOT NULL,
            date            TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            prompt_summary  TEXT,
            exchange_count  INTEGER,
            tasks_attempted INTEGER,
            tasks_succeeded INTEGER,
            result_summary  TEXT,
            duration_seconds REAL
        )
    """)
    conn.commit()


def log_cc_session(
    prompt_summary: str = "",
    exchange_count: int = 0,
    tasks_attempted: int = 0,
    tasks_succeeded: int = 0,
    result_summary: str = "",
    duration_seconds: float = 0.0,
) -> None:
    """
    Called by Claude Code (via a short logging call at session end) to record
    the session summary in the database.
    Can also be called manually: python -c "from brain.session_logger import log_cc_session; log_cc_session(...)"
    """
    try:
        now = datetime.now()
        with _lock:
            conn = _get_conn()
            _ensure_cc_table(conn)
            conn.execute(
                """
                INSERT INTO cc_sessions
                    (session_id, date, timestamp, prompt_summary, exchange_count,
                     tasks_attempted, tasks_succeeded, result_summary, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    SESSION_ID,
                    now.strftime("%Y-%m-%d"),
                    now.isoformat(),
                    prompt_summary[:300] if prompt_summary else "",
                    exchange_count,
                    tasks_attempted,
                    tasks_succeeded,
                    result_summary[:500] if result_summary else "",
                    duration_seconds,
                ),
            )
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"[session_logger] CC session log failed: {e}")
