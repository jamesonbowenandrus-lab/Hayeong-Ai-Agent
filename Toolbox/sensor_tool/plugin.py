"""
Toolbox/sensor_tool/plugin.py

Injects hardware state into shared state on every heartbeat tick.
Hayeong's brain reads this to make decisions about compute-heavy tasks.
"""

from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent


def tick(state: dict) -> dict:
    try:
        from toolbox.sensor_tool.sensor_tool import _gpu_status, _cpu_ram_status
        gpu_summary = _gpu_status("all")
        cpu_summary = _cpu_ram_status()
        return {
            "hardware_state": {
                "gpu_summary": gpu_summary,
                "cpu_ram":     cpu_summary,
                "note":        "Updated each heartbeat tick",
            }
        }
    except Exception:
        return {}


def get_context_injection(state: dict) -> str:
    hw = state.get("hardware_state", {})
    if not hw:
        return ""
    return f"HARDWARE: {hw.get('gpu_summary', '')} | {hw.get('cpu_ram', '')}"