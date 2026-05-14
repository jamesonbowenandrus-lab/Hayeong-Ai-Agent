"""
toolbox/comfyui/plugin.py
Heartbeat plugin — injects ComfyUI status into Hayeong's presence context.
Checks ComfyUI health at most every 30 seconds.
"""

import time
import requests

from brain.config import COMFYUI_URL, COMFYUI_OUTPUT_DIR
from pathlib import Path

_last_check:   float = 0.0
_status:       str   = "unknown"   # "running" | "not running" | "unknown"
_last_output:  str | None = None

_CHECK_INTERVAL = 30


def tick():
    global _last_check, _status, _last_output

    now = time.time()
    if now - _last_check < _CHECK_INTERVAL:
        return
    _last_check = now

    try:
        r = requests.get(f"{COMFYUI_URL}/system_stats", timeout=2)
        _status = "running" if r.status_code == 200 else "not running"
    except Exception:
        _status = "not running"

    if _status == "running":
        _last_output = _find_latest_output()


def get_context_injection(state=None) -> list:
    if _status == "running":
        line = "- ComfyUI: running"
        if _last_output:
            line += f" | Last output: {_last_output}"
        return [line]
    elif _status == "not running":
        return ["- ComfyUI: not running (start ComfyUI to enable image generation)"]
    else:
        return ["- ComfyUI: status unknown"]


def _find_latest_output() -> str | None:
    output_dir = Path(COMFYUI_OUTPUT_DIR)
    try:
        pngs = sorted(output_dir.glob("*.png"), key=lambda p: p.stat().st_mtime)
        return str(pngs[-1]) if pngs else None
    except Exception:
        return None
