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
    write_section("what_she_knows", {
        "context_for_james": "",
        "last_conclusion":   "",
        "current_thinking":  "",
        "updated_at":        "",
    })
    write_section("what_shes_doing", {
        "task_type": "",
        "task_description": "",
        "task_params": {},
        "assigned_at": "",
        "status": "idle",
    })
    write_section("what_happened", {
        "last_result": "",
        "last_tool":   "",
        "last_error":  "",
        "result_at":   "",
        "tool_status": {"minecraft": "idle", "voice": "idle", "email": "idle", "blender": "idle"},
    })
    write_section("james_input", {"message": "", "received_at": ""})
    write_section("hayeong_output", {"message": "", "sent_at": ""})
