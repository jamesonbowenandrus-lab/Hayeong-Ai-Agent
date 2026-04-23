"""
reasoning_loop.py
The Reasoning LLM heartbeat — runs on its own thread alongside the main brain.

Responsibilities:
  - Process priority flags from the communication LLM
  - Advance the active task (e.g. Minecraft planning, long-running research)
  - Consume pending results from capability scripts
  - Write conclusions and context back to shared state

Architecture rule:
  This loop NEVER speaks directly to James.
  All James-facing output goes through the communication LLM (7b, port 11434).
  This loop writes to shared_state["reasoning"]["context_for_communication"]
  and the communication LLM picks it up on the next response turn.

Usage:
  from reasoning_loop import start_reasoning_loop, stop_reasoning_loop
  start_reasoning_loop()   # call once during brain startup
"""

import json
import re
import threading
import time
from datetime import datetime

import requests

from state_manager import (
    read_state,
    write_reasoning,
    pop_priority_flags,
    pop_pending_results,
)

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

REASONING_URL   = "http://localhost:11435/api/chat"
REASONING_MODEL = "qwen2.5:14b-instruct-q4_K_M"

HEARTBEAT_SECONDS = 3    # how often the reasoning loop ticks when idle
TIMEOUT_SECONDS   = 30   # per Ollama call

_stop_event = threading.Event()
_thread: threading.Thread | None = None


# ─────────────────────────────────────────────
# OLLAMA CALL
# ─────────────────────────────────────────────

