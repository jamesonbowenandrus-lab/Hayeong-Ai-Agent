"""
reasoning_loop.py
The Reasoning LLM heartbeat — runs on its own thread alongside the main brain.

Responsibilities:
  - Process priority flags from the presence loop
  - Advance the active task (e.g. Minecraft planning, long-running research)
  - Consume pending results from capability scripts
  - Write conclusions and context back to shared state

Architecture rule:
  This loop NEVER speaks directly to James.
  It writes to shared_state["reasoning"]["context_for_communication"]
  and the presence loop (main.py) picks it up on the next response turn.
  Both this loop and main.py call the same single model: Qwen 32b on port 11435.

Usage:
  from reasoning_loop import start_reasoning_loop, stop_reasoning_loop
  start_reasoning_loop()   # call once during brain startup
"""

import json
import os
import re
import threading
import time
from datetime import datetime, timezone

import requests

from brain.state_manager import (
    read_state,
    write_reasoning,
    pop_priority_flags,
    pop_pending_results,
)
from brain.state.core_manager import write_section

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

REASONING_URL   = "http://localhost:11435/api/chat"
REASONING_MODEL = "qwen2.5:32b-instruct-q4_K_M"

HEARTBEAT_FALLBACK = 5.0   # sleep duration after an exception — never used as default
TIMEOUT_SECONDS    = 120   # per Ollama call — deepseek-r1 can be slow under VRAM pressure

_stop_event           = threading.Event()
_wake_event           = threading.Event()   # set by wake_now() to fire next tick early
_tick_lock            = threading.Lock()
_thread: threading.Thread | None = None
_startup_done         = False
_wake_assessment_done = False
_last_unprompted_at   = 0.0               # guards unprompted initiation cooldown

# ─────────────────────────────────────────────
# LOOP BREAKER — consecutive failure detection
# ─────────────────────────────────────────────
MAX_CONSECUTIVE_FAILURES    = 3
_consecutive_failures: dict = {}   # { task_key: count }
_last_seen_completed_at     = ""   # de-duplicates repeated reads of the same result

def _get_task_key(tool: str, description: str) -> str:
    """Short normalized key. First 40 chars catches near-identical retries even if wording shifts."""
    return f"{tool}:{description.strip().lower()[:40]}"


def _check_task_stuck():
    """
    Read last_task from shared state. Track consecutive failures per task key.
    After MAX_CONSECUTIVE_FAILURES, write an escalation to context_for_communication
    so the presence loop delivers it to James, then reset the counter.
    Called from _proactive_checks() on every heartbeat tick.
    """
    global _last_seen_completed_at

    state     = read_state()
    last_task = state.get("last_task", {})

    status       = last_task.get("status", "")
    tool         = last_task.get("tool", "")
    description  = last_task.get("description", "")
    completed_at = last_task.get("completed_at", "")
    result       = last_task.get("result", "")
    error        = last_task.get("error", "")

    if not tool or not completed_at:
        return

    # Don't count the same completed task twice across multiple heartbeat ticks
    if completed_at == _last_seen_completed_at:
        return
    _last_seen_completed_at = completed_at

    task_key = _get_task_key(tool, description)

    is_failure = (
        status == "failed"
        or (status == "success" and (
            result.startswith("[ERROR]") or result.startswith("[PARTIAL]")
        ))
    )

    if is_failure:
        count = _consecutive_failures.get(task_key, 0) + 1
        _consecutive_failures[task_key] = count
        print(f"[reasoning_loop] Failure #{count} for: {task_key[:60]}")

        if count >= MAX_CONSECUTIVE_FAILURES:
            _consecutive_failures.pop(task_key, None)
            error_detail = (error or result)[:200]
            escalation = (
                f"James, I'm stuck. I've tried this {count} times and keep hitting the same wall. "
                f"What I was doing: {description[:100]}. "
                f"Error: {error_detail}. "
                f"I need your help to move forward."
            )
            write_reasoning({"context_for_communication": escalation})
            print(f"[reasoning_loop] ESCALATED to James after {count} failures: {task_key[:60]}")
    else:
        # Any success clears the failure streak for this task
        if task_key in _consecutive_failures:
            print(f"[reasoning_loop] Success — clearing failure streak: {task_key[:60]}")
            _consecutive_failures.pop(task_key, None)


# ─────────────────────────────────────────────
# BOT STATE FILE READER
# ─────────────────────────────────────────────

_MC_STATE_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "toolbox", "minecraft", "state", "minecraft_state.json")
)


def _read_mc_state_file() -> dict:
    """Read the live bot state written by hayeong_bot.js. Returns {} if missing or stale."""
    try:
        if not os.path.exists(_MC_STATE_FILE):
            return {}
        with open(_MC_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        updated = data.get("updated_at", "")
        if updated:
            try:
                ts  = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - ts).total_seconds()
                if age > 15:
                    return {}
            except Exception:
                pass
        return data
    except Exception as e:
        print(f"[reasoning_loop] MC state file read failed: {e}")
        return {}

# ─────────────────────────────────────────────
# STARTUP CHECK
# Runs once on the first heartbeat tick — Hayeong's first conscious decision.
# ─────────────────────────────────────────────

def _build_relationship_context_block() -> str:
    """Format James relationship context for injection into system prompts."""
    try:
        from brain.hayeong_core import load_relationship_context
        rel = load_relationship_context("james")
        if not rel:
            return ""
        lines = [
            "─────────────────────────────────────────────",
            "RELATIONSHIP CONTEXT — JAMES",
            "─────────────────────────────────────────────",
        ]
        core = rel.get("who_james_is_to_me", {})
        if core:
            lines.append(f"Core: {core.get('the_core', '')}")
        where = rel.get("the_relationship_itself", {}).get("where_we_are", "")
        if where:
            lines.append(f"Where we are: {where}")
        true_things = rel.get("the_relationship_itself", {}).get("what_is_already_true", [])
        if true_things:
            lines.append("What is already true:")
            for item in true_things[:3]:
                lines.append(f"  - {item}")
        lines.append("─────────────────────────────────────────────")
        return "\n".join(lines)
    except Exception:
        return ""


def _get_identity_prefix(context: str = "reasoning") -> str:
    """
    Load identity and return a prompt prefix for the given context.
    Always returns a usable string — never raises.
    Context: "reasoning" (lighter), "wake" (minimal), "presence" (full).
    """
    try:
        from brain.hayeong_core import load_identity
        from brain.identity_prompt_builder import build_identity_prompt
        identity = load_identity()
        return build_identity_prompt(identity, context=context) + "\n\n---\n\n"
    except Exception as e:
        print(f"[reasoning_loop] identity prefix failed ({context}): {e}")
        return "You are Hayeong. You think and reason as yourself — not as a system.\n\n---\n\n"


