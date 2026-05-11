"""
core_manager.py — Read and write sections of state/core.json
Simple. No abstractions. Just file read/write with a lock.
"""

import json
import threading
from pathlib import Path
from datetime import datetime

CORE_FILE = Path(__file__).parent / "core.json"
_lock = threading.Lock()


def read() -> dict:
    with _lock:
        try:
            return json.loads(CORE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}


def write_section(section: str, data: dict):
    with _lock:
        try:
            state = json.loads(CORE_FILE.read_text(encoding="utf-8"))
            if section not in state:
                state[section] = {}
            state[section].update(data)
            CORE_FILE.write_text(
                json.dumps(state, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"[core_manager] Write failed: {e}")


def clear_on_startup():
    """Clear volatile sections for a clean session."""
    write_section("situation", {
        "what_james_said": "",
        "said_at":         "",
        "what_i_am_doing": "idle",
        "current_focus":   "",
    })
    write_section("last_task", {
        "tool":         "",
        "description":  "",
        "params":       {},
        "started_at":   "",
        "status":       "none",
        "result":       "",
        "error":        "",
        "completed_at": "",
    })
    write_section("presence_output", {
        "for_james":    "",
        "emotion":      "calm",
        "certainty":    "",
        "is_new":       False,
        "expressed_at": "",
    })
