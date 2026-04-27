"""
watchdog.py
Lightweight process supervisor for Hayeong.

Responsibilities:
  1. Start the brain on launch
  2. Detect unexpected brain exits and restart with notification to James
  3. Act on recovery notes left by the brain before intentional shutdowns
  4. Log all activity to hayeong_outputs/logs/watchdog.log

Usage:
  python watchdog.py

Started automatically by start_hayeong.bat in its own window.
The watchdog (not the bat file) owns the brain process lifetime.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR      = Path(__file__).parent
BRAIN_SCRIPT  = str(BASE_DIR / "main.py")
RECOVERY_FILE = BASE_DIR / "hayeong_outputs" / "recovery" / "last_recovery_note.json"
STARTUP_MSG   = BASE_DIR / "hayeong_outputs" / "recovery" / "startup_message.txt"
WATCHDOG_LOG  = BASE_DIR / "hayeong_outputs" / "logs" / "watchdog.log"

CHECK_INTERVAL = 10   # seconds between brain liveness checks

brain_process = None


# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

def log(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [watchdog] {message}"
    print(line)
    WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ─────────────────────────────────────────────
# RECOVERY NOTE
# ─────────────────────────────────────────────

def read_recovery_note() -> dict | None:
    if not RECOVERY_FILE.exists():
        return None
    try:
        note = json.loads(RECOVERY_FILE.read_text(encoding="utf-8"))
        if not note.get("resolved"):
            return note
    except Exception:
        pass
    return None


def mark_recovery_resolved():
    if not RECOVERY_FILE.exists():
        return
    try:
        note = json.loads(RECOVERY_FILE.read_text(encoding="utf-8"))
        note["resolved"] = True
        RECOVERY_FILE.write_text(json.dumps(note, indent=2), encoding="utf-8")
    except Exception:
        pass


# ─────────────────────────────────────────────
# STARTUP MESSAGE
# ─────────────────────────────────────────────

def queue_startup_message(message: str):
    """Leave a message for Hayeong to deliver to James on next brain startup."""
    STARTUP_MSG.parent.mkdir(parents=True, exist_ok=True)
    STARTUP_MSG.write_text(message, encoding="utf-8")
    log(f"Startup message queued: {message[:80]}...")


# ─────────────────────────────────────────────
# BRAIN PROCESS MANAGEMENT
# ─────────────────────────────────────────────

def start_brain():
    global brain_process
    log("Starting Hayeong brain...")
    brain_process = subprocess.Popen(
        [sys.executable, BRAIN_SCRIPT, "--brain"],
        cwd=str(BASE_DIR),
    )
    log(f"Brain started (PID {brain_process.pid}).")


def brain_is_running() -> bool:
    global brain_process
    if brain_process is None:
        return False
    return brain_process.poll() is None


def handle_recovery_note(note: dict):
    log(f"Acting on recovery note: {note['reason']}")

    script = note.get("script_to_run")
    if script and os.path.exists(script):
        log(f"Running recovery script: {script}")
        try:
            subprocess.run([sys.executable, script], cwd=str(BASE_DIR), timeout=60)
        except Exception as e:
            log(f"Recovery script failed: {e}")

    if note.get("notify_james") and note.get("message_to_james"):
        queue_startup_message(note["message_to_james"])

    if note.get("suggested_action") == "restart_brain":
        log("Recovery note requests brain restart.")
        start_brain()

    mark_recovery_resolved()


# ─────────────────────────────────────────────
# MAIN WATCHDOG LOOP
# ─────────────────────────────────────────────

def run():
    log("Watchdog starting.")

    note = read_recovery_note()
    if note:
        handle_recovery_note(note)
    else:
        start_brain()

    while True:
        time.sleep(CHECK_INTERVAL)

        if not brain_is_running():
            log("Brain process has stopped.")
            note = read_recovery_note()
            if note:
                handle_recovery_note(note)
            else:
                log("Unexpected brain exit — no recovery note found. Restarting.")
                queue_startup_message(
                    "I crashed unexpectedly and the watchdog restarted me. "
                    "I don't have full context on what happened — check "
                    "hayeong_outputs/logs/brain_errors.log for details."
                )
                start_brain()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log("Watchdog stopped by user.")
        if brain_is_running():
            log("Brain process still running — leaving it alive.")
