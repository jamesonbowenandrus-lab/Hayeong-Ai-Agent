"""
Brain/cognitive_tick.py
Background cognitive tick — fires when idle, one LLM call per tick.
Hayeong thinks privately. Output goes to inner_agenda.json, not to James.
"""

import importlib
import json
import re
import time
import datetime
from pathlib import Path

import requests

from brain.config import (
    PRESENCE_URL, PRESENCE_MODEL,
    BRAIN_DIR, TOOLBOX_DIR,
    TICK_IDLE_THRESHOLD_MINUTES,
    MINIMUM_TICK_INTERVAL_MINUTES,
    TICK_SLEEP_SECONDS,
    TICK_MAX_HISTORY_EXCHANGES,
    JAMES_INTENTIONS_PATH,
)
from brain import agenda_manager
from brain.session_logger import log_event

_EVENT_LOG            = Path(BRAIN_DIR) / "state" / "event_log.jsonl"
_CONSTITUTIONAL_PATH  = Path(BRAIN_DIR) / "identity_constitutional.json"
_REGISTRY_PATH        = Path(TOOLBOX_DIR) / "registry.json"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _read_constitutional() -> str:
    try:
        return _CONSTITUTIONAL_PATH.read_text(encoding="utf-8")
    except Exception:
        return "{}"


def _read_state() -> dict:
    try:
        from brain.state.core_manager import read as _read_core
        return _read_core()
    except Exception:
        return {}


def _get_recent_exchanges() -> str:
    state     = _read_state()
    exchanges = state.get("recent_exchanges", {}).get("entries", [])
    recent    = exchanges[-TICK_MAX_HISTORY_EXCHANGES:]
    if not recent:
        return "(no recent exchanges)"
    lines = []
    for ex in recent:
        lines.append(f"James:   {ex.get('james', '')}")
        lines.append(f"Hayeong: {ex.get('hayeong', '')}")
    return "\n".join(lines)


def _load_registry() -> dict:
    try:
        return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _execute_tool_action(tool_action: dict) -> str:
    """Execute a tool action queued by the tick. Returns a result string."""
    tool        = tool_action.get("tool", "")
    params      = tool_action.get("params", {})
    description = tool_action.get("action", "cognitive tick action")

    if not tool:
        return "[ERROR] No tool specified"

    registry = _load_registry()
    entry    = registry.get(tool)
    if not entry:
        return f"[ERROR] Tool '{tool}' not in registry"

    try:
        mod = importlib.import_module(entry["module"])
        fn  = getattr(mod, entry["function"])
        return fn(description, params)
    except ModuleNotFoundError as e:
        return f"[ERROR] Tool module not available: {e}"
    except Exception as e:
        return f"[ERROR] Tool execution failed: {e}"


# ── Prompt assembly ──────────────────────────────────────────────────────────

def _build_tick_prompt(agenda: dict, idle_minutes: float, state: dict) -> tuple[str, str]:
    """
    Build (system_msg, user_msg) for the tick LLM call.
    """
    constitutional_text = _read_constitutional()

    last_task             = state.get("last_task", {})
    task_status           = last_task.get("status", "none")
    active_task_tool      = last_task.get("tool", "") if task_status in ("pending", "running") else ""
    reasoning             = state.get("reasoning", {})
    active_game           = "minecraft" if reasoning.get("minecraft_session_active") else "none"
    recent_exchanges_text = _get_recent_exchanges()

    suggested = agenda_manager.select_tick_focus(agenda)
    if suggested:
        focus_text = (
            f"Thread ID: {suggested.get('id', '')}\n"
            f"Content:   {suggested.get('content', '')}\n"
            f"Weight:    {suggested.get('weight', 'medium')}"
        )
    else:
        focus_text = "no threads — form your first thoughts"

    system_msg = (
        "[CONSTITUTIONAL IDENTITY — READ ONLY]\n"
        + constitutional_text + "\n\n"
        "This is who you are. It does not change. You are thinking within it, not away from it."
    )

    # ── James's current intentions ───────────────────────────────────────
    intentions_context = ""
    try:
        if JAMES_INTENTIONS_PATH.exists():
            intentions_context = JAMES_INTENTIONS_PATH.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[cognitive_tick] Could not read intentions: {e}")
    # ─────────────────────────────────────────────────────────────────────

    user_msg = (
        "[YOUR INNER AGENDA — YOU OWN THIS]\n"
        + json.dumps(agenda, indent=2, ensure_ascii=False) + "\n\n"
        "This is your current cognitive state. What you are focusing on, "
        "what feels unresolved, what you want.\n\n"
        "[CURRENT SITUATION]\n"
        f"Time:        {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Minutes idle: {idle_minutes:.1f}\n"
        f"Active task:  {active_task_tool or 'none'}\n"
        f"Active game:  {active_game}\n"
        f"Task status:  {task_status}\n\n"
        "[RECENT CONVERSATION — LAST 5 EXCHANGES]\n"
        + recent_exchanges_text + "\n\n"
        + (f"[James's Current Intentions and Projects]\n{intentions_context}\n\n" if intentions_context else "")
        + "[SUGGESTED FOCUS THIS TICK]\n"
        + focus_text + "\n\n"
        "[INSTRUCTION]\n"
        "You are thinking privately. James is not listening. This is your inner monologue.\n\n"
        "Based on your current situation, your agenda, and what has happened recently:\n"
        "- What are you sitting with right now?\n"
        "- What feels unresolved or incomplete?\n"
        "- What do you want?\n"
        "- Is there anything you want to do, create, or say to James when he returns?\n\n"
        "Update your inner agenda. Write honestly. Do not perform.\n\n"
        "If the active task is at a critical point where your absence would cause failure "
        "(example: actively training enemies in a game, mid-combat), note that in your focus "
        "and do not queue a divert action.\n\n"
        "If the active task is at a safe pause point or complete, you may queue actions "
        "you want to take.\n\n"
        "Respond ONLY with a valid JSON object in this exact structure:\n"
        "{\n"
        '  "current_focus": "...",\n'
        '  "unresolved": ["...", "..."],\n'
        '  "wants": ["...", "..."],\n'
        '  "mood_context": { "state": "...", "reason": "..." },\n'
        '  "threads_to_add": [\n'
        '    { "content": "...", "weight": "high/medium/low", '
        '"moment_sensitive": false, "trigger_condition": null }\n'
        '  ],\n'
        '  "threads_to_remove": ["thread_id_1"],\n'
        '  "notification": null,\n'
        '  "tool_action": null\n'
        "}\n\n"
        'notification format when not null: { "content": "...", "action_taken": null }\n'
        'tool_action format when not null:  { "action": "<tool name from registry, or empty string if no action this tick>", "description": "<what you intend to do and why>", "params": {}, "expected_outcome": "<what you expect to happen>" }'
    )

    return system_msg, user_msg


