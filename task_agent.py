"""
task_agent.py

The task execution agent — Hayeong's hands.
Reads task assignments from shared state written by the 14b reasoning model.
Executes them: Minecraft bot control, script running, capability dispatch.
Reports results back to shared state.

Runs as a background thread alongside the main brain loop.
Never talks to James directly — only executes and reports.
"""

import threading
import time
import json
import requests
from datetime import datetime

TASK_URL      = "http://localhost:11436/api/chat"
TASK_MODEL    = "phi3:mini"
TICK_INTERVAL = 2.0  # check for new tasks every 2 seconds

_stop_event = threading.Event()
_thread: threading.Thread | None = None


def _call_task_llm(system: str, user: str, timeout: int = 30) -> str:
    """Call the task agent LLM. Returns response text or empty string."""
    try:
        resp = requests.post(TASK_URL, json={
            "model":      TASK_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "stream":     False,
            "keep_alive": -1,
            "options":    {"num_ctx": 8192, "temperature": 0.1},
        }, timeout=timeout)
        return resp.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"[task_agent] LLM call failed: {e}")
        return ""


def _read_pending_task() -> dict | None:
    """
    Read the pending task assignment from shared state.
    Returns None if no task is pending.
    """
    try:
        from state_manager import read_state
        state = read_state()
        assignment = state.get("task_agent", {}).get("assignment", {})
        if assignment.get("status") == "pending":
            return assignment
    except Exception:
        pass
    return None


def _write_task_result(result: str, status: str = "complete"):
    """Write task execution result back to shared state."""
    try:
        from state_manager import write_state_section, write_reasoning
        write_state_section("task_agent", {
            "assignment": {"status": status},
            "last_result": result,
            "result_at": datetime.now().isoformat(),
        })
        write_reasoning({"context_for_communication": f"Task result: {result}"})
        print(f"[task_agent] Result written: {result[:80]}")
    except Exception as e:
        print(f"[task_agent] Could not write result: {e}")


def _execute_task(task: dict) -> str:
    """
    Execute a task assignment. Dispatches to the appropriate handler
    based on task type.
    """
    task_type   = task.get("type", "")
    task_desc   = task.get("description", "")
    task_params = task.get("params", {})

    print(f"[task_agent] Executing: {task_type} — {task_desc[:60]}")

    try:
        from state_manager import write_state_section
        write_state_section("task_agent", {
            "assignment": {**task, "status": "in_progress"},
        })
    except Exception:
        pass

    if task_type == "minecraft":
        return _execute_minecraft_task(task_desc, task_params)

    if task_type == "script":
        return _execute_script_task(task_desc, task_params)

    # Generic — use task LLM
    response = _call_task_llm(
        system=(
            "You are Hayeong's task execution agent. Execute the assigned task "
            "precisely. Report what you did and the result. Be factual and brief."
        ),
        user=f"Execute: {task_desc}\nParams: {json.dumps(task_params)}",
    )
    return response or "Task completed (no output)."


def _execute_minecraft_task(description: str, params: dict) -> str:
    """Execute a Minecraft-related task via the bot bridge."""
    try:
        from capabilities.minecraft_cap import execute_minecraft_action
        return execute_minecraft_action(description, params)
    except ImportError:
        return "Minecraft capability not loaded — bridge not running."
    except Exception as e:
        return f"Minecraft task failed: {e}"


def _execute_script_task(description: str, params: dict) -> str:
    """Execute a script-based task via app_manager."""
    try:
        script = params.get("script", "")
        if not script:
            return "No script specified in task params."
        from app_manager import get_app_manager
        ok, msg = get_app_manager().start(script)
        return f"Script '{script}': {msg}"
    except Exception as e:
        return f"Script task failed: {e}"


def _task_loop():
    """Main task agent loop — checks for assignments every TICK_INTERVAL seconds."""
    print("[task_agent] Task loop started.")
    while not _stop_event.is_set():
        try:
            task = _read_pending_task()
            if task:
                result = _execute_task(task)
                _write_task_result(result, status="complete")
        except Exception as e:
            print(f"[task_agent] Loop error: {e}")
        _stop_event.wait(timeout=TICK_INTERVAL)
    print("[task_agent] Task loop stopped.")


def start_task_agent():
    """Start the task agent background thread."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_task_loop, daemon=True, name="task_agent")
    _thread.start()
    print("[task_agent] Started.")


def stop_task_agent():
    """Stop the task agent."""
    _stop_event.set()


def assign_task(task_type: str, description: str, params: dict = None):
    """
    Called by the 14b reasoning loop to assign a task to the task agent.
    Non-blocking — the task agent picks it up on its next tick.
    """
    try:
        from state_manager import write_state_section
        write_state_section("task_agent", {
            "assignment": {
                "type":        task_type,
                "description": description,
                "params":      params or {},
                "status":      "pending",
                "assigned_at": datetime.now().isoformat(),
            }
        })
        print(f"[task_agent] Task assigned: {task_type} — {description[:60]}")
    except Exception as e:
        print(f"[task_agent] Assignment failed: {e}")