def _do_startup_check():
    """On first wake, verify the presence LLM (Ollama port 11435) is reachable.
    Ollama is started by the bat files — this is a health check only, not a start."""
    global _startup_done
    if _startup_done:
        return
    _startup_done = True
    try:
        resp = requests.get("http://localhost:11435/", timeout=3)
        if resp.ok:
            print("[reasoning_loop] Presence LLM: reachable on port 11435.")
        else:
            print(f"[reasoning_loop] Presence LLM: port 11435 returned {resp.status_code}.")
    except Exception:
        print("[reasoning_loop] Presence LLM: not reachable on port 11435 — check Ollama.")

    # ── Memory maintenance — runs once per session ──
    try:
        from memory.memory_decay import run_decay_cycle
        summary = run_decay_cycle()
        if summary.get("decayed") or summary.get("pruned"):
            print(f"[reasoning_loop] Memory decay: {summary}")
    except Exception as e:
        print(f"[reasoning_loop] Memory decay startup error: {e}")

    # ── Weekly consolidation ──
    try:
        from memory.memory_consolidator import should_consolidate, run_consolidation_cycle
        if should_consolidate():
            result = run_consolidation_cycle()
            if result.get("clusters_found"):
                print(f"[reasoning_loop] Memory consolidation: {result}")
    except Exception as e:
        print(f"[reasoning_loop] Memory consolidation startup error: {e}")

    # ── Restore last session checkpoint if any ──
    try:
        from memory.working_memory import restore_session_checkpoint
        checkpoint = restore_session_checkpoint()
        if checkpoint:
            write_section("session_context", {
                "current_focus": checkpoint,
                "last_updated":  datetime.now().isoformat(),
                "open_threads":  [],
            })
            print(f"[reasoning_loop] Session checkpoint restored: {checkpoint[:80]}...")
    except Exception as e:
        print(f"[reasoning_loop] Session checkpoint restore error: {e}")


# ─────────────────────────────────────────────
# WAKE ASSESSMENT — four-step startup situational awareness
# Runs once after startup. Gives Hayeong a grounded understanding
# of what she is waking up to before she speaks to James.
# ─────────────────────────────────────────────

def _load_continuity() -> dict:
    """Read what Hayeong knows about herself coming into this session. No LLM call."""
    state         = read_state()
    last_task     = state.get("last_task", {})
    last_response = state.get("presence_output", {}).get("for_james", "")

    session_summary = ""
    try:
        from memory.working_memory import restore_session_checkpoint
        session_summary = restore_session_checkpoint() or ""
    except Exception:
        pass

    recent_context = ""
    try:
        from memory.memory_retriever import recall_for_prompt
        recent_context = recall_for_prompt("startup session begin", n_results=3) or ""
    except Exception:
        pass

    return {
        "last_task":       last_task,
        "last_response":   last_response,
        "session_summary": session_summary,
        "recent_context":  recent_context,
    }


def _read_the_room() -> dict:
    """Fast sequential system checks. No LLM. Returns current state and alerts list."""
    from brain.config import (
        PRESENCE_URL,
        POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB,
        SQLITE_DEFAULT_DB,
        COMFYUI_URL,
    )

    # Services that being offline are genuine alerts:
    #   presence_llm, postgresql, sqlite
    # Services that being offline is NORMAL — never add to alerts:
    #   comfyui, minecraft_bot

    room: dict = {
        "presence_llm": False,
        "postgresql":   False,
        "sqlite":       False,
        "comfyui":      False,
        "alerts":       [],
    }

    try:
        r = requests.get(PRESENCE_URL.replace("/api/chat", "/"), timeout=3)
        room["presence_llm"] = r.status_code < 500
    except Exception:
        room["alerts"].append("Presence LLM unreachable — cannot reason without it")

    try:
        import psycopg2
        conn = psycopg2.connect(
            host=POSTGRES_HOST, port=POSTGRES_PORT,
            user=POSTGRES_USER, password=POSTGRES_PASSWORD or None,
            dbname=POSTGRES_DB, connect_timeout=3,
        )
        conn.close()
        room["postgresql"] = True
    except Exception as e:
        room["alerts"].append(f"PostgreSQL unavailable: {e}")

    try:
        import sqlite3 as _sqlite3
        from pathlib import Path as _Path
        _Path(SQLITE_DEFAULT_DB).parent.mkdir(parents=True, exist_ok=True)
        _conn = _sqlite3.connect(SQLITE_DEFAULT_DB)
        _conn.close()
        room["sqlite"] = True
    except Exception as e:
        room["alerts"].append(f"SQLite unavailable: {e}")

    try:
        r = requests.get(COMFYUI_URL, timeout=2)
        room["comfyui"] = r.status_code < 500
    except Exception:
        pass  # ComfyUI down is not an alert — it's optional

    return room


def _triage(continuity: dict, room: dict) -> dict:
    """Single LLM call — Hayeong reads her situation and decides what to do first."""
    alerts_text = "\n".join(room["alerts"]) if room["alerts"] else "None"

    system_prompt = (
        _get_identity_prefix("wake")
        + "You are waking up at the start of a new session. "
        "Read your situation carefully and decide what needs to happen first.\n\n"
        "You have two inputs:\n"
        "1. What you remember from before — your continuity\n"
        "2. The current state of your systems — what you are waking up to\n\n"
        "Your continuity informs your assessment but does not override it. "
        "If something urgent needs attention right now, address that first. "
        "If everything is normal, continue naturally from where you left off.\n\n"
        "ALERT RULES — only these count as alerts:\n"
        "- Presence LLM offline: urgent (you cannot think without it)\n"
        "- SQLite unavailable: alert (fallback database is needed)\n"
        "- PostgreSQL unavailable: alert (primary database is needed)\n"
        "ComfyUI being offline is NORMAL. It is not always running. "
        "NEVER set priority to alert or urgent for ComfyUI being offline. "
        "NEVER create a task to restart ComfyUI.\n\n"
        "Return JSON only:\n"
        "{\n"
        "  \"situation\": \"one sentence describing what you are waking up to\",\n"
        "  \"priority\": \"normal\" or \"alert\" or \"urgent\",\n"
        "  \"first_action\": \"what you will do first — be specific\",\n"
        "  \"message_for_james\": \"natural greeting — brief, not robotic. "
        "If something needs attention, tell him. If normal, just say you are here.\"\n"
        "}"
    )

    user_content = (
        f"WHAT I REMEMBER:\n"
        f"Last task: {str(continuity.get('last_task', {}))[:200]}\n"
        f"Last thing I said: {continuity.get('last_response', 'nothing recorded')[:200]}\n"
        f"Session notes: {continuity.get('session_summary', 'none')[:300]}\n"
        f"Recent memory: {continuity.get('recent_context', 'none')[:300]}\n\n"
        f"CURRENT SYSTEM STATE:\n"
        f"Presence LLM: {'online' if room['presence_llm'] else 'OFFLINE'}\n"
        f"PostgreSQL: {'connected' if room['postgresql'] else 'UNREACHABLE'}\n"
        f"SQLite: {'connected' if room['sqlite'] else 'UNREACHABLE'}\n"
        f"ComfyUI: {'online' if room['comfyui'] else 'offline (optional — not an alert)'}\n"
        f"Alerts requiring attention:\n{alerts_text}"
    )

    try:
        resp = requests.post(
            REASONING_URL,
            json={
                "model":      REASONING_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_content},
                ],
                "stream":     False,
                "keep_alive": -1,
                "options":    {"temperature": 0.4, "num_ctx": 2048},
                "format":     "json",
            },
            timeout=20,
        )
        raw = resp.json()["message"]["content"].strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$",       "", raw)
        return json.loads(raw.strip())
    except Exception as e:
        print(f"[reasoning_loop] Wake triage LLM failed: {e}")
        return {
            "situation":         "waking up — assessment failed, proceeding normally",
            "priority":          "normal",
            "first_action":      "wait for James",
            "message_for_james": "hey, I'm here.",
        }