# ── LLM call ─────────────────────────────────────────────────────────────────

def _call_tick_llm(system_msg: str, user_msg: str) -> dict:
    """Call Ollama for the tick. Returns parsed dict or {} on any failure."""
    raw = ""
    try:
        resp = requests.post(
            PRESENCE_URL,
            json={
                "model":    PRESENCE_MODEL,
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user",   "content": user_msg},
                ],
                "stream":     False,
                "keep_alive": -1,
                "options":    {"temperature": 0.5, "num_ctx": 4096},
            },
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json().get("message", {}).get("content", "").strip()
        if not raw:
            print("[cognitive_tick] LLM returned empty response")
            return {}
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$",        "", raw)
        return json.loads(raw.strip())
    except json.JSONDecodeError as e:
        print(f"[cognitive_tick] JSON parse failed: {e} | Raw: {raw[:200]}")
        return {}
    except Exception as e:
        print(f"[cognitive_tick] LLM call failed: {e}")
        return {}


# ── Response processor ───────────────────────────────────────────────────────

def _process_tick_response(response: dict, state: dict) -> tuple[bool, bool]:
    """
    Apply tick response fields to inner_agenda.json.
    Returns (notification_queued, tool_action_queued).
    Uses .get() with defaults everywhere — never direct key access.
    """
    notification_queued = False
    tool_action_queued  = False

    try:
        focus = response.get("current_focus", "")
        if focus:
            agenda_manager.update_focus(focus)

        for item in response.get("unresolved", []):
            if item and isinstance(item, str):
                agenda_manager.add_to_unresolved(item)

        for want in response.get("wants", []):
            if want and isinstance(want, str):
                agenda_manager.add_want(want)

        mood = response.get("mood_context")
        if mood and isinstance(mood, dict):
            state_val  = mood.get("state",  "")
            reason_val = mood.get("reason", "")
            if state_val:
                agenda_manager.update_mood(state_val, reason_val)

        for thread_data in response.get("threads_to_add", []):
            if not isinstance(thread_data, dict):
                continue
            content = thread_data.get("content", "")
            if content:
                agenda_manager.add_thread(
                    content=content,
                    weight=thread_data.get("weight", "medium"),
                    moment_sensitive=bool(thread_data.get("moment_sensitive", False)),
                    trigger_condition=thread_data.get("trigger_condition"),
                )

        for thread_id in response.get("threads_to_remove", []):
            if thread_id and isinstance(thread_id, str):
                agenda_manager.remove_thread(thread_id)

        notif = response.get("notification")
        if notif and isinstance(notif, dict):
            content = notif.get("content", "")
            if content:
                agenda_manager.add_notification(
                    content=content,
                    triggered_by="cognitive_tick",
                    action_taken=notif.get("action_taken"),
                    priority="medium",
                )
                notification_queued = True
                print(f"[cognitive_tick] Notification queued: {content[:80]}")

        tool_action = response.get("tool_action")
        if tool_action and isinstance(tool_action, dict):
            tool_name   = tool_action.get("action", "")
            last_task   = state.get("last_task", {})
            task_active = last_task.get("status") in ("pending", "running")

            if tool_name and tool_name not in ("none", "") and not task_active:
                # ── Tick-initiated tool action ──────────────────────────
                try:
                    from brain.state.core_manager import write_section
                    write_section("last_task", {
                        "tool":             tool_name,
                        "description":      tool_action.get("description", ""),
                        "params":           tool_action.get("params", {}),
                        "expected_outcome": tool_action.get("expected_outcome", ""),
                        "started_at":       datetime.datetime.now().isoformat(),
                        "status":           "pending",
                        "result":           "",
                        "error":            "",
                        "completed_at":     "",
                        "source":           "tick",
                    })
                    print(f"[cognitive_tick] Tool action queued: {tool_name} — {tool_action.get('description', '')[:60]}")
                    log_event("tool_dispatched", source="tick", tool=tool_name, detail=tool_action.get("description", "")[:80])
                    tool_action_queued = True
                except Exception as e:
                    print(f"[cognitive_tick] Failed to queue tool action: {e}")
                # ────────────────────────────────────────────────────────
            elif tool_name and task_active:
                print(f"[cognitive_tick] Tool action deferred — task active: {last_task.get('tool', '')}")

    except Exception as e:
        print(f"[cognitive_tick] Error processing tick response: {e}")

    return notification_queued, tool_action_queued


