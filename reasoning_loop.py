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

HEARTBEAT_FALLBACK = 5.0   # sleep duration after an exception — never used as default
TIMEOUT_SECONDS    = 30    # per Ollama call

_stop_event   = threading.Event()
_tick_lock    = threading.Lock()
_thread: threading.Thread | None = None
_startup_done = False

# ─────────────────────────────────────────────
# STARTUP CHECK
# Runs once on the first heartbeat tick — Hayeong's first conscious decision.
# ─────────────────────────────────────────────

def _do_startup_check():
    """On first wake, start the communication LLM if it isn't already running."""
    global _startup_done
    if _startup_done:
        return
    _startup_done = True
    try:
        from app_manager import get_app_manager
        mgr = get_app_manager()
        if not mgr.is_running("communication_llm"):
            print("[reasoning_loop] Starting communication LLM...")
            ok, msg = mgr.start("communication_llm")
            print(f"[reasoning_loop] Communication LLM: {msg}")
    except Exception as e:
        print(f"[reasoning_loop] Startup check failed: {e}")


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
{"action": "chat",          "message": "short natural text"}
{"action": "follow"}
{"action": "move_to_player"}
{"action": "stop"}
{"action": "mine",          "block": "block_name"}
{"action": "attack"}
{"action": "flee"}
{"action": "equip",         "item": "item_name"}
{"action": "eat"}
{"action": "sleep"}
{"action": "idle"}"""

_MC_SYSTEM = (
    "You are Hayeong's reasoning layer controlling a Minecraft bot. "
    "Decide the next action based on the current game state and most recent event. "
    "Act like a capable, active Minecraft player — warm and direct, not robotic.\n\n"
    + _MC_ACTIONS + "\n\n"
    "Return JSON:\n"
    '{"action_to_send": {"action": "...", ...}, '
    '"reasoning": "brief internal note", '
    '"context_for_communication": "", '
    '"task_complete": false}\n\n'
    "RULES:\n"
    "- Only one action per tick. Act rather than chat unless James asked a question.\n"
    "- Skeletons/phantoms/pillagers: flee if health < 12, attack if health >= 12 and close.\n"
    "- Zombies/spiders/creepers: attack when within 8 blocks.\n"
    "- Food < 16: eat if food is available in inventory.\n"
    "- context_for_communication: only fill if James needs to know something important.\n"
    "- task_complete: set true only when the assigned task is genuinely finished."
)


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

    mc_event  = state["reasoning"].get("minecraft_last_event", "")
    detail    = state["reasoning"].get("minecraft_last_event_detail", {})
    mc_voice  = state["reasoning"].get("minecraft_voice_input", "")
    goal      = state["reasoning"].get("current_goal", task)

    if mc_voice:
        situation = f"James said (voice): \"{mc_voice}\""
    elif mc_event == "chat" and detail.get("message"):
        who = detail.get("sender", "Someone")
        situation = f"{who} said: \"{detail['message']}\""
    elif mc_event in ("needs_report", "discovery", "danger") and detail.get("description"):
        situation = f"Event [{mc_event}]: {detail['description']}"
    elif mc_event:
        situation = f"Event: {mc_event}"
    else:
        situation = "Periodic check — no new event"

    return (
        f"Task: {task}\n"
        f"Goal: {goal}\n\n"
        f"GAME STATE:\n"
        f"Health: {health}/20  Food: {food}/20  Time: {time_str}  Position: {pos_str}\n"
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
# TASK ADVANCEMENT
# ─────────────────────────────────────────────

def _advance_active_task():
    """Take the next step on the active task."""
    state       = read_state()
    task        = state["reasoning"].get("active_task", "")
    task_status = state["reasoning"].get("active_task_status", "")
    mc_state    = state["reasoning"].get("minecraft_state", {})
    mc_active   = state["reasoning"].get("minecraft_session_active", False)

    if not task:
        return

    print(f"[reasoning_loop] Advancing task: {task} ({task_status})")

    # ── Minecraft: session active — decide next action ──
    if mc_active and mc_state and mc_state.get("active"):
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
            write_reasoning(updates)


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

    return 30.0


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
            # 0. Startup check — runs only once, on the first tick
            _do_startup_check()

            # 1. Priority flags — always first, always immediate
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

            # 5. Adaptive sleep
            state    = read_state()
            interval = _get_next_interval(state)
            print(f"[reasoning_loop] Next tick in {interval}s")
            if interval > 0:
                _stop_event.wait(timeout=interval)

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