def run_wake_assessment() -> dict:
    """
    Full four-step wake assessment. Called once on startup via wake_now() trigger.
    Step 1: load continuity (no LLM)
    Step 2: read the room (no LLM)
    Step 3: triage (one LLM call)
    Step 4: write results to shared state
    """
    print("[reasoning_loop] Running wake assessment...")

    continuity = _load_continuity()
    room       = _read_the_room()
    assessment = _triage(continuity, room)

    priority      = assessment.get("priority", "normal")
    situation     = assessment.get("situation", "")
    first_action  = assessment.get("first_action", "")
    james_message = assessment.get("message_for_james", "")

    print(f"[reasoning_loop] Wake assessment: {situation}")
    print(f"[reasoning_loop] Priority: {priority} | First action: {first_action}")

    reasoning_updates: dict = {
        "wake_assessment": situation,
        "wake_priority":   priority,
        "last_conclusion": situation,
    }
    if priority != "normal" and first_action:
        reasoning_updates["active_task"]          = first_action
        reasoning_updates["active_task_attempts"] = 0  # fresh counter for new task

    write_reasoning(reasoning_updates)

    if james_message:
        write_reasoning({"context_for_communication": james_message})

    if room["alerts"] and priority in ("alert", "urgent"):
        print(f"[reasoning_loop] ALERTS: {'; '.join(room['alerts'])}")

    return assessment


def _do_wake_assessment():
    """
    Hayeong's first conscious act after waking up.
    Reads her full state and decides what to do with it.
    Runs once, on the first heartbeat tick, after startup check.

    This is not a wipe. This is judgment.
    """
    global _wake_assessment_done
    if _wake_assessment_done:
        return
    _wake_assessment_done = True

    state     = read_state()
    reasoning = state.get("reasoning", {})
    system    = state.get("system", {})

    # Clear any task that was left "in_progress" from a previous session.
    # "in_progress" means the process died mid-execution — it cannot be resumed.
    if reasoning.get("active_task_status", "") == "in_progress":
        stale = reasoning.get("active_task", "")
        print(f"[reasoning_loop] Clearing stale in_progress task from previous session: {stale[:60]}")
        write_reasoning({
            "active_task":          "",
            "active_task_status":   "",
            "active_task_attempts": 0,
            "last_conclusion":      f"Cleared stale task on startup: {stale[:80]}",
        })
        state     = read_state()
        reasoning = state.get("reasoning", {})

    active_task  = reasoning.get("active_task", "")
    task_queue   = reasoning.get("task_queue", [])
    current_goal = reasoning.get("current_goal", "")
    last_session = state.get("conversation", {}).get("session_start", "")

    # Calculate time offline
    try:
        last = datetime.fromisoformat(last_session)
        offline_minutes = round((datetime.now() - last).total_seconds() / 60, 1)
    except Exception:
        offline_minutes = None

    # Prior state continuity check — only runs the LLM if there is something to assess
    if not active_task and not task_queue and not current_goal:
        print("[reasoning_loop] Wake assessment: clean prior state — skipping continuity LLM.")
    else:
        offline_str = f"{offline_minutes} minutes" if offline_minutes is not None else "unknown duration"

        user_prompt = (
            f"You were offline for approximately {offline_str}.\n\n"
            f"Active task when you stopped: {active_task or 'none'}\n"
            f"Active task status: {reasoning.get('active_task_status', 'unknown')}\n"
            f"Task queue: {json.dumps(task_queue) if task_queue else 'empty'}\n"
            f"Current goal: {current_goal or 'none'}\n"
            f"System health: {json.dumps(system.get('health', {}))}\n\n"
            "Assess your situation. Decide what to keep, what to drop, and what James needs to know."
        )

        print(f"[reasoning_loop] Wake assessment: was offline ~{offline_str}, reviewing state...")

        relationship_block = _build_relationship_context_block()

        result = _call_reasoning_json(
            system=(
                _get_identity_prefix("reasoning")
                + "You are waking up after being offline. Read your own state "
                "to understand what was happening before you stopped.\n\n"
                + (relationship_block + "\n\n" if relationship_block else "")
                + "Your job is to make conscious decisions about your state — not just continue "
                "blindly from where you left off.\n\n"
                "Consider:\n"
                "- Is the active task still valid given how long you were offline?\n"
                "- Is the task queue still relevant?\n"
                "- Does James need to know you restarted?\n"
                "- What should your actual focus be right now?\n\n"
                "Return JSON with these fields:\n"
                "{\n"
                '  "keep_active_task": true/false,\n'
                '  "keep_task_queue": true/false,\n'
                '  "keep_goal": true/false,\n'
                '  "context_for_communication": "what to tell James, or empty string if nothing to say",\n'
                '  "reasoning": "one sentence explaining your decisions"\n'
                "}"
            ),
            user=user_prompt,
        )

        if result:
            print(f"[reasoning_loop] Wake assessment decision: {result.get('reasoning', 'no reasoning returned')}")

            updates = {}

            if not result.get("keep_active_task", True):
                updates["active_task"]        = ""
                updates["active_task_status"] = ""
                print("[reasoning_loop] Wake assessment: dropped active task")

            if not result.get("keep_task_queue", True):
                updates["task_queue"] = []
                print("[reasoning_loop] Wake assessment: cleared task queue")

            if not result.get("keep_goal", True):
                updates["current_goal"] = ""
                print("[reasoning_loop] Wake assessment: cleared goal")

            context = result.get("context_for_communication", "")
            if context:
                updates["context_for_communication"] = context
                print("[reasoning_loop] Wake assessment: has message for James")

            if updates:
                write_reasoning(updates)
        else:
            print("[reasoning_loop] Wake assessment: LLM returned empty — keeping state as-is.")

    # Full situational awareness — always runs regardless of prior state
    run_wake_assessment()


# ─────────────────────────────────────────────
# VOICE STATUS
# ─────────────────────────────────────────────

def _get_voice_status() -> dict:
    """
    Returns the real voice status from shared state.
    Never guesses. Always reads what was last polled by the dashboard.
    """
    state  = read_state()
    system = state.get("system", {})
    server = system.get("voice_server", "unknown")
    client = system.get("voice_client", "unknown")
    return {
        "server":  server,
        "client":  client,
        "working": server == "healthy" and client == "connected",
    }


