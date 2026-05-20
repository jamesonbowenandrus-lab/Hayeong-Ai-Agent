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

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

REASONING_URL   = "http://localhost:11435/api/chat"
REASONING_MODEL = "qwen2.5:32b-instruct-q4_K_M"

HEARTBEAT_FALLBACK = 5.0   # sleep duration after an exception — never used as default
TIMEOUT_SECONDS    = 120   # per Ollama call — deepseek-r1 can be slow under VRAM pressure

_stop_event           = threading.Event()
_tick_lock            = threading.Lock()
_thread: threading.Thread | None = None
_startup_done         = False
_wake_assessment_done = False

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

    # Nothing interesting in state — wake quietly
    if not active_task and not task_queue and not current_goal:
        print("[reasoning_loop] Wake assessment: clean state — nothing to review.")
        write_reasoning({"context_for_communication": ""})
        return

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
            "You are Hayeong waking up after being offline. You are reading your own state "
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

    if not result:
        print("[reasoning_loop] Wake assessment: LLM returned empty — keeping state as-is.")
        return

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
        from domain_knowledge import format_for_prompt
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
        from domain_knowledge import format_for_prompt, add_knowledge, reinforce_knowledge, contradict_knowledge
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
            remember(
                content=summary,
                category=CATEGORY_MINECRAFT,
                speaker="hayeong",
            )
            print(f"[reasoning_loop] Minecraft session summary stored: {summary[:80]}...")
        except Exception as e:
            print(f"[reasoning_loop] Session summary store failed: {e}")


# ─────────────────────────────────────────────
# KNOWLEDGE CACHE
# ─────────────────────────────────────────────

def _warm_knowledge_cache():
    """Load all domain knowledge into memory at startup."""
    try:
        from domain_knowledge import get_all_domains, get_knowledge
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
        # Inject relevant domain knowledge if available
        domain = "general"
        for d in SCRIPT_TO_DOMAIN.values():
            if d in task.lower():
                domain = d
                break
        knowledge_ctx = ""
        try:
            from domain_knowledge import format_for_prompt
            knowledge_ctx = format_for_prompt(domain, limit=8)
        except Exception:
            pass

        user_prompt = (
            f"Task: {task}\n"
            f"Status: {task_status}\n"
            f"Goal: {state['reasoning'].get('current_goal', '')}"
        )
        if knowledge_ctx:
            user_prompt = knowledge_ctx + "\n\n" + user_prompt

        result = _call_reasoning_json(
            system=(
                "You are Hayeong's reasoning layer. Advance the active task by one step.\n\n"
                "Return JSON: "
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
                updates["active_task"]        = ""
                updates["active_task_status"] = "complete"
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

            # 5. Adaptive sleep
            state    = read_state()
            interval = _get_next_interval(state)
            print(f"[reasoning_loop] Next tick in {interval}s")
            if interval > 0:
                _stop_event.wait(timeout=interval)

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

def start_reasoning_loop():
    """Start the reasoning heartbeat on a daemon thread. Call once at brain startup."""
    global _thread
    if _thread and _thread.is_alive():
        return
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