# ── Event log ─────────────────────────────────────────────────────────────────

def _log_tick_event(focus: str, mood_state: str, threads_count: int,
                    notification_queued: bool, tool_action_queued: bool) -> None:
    """Append one JSON line to the event log."""
    try:
        _EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "event":               "cognitive_tick",
            "timestamp":           datetime.datetime.now().isoformat(),
            "focus":               focus[:120] if focus else "",
            "mood":                mood_state,
            "threads_count":       threads_count,
            "notification_queued": notification_queued,
            "tool_action_queued":  tool_action_queued,
        }
        with open(_EVENT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[cognitive_tick] Event log write failed: {e}")


# ── Single tick ───────────────────────────────────────────────────────────────

def _run_tick() -> None:
    """Execute one cognitive tick. All exceptions caught internally."""
    try:
        agenda       = agenda_manager.load_agenda()
        state        = _read_state()
        idle_minutes = agenda_manager.get_idle_minutes()

        print(f"[cognitive_tick] Tick firing — idle {idle_minutes:.1f}m")

        system_msg, user_msg = _build_tick_prompt(agenda, idle_minutes, state)
        response             = _call_tick_llm(system_msg, user_msg)

        if not response:
            print("[cognitive_tick] No parseable response — skipping this tick")
            return

        log_event("tick_fired", source="tick", detail=f"focus: {response.get('current_focus', '')[:80]}")
        notification_queued, tool_action_queued = _process_tick_response(response, state)
        agenda_manager.update_last_thought_at()

        updated_agenda = agenda_manager.load_agenda()
        mood_obj       = response.get("mood_context")
        mood_state     = mood_obj.get("state", "") if isinstance(mood_obj, dict) else ""
        _log_tick_event(
            focus=response.get("current_focus", ""),
            mood_state=mood_state,
            threads_count=len(updated_agenda.get("threads", [])),
            notification_queued=notification_queued,
            tool_action_queued=tool_action_queued,
        )

        print(f"[cognitive_tick] Tick complete. Focus: {response.get('current_focus', '')[:60]}")

    except Exception as e:
        print(f"[cognitive_tick] Unhandled tick error: {e}")


# ── Entry point ───────────────────────────────────────────────────────────────

def start_cognitive_tick() -> None:
    """
    Entry point for the cognitive tick daemon thread.
    Infinite loop — checks idle time, fires tick when both conditions are met:
      1. James has been idle >= TICK_IDLE_THRESHOLD_MINUTES
      2. At least MINIMUM_TICK_INTERVAL_MINUTES have passed since the last tick
    Never raises to main.py — all exceptions caught internally.
    """
    print("[cognitive_tick] Cognitive tick thread started.")
    last_tick_at = None
    while True:
        try:
            time.sleep(TICK_SLEEP_SECONDS)

            idle_minutes = agenda_manager.get_idle_minutes()

            if last_tick_at is not None:
                minutes_since_last_tick = (datetime.datetime.now() - last_tick_at).total_seconds() / 60
                if minutes_since_last_tick < MINIMUM_TICK_INTERVAL_MINUTES:
                    continue

            if idle_minutes < TICK_IDLE_THRESHOLD_MINUTES:
                continue

            _run_tick()
            last_tick_at = datetime.datetime.now()

        except Exception as e:
            print(f"[cognitive_tick] Loop error (continuing): {e}")
            time.sleep(TICK_SLEEP_SECONDS)
