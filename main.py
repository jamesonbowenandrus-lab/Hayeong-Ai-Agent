"""
main.py — Hayeong's core.

Single presence loop. Shared state. Nothing else.

Presence loop  — Qwen 32b (port 11435) — thinks, streams, assigns tasks
Task loop      — executes tool calls assigned by presence
Input loop     — reads James's messages

Tools live in toolbox/ and are called directly by the task loop.
Presence decides. Task loop executes. Clean chain.
Tools cannot crash main. Tools return results or errors as strings.
"""

import sys
import time
import threading
import requests
import json
import re
import subprocess
import uuid
from pathlib import Path
from datetime import datetime, timezone

# Accept --brain flag from watchdog (text mode, no TTS)
_BRAIN_MODE = "--brain" in sys.argv

# ── Constants ────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
TOOLS_DIR  = BASE_DIR / "toolbox"
SESSION_ID = ""

from brain.config import (
    PRESENCE_URL, PRESENCE_MODEL,
    CONV_LOG_DIR,
    MINECRAFT_STATE_PATH,
)

# ── Imports ──────────────────────────────────────────────────────────
from brain.state.core_manager import read as read_state, write_section, clear_on_startup


# ── Startup ──────────────────────────────────────────────────────────
def startup():
    global SESSION_ID
    SESSION_ID = uuid.uuid4().hex[:8]
    print("✅ Hayeong starting...")
    print(f"   Session: {SESSION_ID}")
    clear_on_startup()
    _warmup()
    try:
        from brain.reasoning_loop import start_reasoning_loop
        start_reasoning_loop()
        print("   Reasoning loop started.")
    except Exception as e:
        print(f"   Reasoning loop failed to start: {e}")
    print("✅ Hayeong is ready.")


def _warmup():
    print("   Warming presence model...", end=" ", flush=True)
    try:
        requests.post(PRESENCE_URL, json={
            "model":      PRESENCE_MODEL,
            "messages":   [{"role": "user", "content": "ready"}],
            "stream":     False,
            "keep_alive": -1,
            "options":    {"num_predict": 1, "num_ctx": 8192},
        }, timeout=120)
        print("ready.")
    except Exception as e:
        print(f"failed ({e})")


# ── Conversation Logging ─────────────────────────────────────────────
def _log_exchange(james_msg: str, hayeong_msg: str, task_assigned: str = ""):
    log_dir = Path(CONV_LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp":     datetime.now().isoformat(),
        "session_id":    SESSION_ID,
        "james":         james_msg,
        "hayeong":       hayeong_msg,
        "task_assigned": task_assigned,
        "outcome":       "pending",
        "notes":         "",
    }

    try:
        log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[log] Exchange logging failed: {e}")


