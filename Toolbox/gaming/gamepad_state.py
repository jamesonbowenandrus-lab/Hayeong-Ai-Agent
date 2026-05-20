"""
Toolbox/gaming/gamepad_state.py

Tracks current virtual gamepad state.
Written to Brain/state/gaming_state.json for the brain to read.
"""

import json
from datetime import datetime
from pathlib import Path

STATE_PATH = Path(__file__).parent.parent.parent / "Brain" / "state" / "gaming_state.json"


def write_state(action: str, params: dict, result: str):
    """Write the last gamepad action to the gaming state file."""
    state = {
        "last_action":  action,
        "last_params":  params,
        "last_result":  result,
        "timestamp":    datetime.now().isoformat(),
        "gamepad_active": True,
    }
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def read_state() -> dict:
    """Read the current gaming state. Returns empty dict if not found."""
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def clear_state():
    """Clear gaming state on shutdown."""
    state = {
        "last_action":  "none",
        "last_params":  {},
        "last_result":  "gamepad released",
        "timestamp":    datetime.now().isoformat(),
        "gamepad_active": False,
    }
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