def _call_reasoning(system: str, user: str) -> str:
    """Single call to the reasoning LLM. Returns response text or empty string on failure."""
    try:
        resp = requests.post(
            REASONING_URL,
            json={
                "model":   REASONING_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "stream":  False,
                "options": {"temperature": 0.3},
            },
            timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    except Exception as e:
        print(f"[reasoning_loop] LLM call failed: {e}")
        return ""


def _call_reasoning_json(system: str, user: str) -> dict:
    """Call reasoning LLM and parse JSON response. Returns {} on failure."""
    try:
        resp = requests.post(
            REASONING_URL,
            json={
                "model":   REASONING_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "stream":  False,
                "format":  "json",
                "options": {"temperature": 0.0},
            },
            timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$",       "", raw)
        return json.loads(raw.strip())
    except Exception as e:
        print(f"[reasoning_loop] JSON call failed: {e}")
        return {}


# ─────────────────────────────────────────────
# PROCESSING FUNCTIONS
# ─────────────────────────────────────────────

def _process_priority_flags(flags: list):
    """Reason about priority flags from the communication LLM."""
    if not flags:
        return

    flag_text = "\n".join(
        f"[{f['level'].upper()}] {f['message']}"
        for f in flags
    )

    print(f"[reasoning_loop] Processing {len(flags)} priority flag(s)...")

    result = _call_reasoning_json(
        system=(
            "You are Hayeong's reasoning layer. You received a priority message "
            "from the communication layer. Decide what to do.\n\n"
            "Return JSON: "
            '{"conclusion": "...", "context_for_communication": "...", '
            '"new_goal": "", "new_task": ""}\n\n'
            "context_for_communication: what the communication LLM should tell James "
            "(leave empty if no update needed for James right now).\n"
            "new_goal / new_task: if this triggers a new goal or task, name it; otherwise empty."
        ),
        user=f"Priority flags:\n{flag_text}",
    )

    if result:
        updates = {"last_conclusion": result.get("conclusion", "")}
        if result.get("context_for_communication"):
            updates["context_for_communication"] = result["context_for_communication"]
        if result.get("new_goal"):
            updates["current_goal"] = result["new_goal"]
        if result.get("new_task"):
            updates["active_task"] = result["new_task"]
            updates["active_task_status"] = "started"
        write_reasoning(updates)


def _consume_pending_results(results: list):
    """Process results from capability scripts."""
    if not results:
        return

    for entry in results:
        script  = entry.get("script", "unknown")
        payload = entry.get("result", {})
        print(f"[reasoning_loop] Consuming result from {script}...")

        conclusion = _call_reasoning(
            system=(
                "You are Hayeong's reasoning layer. A capability script completed. "
                "Summarize what happened and decide if James needs to know anything. "
                "Be concise. If James should be told something, start your response with "
                "'TELL JAMES: ' followed by what to say. Otherwise just summarize internally."
            ),
            user=f"Script: {script}\nResult: {json.dumps(payload, indent=2)[:2000]}",
        )

        updates: dict = {"last_conclusion": conclusion[:500]}

        if conclusion.startswith("TELL JAMES:"):
            message = conclusion[len("TELL JAMES:"):].strip()
            updates["context_for_communication"] = message

        write_reasoning(updates)


def _advance_active_task():
    """Take the next step on the active task."""
    state       = read_state()
    task        = state["reasoning"].get("active_task", "")
    task_status = state["reasoning"].get("active_task_status", "")
    mc_state    = state["reasoning"].get("minecraft_state", {})

    if not task:
        return

    print(f"[reasoning_loop] Advancing task: {task} ({task_status})")

    # ── Minecraft task ──
    if mc_state and "player" in mc_state:
        result = _call_reasoning_json(
            system=(
                "You are Hayeong's reasoning layer controlling a Minecraft bot. "
                "Given the current game state, decide the next action.\n\n"
                "Return JSON: "
                '{"action": "move|mine|place|craft|idle", '
                '"target": "block/entity name or direction", '
                '"context_for_communication": "", '
                '"task_complete": false}'
            ),
            user=(
                f"Current goal: {state['reasoning'].get('current_goal', task)}\n"
                f"Game state: {json.dumps(mc_state, indent=2)[:1500]}"
            ),
        )
        if result:
            updates: dict = {
                "last_conclusion": f"Minecraft action: {result.get('action')} {result.get('target')}",
            }
            if result.get("context_for_communication"):
                updates["context_for_communication"] = result["context_for_communication"]
            if result.get("task_complete"):
                updates["active_task"]        = ""
                updates["active_task_status"] = "complete"
            write_reasoning(updates)

    # ── Generic task ──
    else:
        result = _call_reasoning_json(
            system=(
                "You are Hayeong's reasoning layer. Advance the active task by one step.\n\n"
                "Return JSON: "
                '{"progress": "what was done or decided", '
                '"context_for_communication": "", '
                '"task_complete": false}'
            ),
            user=(
                f"Task: {task}\n"
                f"Status: {task_status}\n"
                f"Goal: {state['reasoning'].get('current_goal', '')}"
            ),
        )
        if result:
            updates = {
                "last_conclusion":    result.get("progress", "")[:400],
                "active_task_status": "in_progress",
            }
            if result.get("context_for_communication"):
                updates["context_for_communication"] = result["context_for_communication"]
            if result.get("task_complete"):
                updates["active_task"]        = ""
                updates["active_task_status"] = "complete"
            write_reasoning(updates)


def _background_cognition():
    """Low-priority thinking when nothing urgent is queued."""
    state = read_state()
    # Only run background cognition occasionally — every ~30s of idle
    # Tracked via a module-level counter rather than wall clock.
    _background_cognition._ticks = getattr(_background_cognition, "_ticks", 0) + 1
    if _background_cognition._ticks % max(1, round(30 / HEARTBEAT_SECONDS)) != 0:
        return

    goal = state["reasoning"].get("current_goal", "")
    queue = state["reasoning"].get("task_queue", [])

    if goal or queue:
        print("[reasoning_loop] Background: reviewing goal/queue...")
        result = _call_reasoning_json(
            system=(
                "You are Hayeong's reasoning layer doing a quiet background check. "
                "Review the current goal and task queue. Decide if anything needs attention.\n\n"
                "Return JSON: "
                '{"summary": "brief status", "context_for_communication": "", '
                '"next_task": ""}'
            ),
            user=f"Goal: {goal}\nQueue: {json.dumps(queue)[:500]}",
        )
        if result:
            updates: dict = {}
            if result.get("context_for_communication"):
                updates["context_for_communication"] = result["context_for_communication"]
            if result.get("next_task") and not state["reasoning"].get("active_task"):
                updates["active_task"]        = result["next_task"]
                updates["active_task_status"] = "queued"
            if updates:
                write_reasoning(updates)


# ─────────────────────────────────────────────
# MAIN HEARTBEAT LOOP
# ─────────────────────────────────────────────

def _heartbeat():
    print("[reasoning_loop] Heartbeat started.")
    while not _stop_event.is_set():
        try:
            # 1. Priority flags first
            flags = pop_priority_flags()
            if flags:
                _process_priority_flags(flags)

            # 2. Consume script results
            results = pop_pending_results()
            if results:
                _consume_pending_results(results)

            # 3. Advance active task
            state = read_state()
            if state["reasoning"].get("active_task"):
                _advance_active_task()

            # 4. Background cognition when idle
            else:
                _background_cognition()

        except Exception as e:
            print(f"[reasoning_loop] Heartbeat error: {e}")

        _stop_event.wait(HEARTBEAT_SECONDS)

    print("[reasoning_loop] Heartbeat stopped.")


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def start_reasoning_loop():
    """Start the reasoning heartbeat on a daemon thread. Call once at brain startup."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_heartbeat, name="reasoning_loop", daemon=True)
    _thread.start()


def stop_reasoning_loop():
    """Signal the heartbeat to stop. Returns when the thread exits."""
    global _thread
    _stop_event.set()
    if _thread:
        _thread.join(timeout=10)
        _thread = None