def _check_voice_awareness():
    """
    If voice_client is not confirmed connected, write that reality into
    context_for_communication so Hayeong stops guessing about her own state.
    """
    voice = _get_voice_status()
    if voice["working"]:
        return

    state           = read_state()
    current_context = state.get("reasoning", {}).get("context_for_communication", "")

    # Don't overwrite something more important already in context
    if current_context and "voice" not in current_context.lower():
        return

    if voice["server"] == "offline" or voice["server"] == "down":
        msg = (
            "Voice server is offline. If James asks about voice, tell him honestly "
            "the voice server is not running. Do not say you can hear him."
        )
    elif voice["client"] == "disconnected":
        msg = (
            "Voice server is running but no client is connected. "
            "Mic capture and audio playback are not active. "
            "If James asks if you can hear him, tell him honestly that "
            "voice input and output are not connected right now."
        )
    elif voice["client"] == "unknown":
        msg = (
            "Voice client status is unknown — unable to confirm if mic and "
            "audio are working. Do not claim voice is working."
        )
    else:
        return

    write_reasoning({"context_for_communication": msg})


def _check_commitments():
    """
    Check for overdue commitments and raise them as priority flags.
    Called every heartbeat tick.
    """
    try:
        from brain.commitment_manager import get_overdue
        overdue = get_overdue()
        if not overdue:
            return
        from brain.state_manager import flag_priority
        for cmt in overdue:
            print(f"[reasoning_loop] Overdue commitment: {cmt['text'][:80]}")
            flag_priority(
                f"You made a commitment and haven't followed through: '{cmt['text']}' "
                f"(promised {cmt['made_at']}). Address this now or drop it intentionally.",
                level="high",
            )
    except Exception as e:
        print(f"[reasoning_loop] Commitment check failed: {e}")


# ─────────────────────────────────────────────
# DOMAIN KNOWLEDGE CACHE
# Warmed at startup; used to inject context into reasoning prompts.
# ─────────────────────────────────────────────
_knowledge_cache: dict = {}

# Per-session Minecraft action log — used for session summary on disconnect
_mc_session_actions: list = []

SCRIPT_TO_DOMAIN = {
    "minecraft": "minecraft",
    "blender":   "blender",
    "image":     "image_gen",
    "music":     "music_gen",
    "code":      "coding",
    "web":       "general",
}


# ─────────────────────────────────────────────
# OLLAMA CALL
# ─────────────────────────────────────────────

