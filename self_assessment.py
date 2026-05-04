"""
self_assessment.py
Runs as a background thread. Every 30 seconds, reads all system state
and writes a clean, accurate self-model to shared_state["self_assessment"].

This is what Hayeong reads when she needs to know how she is.
The communication LLM is injected with this block at the start of every response.
"""

import threading
import time
import urllib.request
import json
from datetime import datetime
from pathlib import Path

_stop_event = threading.Event()
_thread: threading.Thread | None = None


def _check_url(url: str, timeout: int = 3) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _check_url_json(url: str, timeout: int = 3) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _build_assessment() -> dict:
    """Read everything and build an accurate picture of current state."""
    now = datetime.now()

    # Voice server
    voice_health = _check_url_json("http://localhost:8765/health")
    if voice_health:
        voice_server  = voice_health.get("status", "unknown")
        voice_client  = "connected" if voice_health.get("active_connections", 0) > 0 else "disconnected"
        tts_available = voice_health.get("tts_active", "none") != "none"
        stt_available = voice_health.get("whisper", "not loaded") == "loaded"
    else:
        voice_server  = "offline"
        voice_client  = "unknown"
        tts_available = False
        stt_available = False

    # Communication LLM
    comm_health = _check_url_json("http://localhost:11434/api/ps")
    if comm_health:
        models      = comm_health.get("models", [])
        comm_loaded = len(models) > 0
        comm_model  = models[0].get("name", "unknown") if models else "none"
    else:
        comm_loaded = False
        comm_model  = "offline"

    # Reasoning LLM
    reasoning_health = _check_url_json("http://localhost:11435/api/ps")
    if reasoning_health:
        models           = reasoning_health.get("models", [])
        reasoning_loaded = len(models) > 0
    else:
        reasoning_loaded = False

    # Shared state
    try:
        from state_manager import read_state
        state          = read_state()
        active_task    = state.get("reasoning", {}).get("active_task", "")
        task_status    = state.get("reasoning", {}).get("active_task_status", "")
        current_goal   = state.get("reasoning", {}).get("current_goal", "")
        active_scripts = state.get("system", {}).get("active_scripts", [])
    except Exception:
        active_task    = ""
        task_status    = ""
        current_goal   = ""
        active_scripts = []

    # Minecraft bot
    minecraft_running = False
    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            cmdline = proc.info.get('cmdline') or []
            if any('hayeong_bot' in str(c) or 'mineflayer' in str(c).lower()
                   for c in cmdline):
                minecraft_running = True
                break
    except Exception:
        pass

    # Commitments
    try:
        from commitment_manager import get_all_active
        active_commitments = get_all_active()
        pending_count      = len([c for c in active_commitments if c["status"] == "pending"])
        overdue_count      = len([c for c in active_commitments if c["status"] == "overdue"])
    except Exception:
        pending_count = 0
        overdue_count = 0

    # Uptime
    try:
        uptime_file = Path(__file__).parent / "state" / "session_start.txt"
        if uptime_file.exists():
            start       = datetime.fromisoformat(uptime_file.read_text().strip())
            uptime_mins = round((now - start).total_seconds() / 60, 1)
        else:
            uptime_mins = None
    except Exception:
        uptime_mins = None

    return {
        "assessed_at":    now.isoformat(),
        "uptime_minutes": uptime_mins,
        "voice": {
            "server":         voice_server,
            "client":         voice_client,
            "can_hear_james": voice_client == "connected" and stt_available,
            "can_speak":      voice_client == "connected" and tts_available,
        },
        "models": {
            "communication":       "loaded" if comm_loaded else "offline",
            "communication_model": comm_model,
            "reasoning":           "loaded" if reasoning_loaded else "offline",
        },
        "task": {
            "active":          active_task,
            "status":          task_status,
            "goal":            current_goal,
            "running_scripts": active_scripts,
        },
        "commitments": {
            "pending": pending_count,
            "overdue": overdue_count,
        },
        "minecraft": {
            "bot_running": minecraft_running,
        },
    }


def _assessment_loop():
    """Background loop — runs every 30 seconds."""
    import time
    while not _stop_event.is_set():
        try:
            assessment = _build_assessment()
            from state_manager import write_system
            write_system({"self_assessment": assessment})
        except Exception as e:
            print(f"[self_assessment] Error: {e}")
        # Wait 30s in 1s increments so the stop flag is checked each second.
        # Avoids _stop_event.wait(timeout=30) returning early if the event
        # was set by a previous session and never cleared.
        for _ in range(30):
            if _stop_event.is_set():
                return
            time.sleep(1)


def start_self_assessment():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(
        target=_assessment_loop, daemon=True, name="self_assessment"
    )
    _thread.start()
    print("[self_assessment] Background assessment started.")


def stop_self_assessment():
    _stop_event.set()