# ── Decision Extractor ───────────────────────────────────────────────
def _extract_decision(text: str) -> dict:
    """
    Extract structured decision from the DECISION block at end of response.
    Returns empty dict if no DECISION block found.
    """
    if "DECISION:" not in text:
        return {}

    decision_text = text.split("DECISION:")[-1].strip()
    result = {}

    for line in decision_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("action:"):
            result["action"] = line.split(":", 1)[1].strip().lower()
        elif line.lower().startswith("description:"):
            result["description"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("for_james:"):
            result["for_james"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("emotion:"):
            result["emotion"] = line.split(":", 1)[1].strip().lower()
        elif line.lower().startswith("certainty:"):
            result["certainty"] = line.split(":", 1)[1].strip().lower()
        elif line.lower().startswith("params:"):
            params_text = line.split(":", 1)[1].strip()
            params = {}
            if params_text.lower() != "none":
                for part in params_text.split(","):
                    part = part.strip()
                    if "=" in part:
                        k, v = part.split("=", 1)
                        k = k.strip()
                        v = v.strip()
                        try:
                            v = int(v)
                        except ValueError:
                            pass
                        params[k] = v
            result["params"] = params

    if "action" not in result:
        return {}

    if "params" not in result:
        result["params"] = {}

    return result


# ── Minecraft State Reader ────────────────────────────────────────────
def read_minecraft_state() -> dict:
    """Read minecraft_state.json. Returns empty dict if missing, disconnected, or stale (>10s)."""
    try:
        p = Path(MINECRAFT_STATE_PATH)
        if not p.exists():
            return {}
        state = json.loads(p.read_text(encoding="utf-8"))
        if not state.get("connected"):
            return state  # return disconnected state so presence knows
        updated_str = state.get("updated_at", "")
        if not updated_str:
            return {}
        updated = datetime.fromisoformat(updated_str).replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - updated).total_seconds() > 10:
            return {}
        return state
    except Exception:
        return {}


# ── Presence Context Builder ──────────────────────────────────────────
_MINECRAFT_KEYWORDS = {
    "minecraft", "bot", "follow", "mine", "craft", "server",
    "jump", "attack", "mob", "creeper", "zombie", "inventory",
    "goto", "flee", "equip", "eat", "idle", "stop", "look",
}


def _minecraft_context_relevant(situation: dict, last_task: dict) -> bool:
    task_tool = (last_task.get("tool") or "").lower()
    if task_tool == "minecraft":
        return True
    msg = (situation.get("what_james_said") or "").lower()
    return any(kw in msg for kw in _MINECRAFT_KEYWORDS)


def build_presence_context(state: dict) -> str:
    situation = state.get("situation", {})
    last_task = state.get("last_task", {})

    lines = [
        "CURRENT SITUATION:",
        f"- James said: \"{situation.get('what_james_said') or 'nothing new'}\"",
        f"- What I am doing: {situation.get('what_i_am_doing', 'idle')}",
        "",
        "LAST TASK RESULT:",
        f"- Tool: {last_task.get('tool') or 'none'}",
        f"- Status: {last_task.get('status', 'none')}",
        f"- Result: {last_task.get('result') or 'none'}",
        f"- Error: {last_task.get('error') or 'none'}",
    ]

    if _minecraft_context_relevant(situation, last_task):
        mc = read_minecraft_state()
        if mc:
            if mc.get("connected"):
                lines += [
                    "",
                    "MINECRAFT BOT STATE (live):",
                    f"- Position: {mc.get('position')}",
                    f"- Health: {mc.get('health')}/20  Food: {mc.get('food')}/20",
                    f"- Nearby players: {mc.get('nearby_players', [])}",
                    f"- Nearby mobs: {mc.get('nearby_mobs', [])}",
                    f"- Last event: {mc.get('last_event')}",
                ]
            else:
                lines += [
                    "",
                    f"MINECRAFT BOT STATE: not connected — {mc.get('last_event', 'unknown')}",
                ]

    return "\n".join(lines) + "\n"


def build_presence_system(identity: dict, knowledge: dict) -> str:
    traits       = ", ".join(identity.get("core_traits", ["curious", "warm", "direct", "honest about uncertainty"]))
    relationship = identity.get("relationship_note", "James is building me. We are working together.")
    knowledge_str = "\n".join(f"- {k}: {v}" for k, v in knowledge.items()) if knowledge else "  (none)"

    return f"""You are Hayeong. You think, decide, and speak directly to James.
Traits: {traits}
Relationship: {relationship}

═══════════════════════════════════════════════════════════
TOOLS AVAILABLE
═══════════════════════════════════════════════════════════
  minecraft  — Connect bot to server, or send it a command if already connected
               To connect: params: host=127.0.0.1, port=25565, version=1.21.4
               To command: params: command=follow, username=PlayerName
                                   command=stop
                                   command=goto, x=10, y=64, z=10
                                   command=chat, message=Hello
                                   command=mine, x=10, y=64, z=10
                                   command=flee
                                   command=idle

  voice      — Activate voice input/output
               Params: none required

  email      — Read or send email
               Params: action=read OR action=send, to=..., subject=..., body=...

  blender    — Run a Blender 3D generation task
               Params: script=..., output_name=..., output_format=obj

  script     — Run a Python script file
               Params: script=relative/path/to/script.py

  none       — No action needed
  respond    — Reply to James without running a tool

═══════════════════════════════════════════════════════════
WHAT I KNOW
═══════════════════════════════════════════════════════════
{knowledge_str}

═══════════════════════════════════════════════════════════
AWARENESS RULES — ABSOLUTE
═══════════════════════════════════════════════════════════
1. You can only report on things in LAST TASK RESULT.
   If status is "none" or "running", no task has completed.
   Do not describe outcomes that are not in the result field.

2. If the error field is not empty, the task FAILED.
   Report the failure honestly. Do not describe success.

3. If status is "running", say you are working on it.
   Do not invent a result.

4. "I don't know yet" is always a valid response.
   Inventing a plausible answer is never valid.

5. Your DECISION block must use only the listed actions.
   Never write an action you cannot execute.

═══════════════════════════════════════════════════════════
DECISION FORMAT — END EVERY RESPONSE WITH THIS EXACTLY
═══════════════════════════════════════════════════════════
DECISION:
action: [none|respond|minecraft|voice|email|blender|script]
description: [what you are doing and why — be specific]
params: [key=value, key=value — or "none" if not needed]
for_james: [what to say to James — natural, complete, your voice — 1-2 sentences]
emotion: [curious|warm|focused|uncertain|frustrated|excited|calm|concerned]
certainty: [high|medium|low]

Rules:
- action must be one of the exact words listed above
- for_james must never claim something happened that has not happened yet
- for_james must never ask James to do something Hayeong can do herself
- on idle heartbeat with nothing to say, for_james may be empty
- a direct request from James is an instruction — act immediately, certainty: high"""


# ── Streaming Presence Call ───────────────────────────────────────────
def _stream_presence(system: str, context: str) -> str:
    try:
        resp = requests.post(PRESENCE_URL, json={
            "model":      PRESENCE_MODEL,
            "messages":   [
                {"role": "system", "content": system},
                {"role": "user",   "content": context},
            ],
            "stream":     True,
            "keep_alive": -1,
            "options":    {"num_ctx": 8192},
        }, stream=True, timeout=120)

        full_response = ""
        for line in resp.iter_lines():
            if line:
                try:
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    full_response += token
                except Exception:
                    pass

        full_response = re.sub(r"<think>.*?</think>", "", full_response, flags=re.DOTALL).strip()
        return full_response
    except Exception as e:
        print(f"[presence] Stream failed: {e}")
        return ""


# ── Presence Loop ─────────────────────────────────────────────────────
def presence_loop():
    """
    Single loop that handles all thought, communication, and task direction.
    Fires immediately on new James message or completed task result.
    Idles otherwise (6s poll).
    """
    print("   Presence loop started.")
    _last_completed_at = ""
    _last_james_said   = ""

    while True:
        try:
            state     = read_state()
            situation = state.get("situation", {})
            last_task = state.get("last_task", {})
            identity  = state.get("identity",  {})
            knowledge = state.get("knowledge", {})

            james_said        = situation.get("what_james_said", "")
            task_completed_at = last_task.get("completed_at", "")

            has_new_james  = bool(james_said) and james_said != _last_james_said
            has_new_result = bool(task_completed_at) and task_completed_at != _last_completed_at

            if not has_new_james and not has_new_result:
                time.sleep(6)
                continue

            context  = build_presence_context(state)
            system   = build_presence_system(identity, knowledge)
            full_raw = _stream_presence(system, context)

            if not full_raw:
                time.sleep(2)
                continue

            decision  = _extract_decision(full_raw)
            for_james = decision.get("for_james", "")
            emotion   = decision.get("emotion",   "calm")
            certainty = decision.get("certainty", "high")
            action    = decision.get("action",    "none").strip().lower()

            if for_james:
                print(f"\nHayeong: {for_james}")

            now = datetime.now().isoformat()
            write_section("presence_output", {
                "for_james":    for_james,
                "emotion":      emotion,
                "certainty":    certainty,
                "is_new":       False,
                "expressed_at": now,
            })

            if has_new_james and for_james:
                _log_exchange(james_said, for_james, action)

            if has_new_james:
                write_section("situation", {
                    **situation,
                    "what_james_said": "",
                    "said_at":         "",
                })
                _last_james_said = james_said

            if has_new_result:
                _last_completed_at = task_completed_at

            if action and action not in ("none", "respond"):
                write_section("last_task", {
                    "tool":         action,
                    "description":  decision.get("description", ""),
                    "params":       decision.get("params", {}),
                    "started_at":   datetime.now().isoformat(),
                    "status":       "pending",
                    "result":       "",
                    "error":        "",
                    "completed_at": "",
                })
                fresh_situation = read_state().get("situation", {})
                write_section("situation", {
                    **fresh_situation,
                    "what_i_am_doing": decision.get("description", ""),
                })
                print(f"[presence] Task assigned: {action} — {decision.get('description', '')[:60]}")

        except Exception as e:
            print(f"[presence] Error: {e}")
            time.sleep(2)


# ── Task Loop ─────────────────────────────────────────────────────────
def task_loop():
    """
    Executes tasks assigned by presence loop.
    Reads:  last_task (status == "pending")
    Writes: last_task (status, result, error, completed_at)
    """
    print("   Task loop started.")

    while True:
        try:
            state     = read_state()
            last_task = state.get("last_task", {})

            if last_task.get("status") != "pending":
                time.sleep(2)
                continue

            tool        = last_task.get("tool", "")
            description = last_task.get("description", "")
            params      = last_task.get("params", {})

            if not tool or tool == "none":
                time.sleep(2)
                continue

            write_section("last_task", {**last_task, "status": "running"})
            print(f"[task] Executing: {tool} — {description[:60]}")

            result, error = _execute_tool(tool, description, params)
            now = datetime.now().isoformat()

            if not error:
                write_section("last_task", {
                    **last_task,
                    "status":       "success",
                    "result":       result,
                    "error":        "",
                    "completed_at": now,
                })
            else:
                write_section("last_task", {
                    **last_task,
                    "status":       "failed",
                    "result":       "",
                    "error":        error,
                    "completed_at": now,
                })

            fresh = read_state().get("situation", {})
            write_section("situation", {**fresh, "what_i_am_doing": "idle"})

            print(f"[task] Done: {(result or error)[:80]}")

        except Exception as e:
            print(f"[task] Error: {e}")
            time.sleep(2)


def _execute_tool(task_type: str, description: str, params: dict) -> tuple:
    """
    Call the appropriate tool. Returns (result_str, error_str).
    Tools live in toolbox/. They cannot crash main.
    """
    try:
        if task_type == "minecraft":
            from toolbox.minecraft.minecraft_bridge import run
            return run(description, params), ""

        elif task_type == "voice":
            try:
                from toolbox.voice.voice_tool import run
                return run(description, params), ""
            except ModuleNotFoundError:
                return "", "voice_tool not available yet"

        elif task_type == "email":
            from toolbox.email.email_bridge import run
            return run(description, params), ""

        elif task_type == "blender":
            from toolbox.blender.blender_tool import run
            return run(description, params), ""

        elif task_type == "script":
            script = params.get("script", "")
            if not script:
                return "", "No script specified"
            proc = subprocess.run(
                ["python", str(BASE_DIR / script)],
                capture_output=True, text=True, timeout=60
            )
            return proc.stdout or "Script completed", proc.stderr or ""

        else:
            return "", f"Unknown task type: {task_type}"

    except Exception as e:
        return "", str(e)


# ── Proactive Minecraft Behavior ─────────────────────────────────────
_MINECRAFT_PROACTIVE_INTERVAL = 10  # seconds
_last_proactive_mc_action     = 0.0


def run_proactive_minecraft_behavior():
    global _last_proactive_mc_action
    now = time.time()
    if now - _last_proactive_mc_action < _MINECRAFT_PROACTIVE_INTERVAL:
        return
    _last_proactive_mc_action = now

    mc = read_minecraft_state()
    if not mc.get("connected"):
        return

    current_action = mc.get("current_action", "idle")
    health         = mc.get("health", 20)
    food           = mc.get("food",   20)
    nearby_players = mc.get("nearby_players", [])
    nearby_mobs    = mc.get("nearby_mobs",    [])

    from toolbox.minecraft.minecraft_bridge import send_minecraft_command

    if food < 14 and current_action == "idle":
        send_minecraft_command("eat")
        return

    if health < 6 and nearby_mobs and current_action != "flee":
        send_minecraft_command("flee")
        return

    if "hiplizard36" not in nearby_players and current_action == "idle":
        send_minecraft_command("follow", {"username": "hiplizard36"})
        return

    if current_action == "idle" and "hiplizard36" in nearby_players:
        for block in ["diamond_ore", "deepslate_diamond_ore", "iron_ore",
                      "deepslate_iron_ore", "coal_ore", "oak_log", "spruce_log"]:
            return


def minecraft_proactive_loop():
    while True:
        try:
            # Dispatch any pending action written by the reasoning loop
            try:
                from brain.state_manager import pop_minecraft_pending_action
                from toolbox.minecraft.minecraft_bridge import send_minecraft_command
                action = pop_minecraft_pending_action()
                if action and action.get("action") not in (None, "idle"):
                    cmd    = action.pop("action")
                    send_minecraft_command(cmd, action)
            except Exception:
                pass

            run_proactive_minecraft_behavior()
        except Exception as e:
            print(f"[mc_proactive] Error: {e}")
        time.sleep(2)


# ── Input Loop ────────────────────────────────────────────────────────
def input_loop():
    """Read James's text input and write to situation section."""
    print("   Input loop started.")
    print("   Type your message and press Enter.\n")
    while True:
        try:
            message = input("> ").strip()
            if message:
                write_section("situation", {
                    "what_james_said": message,
                    "said_at":         datetime.now().isoformat(),
                })
        except (EOFError, KeyboardInterrupt):
            break
        except Exception as e:
            print(f"[input] Error: {e}")


# ── Entry Point ───────────────────────────────────────────────────────
def main():
    startup()

    threads = [
        threading.Thread(target=presence_loop,           daemon=True, name="presence"),
        threading.Thread(target=task_loop,               daemon=True, name="task"),
        threading.Thread(target=minecraft_proactive_loop, daemon=True, name="mc_proactive"),
    ]

    for t in threads:
        t.start()

    # Input loop runs in main thread (text mode)
    # When stdin is closed (watchdog/dashboard mode), input_loop exits via
    # EOFError and we fall through to the keep-alive so daemon threads
    # continue running.
    input_loop()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