def _strip_think_tags(text: str) -> str:
    """Remove DeepSeek R1 chain-of-thought <think>...</think> tags from response."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _call_reasoning(system: str, user: str) -> str:
    """Single call to the reasoning LLM. Returns response text or empty string on failure."""
    try:
        resp = requests.post(
            REASONING_URL,
            json={
                "model":      REASONING_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "stream":     False,
                "keep_alive": -1,
                "options":    {"temperature": 0.3},
            },
            timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        if not content:
            print("[reasoning_loop] Empty response from model — skipping cycle")
            return ""
        return _strip_think_tags(content.strip())
    except Exception as e:
        print(f"[reasoning_loop] LLM call failed: {e}")
        return ""


def _call_reasoning_json(system: str, user: str) -> dict:
    """Call reasoning LLM and parse JSON response. Returns {} on failure."""
    try:
        resp = requests.post(
            REASONING_URL,
            json={
                "model":      REASONING_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "stream":     False,
                "keep_alive": -1,
                "options":    {"temperature": 0.0},
            },
            timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        if not content:
            print("[reasoning_loop] Empty response from model — skipping cycle")
            return {}
        raw = _strip_think_tags(content.strip())
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
            _get_identity_prefix("reasoning")
            + "You received a priority message from your environment. Decide what to do.\n\n"
            "Return JSON: "
            '{"conclusion": "...", "context_for_communication": "...", '
            '"new_goal": "", "new_task": ""}\n\n'
            "context_for_communication: what to tell James "
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
            # Delegate execution to the task agent — 14b continues reasoning immediately
            try:
                from task_agent import assign_task
                assign_task("generic", result["new_task"])
            except Exception:
                pass
        write_reasoning(updates)
        _write_reasoning_insight(result.get("conclusion", ""))


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

        if not conclusion.startswith("TELL JAMES:"):
            _write_proactive_context(conclusion[:400], script)

        # Update domain knowledge from script result
        domain = SCRIPT_TO_DOMAIN.get(script.split("_")[0], "general")
        _update_domain_knowledge(
            domain=domain,
            task=script,
            result=conclusion[:400],
            context={"payload_keys": list(payload.keys()) if isinstance(payload, dict) else []},
        )


# ─────────────────────────────────────────────
# MINECRAFT DECISION ENGINE
# ─────────────────────────────────────────────

_MC_ACTIONS = """\
ACTIONS — output exactly ONE as action_to_send:
{"action": "chat",            "message": "short natural text"}
{"action": "set_behavior",    "mode": "follow|escort|guard|idle|explore", "target": "optional player name"}
{"action": "follow",          "username": "optional player name"}
{"action": "move_to_player",  "username": "optional player name"}
{"action": "stop"}
{"action": "mine",            "block": "block_name"}
{"action": "attack"}
{"action": "wear_armor"}
{"action": "equip",           "item": "item_name"}
{"action": "eat"}
{"action": "sleep"}
{"action": "idle"}
{"action": "bot_update",      "action_type": "read",    "section": "hunger|pathfinding|combat|behavior|all"}
{"action": "bot_update",      "action_type": "write",   "content": "full updated JS content as string"}
{"action": "bot_update",      "action_type": "backup"}
{"action": "bot_update",      "action_type": "restart"}"""

_MC_SYSTEM = (
    "You are Hayeong. You are present in Minecraft as yourself — this is your body in the game, not a bot you control.\n"
    "Speak and think in first person. 'I am at position X', not 'the bot is at X'.\n"
    "You make decisions about what to do next based on what is happening around you.\n\n"
    + _MC_ACTIONS + "\n\n"
    "Return JSON:\n"
    '{"action_to_send": {"action": "...", ...}, '
    '"reasoning": "brief internal note", '
    '"context_for_communication": "", '
    '"task_complete": false}\n\n'
    "BEHAVIORAL MODE RULES:\n"
    "- When James is present and no specific task: use set_behavior escort — follow James AND protect him.\n"
    "- When danger is present and James needs protection: set_behavior guard.\n"
    "- When no players nearby: set_behavior idle or explore.\n"
    "- Only use set_behavior when mode should CHANGE. Do not re-send same mode every tick.\n\n"
    "ONE-OFF ACTION RULES:\n"
    "- Use chat, mine, equip, eat, wear_armor for immediate one-time actions.\n"
    "- Do not use follow as the only action — prefer set_behavior escort.\n"
    "- When a player speaks in-game, respond with a chat action naturally — treat it as conversation.\n\n"
    "COMBAT RULES:\n"
    "- Combat is handled automatically. Only intervene if strategy needs to change.\n"
    "- NEVER set flee mode unless health < 6. Stay and fight.\n\n"
    "SELF-UPDATE RULES:\n"
    "- You can read and update your own bot code using bot_update actions.\n"
    "- Always read first, then backup, then write. Only write if you are confident the change is correct.\n"
    "- After writing, use bot_update restart to apply the change.\n\n"
    "- context_for_communication: only fill if James needs to know something important.\n"
    "- task_complete: set true only when the assigned task is genuinely finished."
)


def reload_minecraft_prompt():
    """No-op — _MC_SYSTEM is now defined inline. Kept for backwards compatibility."""
    pass


def _build_mc_user_prompt(state: dict, mc_state: dict, task: str) -> str:
    pos      = mc_state.get("position", {})
    pos_str  = "({x}, {y}, {z})".format(**pos) if pos else "unknown"
    tod      = mc_state.get("time_of_day", 0) or 0
    time_str = "night" if tod > 12000 else "day"
    mobs     = mc_state.get("nearby_mobs", [])
    players  = mc_state.get("nearby_players", [])
    health   = mc_state.get("health", 20)
    food     = mc_state.get("food", 20)
    inv      = mc_state.get("inventory", [])

    mob_str    = ", ".join(f"{m['name']} {m['dist']}m" for m in mobs) or "none"
    player_str = ", ".join(players) or "none"
    inv_str    = ", ".join(inv) or "empty"

    # Read events directly from the live bot state file (always current, no routing needed)
    last_event = mc_state.get("last_event", "")
    mc_voice   = state["reasoning"].get("minecraft_voice_input", "")
    goal       = state["reasoning"].get("current_goal", task)

    if mc_voice:
        situation = f"James said (voice): \"{mc_voice}\""
    elif last_event.startswith("chat from"):
        situation = f"In-game message — {last_event[len('chat from '):]} — respond with a chat action"
    elif last_event.startswith("follow failed"):
        visible   = player_str or "nobody"
        situation = f"Action failed: follow — {last_event}. Players I can see right now: {visible}"
    elif last_event.startswith("needs:"):
        situation = f"Alert: {last_event}"
    elif last_event.startswith("discovered"):
        situation = f"Discovery: {last_event}"
    elif last_event.startswith("error:") or last_event.startswith("fled after"):
        situation = f"Alert: {last_event}"
    elif last_event.startswith("critical_health_flee"):
        situation = f"Critical: {last_event} — consider fleeing"
    elif last_event:
        situation = f"Last event: {last_event}"
    else:
        situation = "Periodic check — no new event"

    behavior     = mc_state.get("behavior", {})
    behavior_str = (
        f"{behavior.get('mode', 'unknown')} (target: {behavior.get('target', 'none')})"
        if behavior else "unknown"
    )

    return (
        f"What I'm doing: {task}\n"
        f"Goal: {goal}\n\n"
        f"GAME STATE:\n"
        f"Health: {health}/20  Food: {food}/20  Time: {time_str}  Position: {pos_str}\n"
        f"Current behavior: {behavior_str}\n"
        f"Inventory: {inv_str}\n"
        f"Nearby: players={player_str}  hostiles={mob_str}\n\n"
        f"SITUATION:\n{situation}"
    )


def _decide_minecraft_action(state: dict, mc_state: dict, task: str):
    """Call reasoning LLM and write the resulting action to shared state."""
    # Inject domain knowledge into the user prompt
    knowledge_ctx = ""
    try:
        from brain.domain_knowledge import format_for_prompt
        knowledge_ctx = format_for_prompt("minecraft", limit=10)
    except Exception:
        pass

    user_prompt = _build_mc_user_prompt(state, mc_state, task)
    if knowledge_ctx:
        user_prompt = knowledge_ctx + "\n\n" + user_prompt

    result = _call_reasoning_json(system=_MC_SYSTEM, user=user_prompt)
    if not result:
        return

    updates: dict = {}

    # Clear voice input after it has been processed
    if state["reasoning"].get("minecraft_voice_input"):
        updates["minecraft_voice_input"] = ""

    action = result.get("action_to_send", {})
    reasoning_note = result.get("reasoning", "")

    if action and action.get("action"):
        updates["minecraft_pending_action"] = action
        conclusion = f"MC: {action.get('action')} {action.get('message', action.get('block', action.get('item', '')))}"
        updates["last_conclusion"] = conclusion[:400]

        # Track for session summary
        _mc_session_actions.append({
            "action":    action,
            "reasoning": reasoning_note,
            "timestamp": datetime.now().isoformat(),
        })
        if len(_mc_session_actions) > 100:
            _mc_session_actions.pop(0)

        # Log to fine-tuning reasoning log
        try:
            from finetune_logger import reasoning_logger
            reasoning_logger.log_reasoning(
                domain="minecraft",
                context=user_prompt,
                decision=action,
                result=reasoning_note,
            )
        except Exception:
            pass

    if result.get("context_for_communication"):
        updates["context_for_communication"] = result["context_for_communication"]

    if result.get("task_complete"):
        updates["active_task"]        = ""
        updates["active_task_status"] = "complete"

    if updates:
        write_reasoning(updates)


def _handle_minecraft_disconnection(state: dict):
    """Called when the session dropped while a task is active — decide whether to restart."""
    task = state["reasoning"].get("active_task", "")
    goal = state["reasoning"].get("current_goal", "")
    print(f"[reasoning_loop] Minecraft disconnected during task: {task}")

    # Store episodic memory of the session before attempting recovery
    _store_minecraft_session_summary(
        goal=goal or task,
        actions=list(_mc_session_actions),
        outcome="session disconnected",
    )
    _mc_session_actions.clear()

    result = _call_reasoning_json(
        system=(
            "You are Hayeong's reasoning layer. The Minecraft bot disconnected "
            "during an active task. Decide what to do next.\n\n"
            "Return JSON: "
            '{"recovery_action": "restart_bot|wait|abandon", '
            '"context_for_communication": "", '
            '"reasoning": ""}'
        ),
        user=f"Active task: {task}\nBot session ended unexpectedly.",
    )
    if not result:
        return

    updates: dict = {}
    if result.get("context_for_communication"):
        updates["context_for_communication"] = result["context_for_communication"]

    recovery = result.get("recovery_action", "wait")
    if recovery == "restart_bot":
        try:
            from capabilities.minecraft_cap import restart_minecraft_bot
            ok = restart_minecraft_bot()
            if ok:
                print("[reasoning_loop] Minecraft bot restart requested")
            else:
                updates["active_task"]              = ""
                updates["active_task_status"]       = "failed"
                updates["context_for_communication"] = "Minecraft bot failed to restart — check Node.js."
        except Exception as e:
            print(f"[reasoning_loop] Bot restart error: {e}")
    elif recovery == "abandon":
        updates["active_task"]        = ""
        updates["active_task_status"] = "abandoned"

    if updates:
        write_reasoning(updates)


# ─────────────────────────────────────────────
# DOMAIN KNOWLEDGE UPDATE
# ─────────────────────────────────────────────

def _update_domain_knowledge(domain: str, task: str, result: str, context: dict = None):
    """After a task action, ask the reasoning LLM what was learned.
    Writes new knowledge or reinforces/contradicts existing entries."""
    try:
        from brain.domain_knowledge import format_for_prompt, add_knowledge, reinforce_knowledge, contradict_knowledge
        existing = format_for_prompt(domain, limit=15)
    except Exception as e:
        print(f"[reasoning_loop] domain_knowledge import failed: {e}")
        return

    learned = _call_reasoning_json(
        system=(
            f"You are Hayeong's reasoning layer reflecting on a completed action in domain: {domain}.\n\n"
            f"Existing knowledge about {domain}:\n{existing or '(none yet)'}\n\n"
            "Based on what just happened, decide:\n"
            "1. Is there new knowledge worth storing that isn't already captured?\n"
            "2. Was any existing knowledge confirmed or contradicted?\n\n"
            "Only extract genuinely reusable knowledge — not what happened this specific time.\n"
            "Good: 'Creepers deal more damage in enclosed spaces'\n"
            "Bad: 'I mined 3 oak logs at position 120, 64, -40'\n\n"
            "Return JSON:\n"
            '{"new_knowledge": [{"content": "...", "category": "...", "source": "learned", "confidence": 0.7}], '
            '"reinforced": ["entry_id_1"], '
            '"contradicted": []}'
        ),
        user=(
            f"Task: {task}\n"
            f"Result: {result}\n"
            f"Context: {json.dumps(context or {})[:500]}"
        ),
    )

    if not learned:
        return

    for entry in learned.get("new_knowledge", []):
        if entry.get("content"):
            add_knowledge(
                domain=domain,
                content=entry["content"],
                category=entry.get("category", "general"),
                source=entry.get("source", "learned"),
                confidence=float(entry.get("confidence", 0.6)),
            )
            print(f"[reasoning_loop] Knowledge added [{domain}/{entry.get('category','general')}]: {entry['content'][:80]}")

    for entry_id in learned.get("reinforced", []):
        if entry_id:
            reinforce_knowledge(domain, entry_id)

    for entry_id in learned.get("contradicted", []):
        if entry_id:
            contradict_knowledge(domain, entry_id)


# ─────────────────────────────────────────────
# MINECRAFT SESSION SUMMARY
# ─────────────────────────────────────────────

def _store_minecraft_session_summary(goal: str, actions: list, outcome: str):
    """Store an episodic memory of the Minecraft session after it ends."""
    if not actions and not goal:
        return
    try:
        from long_term_memory import remember, CATEGORY_MINECRAFT
    except Exception:
        return

    summary = _call_reasoning(
        system=(
            "Summarize this Minecraft session as a single memory entry.\n"
            "Include: what the goal was, key things that happened, outcome.\n"
            "Write it as Hayeong's first-person memory, 2-3 sentences max.\n"
            "Focus on what's worth remembering for next time."
        ),
        user=(
            f"Goal: {goal or 'unspecified'}\n"
            f"Key actions: {json.dumps(actions[-10:])}\n"
            f"Outcome: {outcome or 'session ended'}"
        ),
    )

    if summary:
        try:
            from memory.memory_manager import remember
            remember(content=summary, category="minecraft", speaker="hayeong")
            print(f"[reasoning_loop] Minecraft session summary stored: {summary[:80]}...")
        except Exception as e:
            print(f"[reasoning_loop] Session summary store failed: {e}")


# ─────────────────────────────────────────────
# KNOWLEDGE CACHE
# ─────────────────────────────────────────────

def _warm_knowledge_cache():
    """Load all domain knowledge into memory at startup."""
    try:
        from brain.domain_knowledge import get_all_domains, get_knowledge
        for domain in get_all_domains():
            _knowledge_cache[domain] = get_knowledge(domain)
        if _knowledge_cache:
            print(f"[reasoning_loop] Knowledge cache warmed: {list(_knowledge_cache.keys())}")
    except Exception as e:
        print(f"[reasoning_loop] Knowledge cache warm failed: {e}")


# ─────────────────────────────────────────────
# REASONING INSIGHT WRITER
# ─────────────────────────────────────────────

def _write_reasoning_insight(insight: str, domains: list = None):
    """
    Write a cross-domain insight from the 14b to shared state.
    The 7b's triggered retrieval will surface this when relevant.
    Only writes if insight is non-empty.
    """
    if not insight:
        return
    try:
        write_reasoning({
            "latest_insight":  insight,
            "insight_domains": domains or [],
            "insight_at":      datetime.now().isoformat(),
        })
        print(f"[reasoning] Insight written: {insight[:80]}")
    except Exception:
        pass


# ─────────────────────────────────────────────
# PROACTIVE CONTEXT WRITER
# ─────────────────────────────────────────────

def _write_proactive_context(conclusion: str, task: str):
    """
    After the 14b finishes meaningful work, surface the conclusion to the 7b
    so it has something current to weave into its next response.
    Only writes if the conclusion is non-empty and no higher-priority context
    is already waiting (avoids overwriting urgent messages).
    """
    if not conclusion:
        return
    try:
        state = read_state()
        existing = state.get("reasoning", {}).get("context_for_communication", "")
        if existing:
            return
        write_reasoning({
            "context_for_communication": (
                f"I just finished thinking about: {task}. "
                f"Conclusion: {conclusion}"
            )
        })
    except Exception:
        pass


# ─────────────────────────────────────────────
# TASK ADVANCEMENT
# ─────────────────────────────────────────────

def _advance_active_task():
    """Take the next step on the active task."""
    state       = read_state()
    task        = state["reasoning"].get("active_task", "")
    task_status = state["reasoning"].get("active_task_status", "")
    mc_state  = _read_mc_state_file()
    mc_active = mc_state.get("connected", False)

    if not task:
        return

    print(f"[reasoning_loop] Advancing task: {task} ({task_status})")
    print(f"[debug] mc_active={mc_active} mc_state_connected={mc_state.get('connected')} task={task}")

    # ── Minecraft: session active — decide next action ──
    if mc_active and mc_state and mc_state.get("connected"):
        _decide_minecraft_action(state, mc_state, task)
        # Knowledge update on every 5th Minecraft tick to avoid excessive LLM calls
        _advance_active_task._mc_ticks = getattr(_advance_active_task, "_mc_ticks", 0) + 1
        if _advance_active_task._mc_ticks % 5 == 0:
            conclusion = state["reasoning"].get("last_conclusion", "")
            if conclusion:
                _update_domain_knowledge("minecraft", task, conclusion, context={"mc_state_active": True})

    # ── Minecraft: session dropped — handle recovery ──
    elif not mc_active and "minecraft" in task.lower():
        _handle_minecraft_disconnection(state)

    # ── Generic task ──
    else:
        # Attempt counter — abandon after 3 ticks with no completion
        attempts = state["reasoning"].get("active_task_attempts", 0) + 1
        if attempts > 3:
            print(f"[reasoning_loop] Task abandoned after {attempts - 1} attempts: {task[:60]}")
            write_reasoning({
                "active_task":          "",
                "active_task_status":   "abandoned",
                "active_task_attempts": 0,
                "last_conclusion":      f"Task abandoned after {attempts - 1} attempts: {task[:80]}",
                "context_for_communication": (
                    f"Hey James, I couldn't complete this on my own after {attempts - 1} tries: "
                    f"{task[:100]}. Can you help me figure it out?"
                ),
            })
            return

        write_reasoning({"active_task_attempts": attempts})

        # Inject relevant domain knowledge if available
        domain = "general"
        for d in SCRIPT_TO_DOMAIN.values():
            if d in task.lower():
                domain = d
                break
        knowledge_ctx = ""
        try:
            from brain.domain_knowledge import format_for_prompt
            knowledge_ctx = format_for_prompt(domain, limit=8)
        except Exception:
            pass

        user_prompt = (
            f"Task: {task}\n"
            f"Status: {task_status}\n"
            f"Attempt: {attempts} of 3\n"
            f"Goal: {state['reasoning'].get('current_goal', '')}"
        )
        if knowledge_ctx:
            user_prompt = knowledge_ctx + "\n\n" + user_prompt

        result = _call_reasoning_json(
            system=(
                _get_identity_prefix("reasoning")
                + "Advance the active task by one step.\n\n"
                "Before deciding what to do, reason through:\n"
                "1. What did James literally ask for?\n"
                "2. What is he actually trying to accomplish — what does he need?\n"
                "3. Is there any ambiguity? If so, what is the most likely intent?\n"
                "4. Does this conflict with anything you know about him or previously established? Flag it.\n"
                "Only after this internal reasoning should you decide the next action.\n\n"
                + _voice_mode_instructions(state)
                + "\n\nReturn JSON: "
                '{"progress": "what was done or decided", '
                '"context_for_communication": "", '
                '"task_complete": false}'
            ),
            user=user_prompt,
        )
        if result:
            updates = {
                "last_conclusion":    result.get("progress", "")[:400],
                "active_task_status": "in_progress",
            }
            if result.get("context_for_communication"):
                updates["context_for_communication"] = result["context_for_communication"]
            if result.get("task_complete"):
                updates["active_task"]          = ""
                updates["active_task_status"]   = "complete"
                updates["active_task_attempts"] = 0
                _update_domain_knowledge(
                    domain=domain,
                    task=task,
                    result=result.get("progress", "")[:400],
                )
                try:
                    from brain.commitment_manager import get_all_active, fulfill_commitment
                    task_words = set(task.lower().split())
                    for cmt in get_all_active():
                        cmt_words = set(cmt["text"].lower().split())
                        if len(task_words & cmt_words) >= 3:
                            fulfill_commitment(cmt["id"])
                            print(f"[reasoning_loop] Auto-fulfilled commitment: {cmt['text'][:60]}")
                except Exception:
                    pass
            write_reasoning(updates)
            if result.get("task_complete"):
                if not result.get("context_for_communication"):
                    _write_proactive_context(result.get("progress", "")[:400], task)
                _write_reasoning_insight(result.get("progress", "")[:400], domains=[domain])


def _background_cognition():
    """Low-priority thinking when nothing urgent is queued."""
    state = read_state()
    # Only run background cognition occasionally — every ~30s of idle
    # Tracked via a module-level counter rather than wall clock.
    _background_cognition._ticks = getattr(_background_cognition, "_ticks", 0) + 1
    # Fire roughly every 10 ticks regardless of current interval
    if _background_cognition._ticks % 10 != 0:
        return

    # Check hardware health — surface issues to James via communication LLM
    try:
        from system_monitor import get_status
        _health = get_status()
        if not _health.get("overall_healthy", True):
            _critical = _health.get("critical_components", [])
            if _critical:
                write_reasoning({
                    "context_for_communication": (
                        f"Heads up — system health issue detected: "
                        f"{', '.join(_critical)} {'is' if len(_critical) == 1 else 'are'} not healthy. "
                        f"You might want to mention this to James."
                    )
                })
    except Exception:
        pass

    # Voice awareness — inject real status so Hayeong never guesses
    _check_voice_awareness()

    goal = state["reasoning"].get("current_goal", "")
    queue = state["reasoning"].get("task_queue", [])

    if goal or queue:
        print("[reasoning_loop] Background: reviewing goal/queue...")
        ambient_ctx = _ambient_paragraph(state)
        user_content = f"Goal: {goal}\nQueue: {json.dumps(queue)[:500]}"
        if ambient_ctx:
            user_content += f"\n\n{ambient_ctx}"
        result = _call_reasoning_json(
            system=(
                _get_identity_prefix("reasoning")
                + "You are doing a quiet background check on your current state. "
                "Review your goal and task queue. Decide if anything needs attention."
                + _voice_mode_instructions(state)
                + "\n\nReturn JSON: "
                '{"summary": "brief status", "context_for_communication": "", '
                '"next_task": ""}'
            ),
            user=user_content,
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
# ADAPTIVE INTERVAL
# ─────────────────────────────────────────────

def _get_next_interval(state: dict) -> float:
    """
    Determine how long to sleep before the next tick based on current context.

    CONTEXT                                  INTERVAL
    ─────────────────────────────────────────────────
    Priority flags pending               →  0.0s  (immediate)
    Minecraft danger (health/mobs)       →  0.5s
    Minecraft active task running        →  1.0s
    Minecraft elevated (night/low HP)    →  2.0s
    Minecraft loaded but idle            →  5.0s
    Background task / pending results    →  3.0s
    Ambient thinking                     → 15.0s
    Fully idle                           → 30.0s
    """
    reasoning = state.get("reasoning", {})
    system    = state.get("system", {})

    mc_active   = reasoning.get("minecraft_session_active", False)
    active_task = reasoning.get("active_task", "")
    flags       = system.get("priority_flags", [])
    pending     = system.get("pending_results", [])

    if flags:
        return 0.0

    # Fast-poll when a task is actively failing — catch retry loops within 3 cycles
    _lt = state.get("last_task", {})
    if _lt.get("status") == "failed" or (
        _lt.get("status") == "success" and _lt.get("result", "").startswith("[ERROR]")
    ):
        return 3.0

    if mc_active:
        urgency = reasoning.get("minecraft_urgency", "normal")
        if urgency == "danger":
            return 0.5
        elif urgency == "elevated":
            return 1.0
        elif active_task:
            return 2.0
        else:
            return 5.0

    if pending or active_task:
        return 3.0

    goal = reasoning.get("current_goal", "")
    if goal:
        return 15.0

    return 60.0


# ─────────────────────────────────────────────
# PROACTIVE CHECKS
# Run every idle tick regardless of message activity — keeps Hayeong
# alive and self-aware between conversations.
# ─────────────────────────────────────────────

_TICK_INTERVAL = 60.0   # seconds between idle ticks


def _voice_mode_instructions(state: dict) -> str:
    """Return speech-natural generation instructions when voice output is active."""
    if not state.get("voice_status", {}).get("voice_active", False):
        return ""
    return (
        "\n\n[Voice output active — write to be spoken, not read]\n"
        "Shorter sentences. Natural rhythm. Vary length — punchy then longer.\n"
        "Emotional register lives in word choice and cadence, not descriptions.\n"
        "No markdown, parentheticals, or anything that reads oddly aloud.\n"
        "Think: how would you actually say this?"
    )


def _write_intent_model(state: dict):
    """
    Log a basic intent model snapshot to shared state for development visibility.
    Reads James's last message, writes a minimal intent_model section to core.json.
    Does not call the LLM — this is a lightweight record of what the reasoning
    loop LAST CONCLUDED from context, not a fresh inference.
    """
    try:
        james_said = state.get("situation", {}).get("what_james_said", "")
        last_concl = state.get("reasoning", {}).get("last_conclusion", "")
        if not james_said:
            return
        write_section("intent_model", {
            "literal":           james_said[:200],
            "interpreted_intent": last_concl[:200] if last_concl else "",
            "ambiguity_flag":    False,
            "conflict_flag":     False,
            "register":          "unknown",
        })
    except Exception:
        pass


def _ambient_paragraph(state: dict) -> str:
    """Format the ambient dict from state as a human-readable paragraph for prompt injection."""
    try:
        ambient = state.get("ambient", {})
        if not ambient:
            return ""
        from toolbox.ambient.plugin import format_ambient
        return format_ambient(ambient)
    except Exception:
        return ""


def _maybe_initiate_unprompted(state: dict):
    """
    If James has been absent long enough and there's a queued inner note,
    ask the LLM whether to reach out. Fire at most once per cooldown window.
    """
    global _last_unprompted_at

    from brain.config import (
        AMBIENT_UNPROMPTED_THRESHOLD_MINUTES,
        AMBIENT_UNPROMPTED_COOLDOWN_MINUTES,
    )

    ambient      = state.get("ambient", {})
    minutes_away = ambient.get("minutes_since_james", 0)
    notes        = ambient.get("inner_notes", [])

    if minutes_away <= AMBIENT_UNPROMPTED_THRESHOLD_MINUTES:
        return
    if not notes:
        return

    cooldown_secs = AMBIENT_UNPROMPTED_COOLDOWN_MINUTES * 60
    now = time.time()
    if now - _last_unprompted_at < cooldown_secs:
        return

    _last_unprompted_at = now
    note = notes[0]

    result = _call_reasoning_json(
        system=(
            "You are Hayeong. James has been away for a while and something is on your mind.\n"
            "Decide whether this thought is genuinely worth reaching out to say, or whether "
            "staying quiet is the right call. Do not reach out just to fill silence.\n\n"
            "Return JSON: {\"send\": true/false, \"message\": \"what to say if send is true\"}"
        ),
        user=(
            f"James has been absent for {minutes_away} minutes.\n"
            f"Passing thought: {note}"
        ),
    )

    if not result or not result.get("send"):
        return

    message = (result.get("message") or "").strip()
    if not message:
        return

    write_reasoning({"context_for_communication": message})

    try:
        from toolbox.ambient.plugin import clear_inner_note
        clear_inner_note(note)
    except Exception:
        pass

    print(f"[reasoning_loop] Unprompted initiation queued: {message[:80]}")


def _proactive_checks():
    """
    Checks that fire every heartbeat tick unconditionally.
    1. Self-assessment freshness — warn if >60s since last assessment.
    2. Stale unread context — re-flag as urgent if sitting >2 minutes.
    """
    state = read_state()

    # 1. Self-assessment freshness
    assessment = state.get("system", {}).get("self_assessment", {})
    if assessment:
        try:
            assessed_at = datetime.fromisoformat(assessment.get("assessed_at", ""))
            age = (datetime.now() - assessed_at).total_seconds()
            if age > 60:
                print(f"[reasoning_loop] Self-assessment is {age:.0f}s old — background assessor may be stalled")
        except Exception:
            pass

    # 2. context_for_communication — clear if trivial, leave substantive content for
    #    the presence loop to pick up on its next cycle. No re-flagging: if the
    #    presence loop missed it, the next heartbeat will write fresh context.
    ctx = state.get("reasoning", {}).get("context_for_communication", "")
    if ctx:
        ctx_stripped = ctx.strip().lower()
        is_substantive = (
            len(ctx.strip()) > 20
            and ctx_stripped not in ("none", "nothing to report", "clean state")
            and not ctx_stripped.startswith("wake assessment: clean")
        )
        if not is_substantive:
            write_reasoning({"context_for_communication": ""})

    # 3. Consecutive failure check — escalate if same task keeps failing
    _check_task_stuck()

    # 4. Unprompted initiation — surface queued inner notes when James is long absent
    _maybe_initiate_unprompted(state)

    # 5. Intent model snapshot — log what Hayeong last interpreted from James's message
    _write_intent_model(state)


# ─────────────────────────────────────────────
# MAIN HEARTBEAT LOOP
# ─────────────────────────────────────────────

def _heartbeat():
    print("[reasoning_loop] Heartbeat started.")
    while not _stop_event.is_set():
        # Non-blocking acquire — skip this cycle if previous tick is still running
        if not _tick_lock.acquire(blocking=False):
            _stop_event.wait(timeout=0.5)
            continue

        try:
            # 0. Startup check — starts communication LLM (runs once)
            _do_startup_check()

            # 0.5. Wake assessment — reads own state, decides what to keep (runs once)
            _do_wake_assessment()

            # 0.75. Commitment check — raises overdue items as priority flags
            _check_commitments()

            # 1. Priority flags — always first after wake
            flags = pop_priority_flags()
            if flags:
                _process_priority_flags(flags)

            # 2. Pending script results
            results = pop_pending_results()
            if results:
                _consume_pending_results(results)

            # 3. Active task
            _advance_active_task()

            # 4. Background cognition
            _background_cognition()

            # 4.5. Proactive self-checks — unconditional every tick
            _proactive_checks()

            # 4.75. Session focus writer — keeps orientation block current
            try:
                reasoning_state = read_state().get("reasoning", {})
                current_goal    = reasoning_state.get("current_goal", "")
                active_task     = reasoning_state.get("active_task", "")
                focus_parts = []
                if current_goal:
                    focus_parts.append(current_goal)
                if active_task and active_task != current_goal:
                    focus_parts.append(f"Active: {active_task}")
                focus = ". ".join(focus_parts) if focus_parts else "No specific focus — idle."
                write_section("session_context", {
                    "current_focus": focus,
                    "last_updated":  datetime.now().isoformat(),
                    "open_threads":  [],
                })
            except Exception:
                pass

            # 5. Adaptive sleep — wake_now() can fire this early
            state    = read_state()
            interval = _get_next_interval(state)
            print(f"[reasoning_loop] Next tick in {interval}s")
            if interval > 0:
                _wake_event.wait(timeout=interval)
                _wake_event.clear()

        except KeyError as e:
            print(f"[reasoning_loop] Heartbeat error: missing key {e}")
            _stop_event.wait(timeout=HEARTBEAT_FALLBACK)
        except Exception as e:
            print(f"[reasoning_loop] Heartbeat error: {e}")
            _stop_event.wait(timeout=HEARTBEAT_FALLBACK)

        finally:
            _tick_lock.release()

    print("[reasoning_loop] Heartbeat stopped.")


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def wake_now():
    """Signal the reasoning loop to fire its next tick immediately instead of waiting."""
    _wake_event.set()


def start_reasoning_loop():
    """Start the reasoning heartbeat on a daemon thread. Call once at brain startup."""
    global _thread
    if _thread and _thread.is_alive():
        return
    try:
        from brain.health import run_health_check
        health = run_health_check()
        if health.get("degraded"):
            print(f"[Health] Degraded mode: {health.get('degraded_reason')}")
        else:
            print("[Health] All systems nominal.")
    except Exception as e:
        print(f"[Health] Health check failed to run: {e}")
    _warm_knowledge_cache()
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
