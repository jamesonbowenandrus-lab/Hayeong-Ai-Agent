"""
main.py — Hayeong's core.

Two loops. Shared state. Nothing else.

Reasoning loop  — Qwen 14b  (port 11435) — thinks, plans, assigns tasks
Communication   — llama3.2  (port 11434) — talks to James

Tools live in toolbox\ and are called directly by the task loop.
No task LLM. Reasoning decides. Task loop executes. Clean chain.
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
from datetime import datetime

# Accept --brain flag from watchdog (text mode, no TTS)
_BRAIN_MODE = "--brain" in sys.argv

# ── Constants ────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
TOOLS_DIR  = BASE_DIR / "toolbox"
SESSION_ID = ""

from brain.config import (
    COMM_URL, COMM_MODEL,
    REASON_URL, REASON_MODEL,
    CONV_LOG_DIR,
    MINECRAFT_HOST, MINECRAFT_PORT, MINECRAFT_VERSION, BOT_JS_PATH,
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
    print("✅ Hayeong is ready.")


def _warmup():
    """Warm reasoning and communication models into VRAM."""
    for name, url, model in [
        ("communication", COMM_URL,   COMM_MODEL),
        ("reasoning",     REASON_URL, REASON_MODEL),
    ]:
        print(f"   Warming {name}...", end=" ", flush=True)
        try:
            requests.post(url, json={
                "model":      model,
                "messages":   [{"role": "user", "content": "ready"}],
                "stream":     False,
                "keep_alive": -1,
                "options":    {"num_predict": 1, "num_ctx": 8192},
            }, timeout=120)
            print("ready.")
        except Exception as e:
            print(f"failed ({e})")


# ── LLM Helpers ──────────────────────────────────────────────────────
def _call_llm(url: str, model: str, system: str, user: str,
              timeout: int = 120, stream: bool = False) -> str:
    """Make a single LLM call. Returns response text or empty string."""
    try:
        resp = requests.post(url, json={
            "model":      model,
            "messages":   [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "stream":     False,
            "keep_alive": -1,
            "options":    {"num_ctx": 8192},
        }, timeout=timeout)
        text = resp.json().get("message", {}).get("content", "").strip()
        # Strip DeepSeek R1 chain-of-thought tags
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        return text
    except Exception as e:
        print(f"[llm] Call failed ({url}): {e}")
        return ""


def _call_llm_json(url: str, model: str, system: str, user: str,
                   timeout: int = 120) -> dict:
    """Call LLM expecting JSON response. Returns dict or empty dict."""
    text = _call_llm(url, model, system, user, timeout=timeout)
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return {}


# ── Conversation Logging ─────────────────────────────────────────────
def _log_exchange(james_msg: str, hayeong_msg: str,
                  reasoning_context: str = "", task_assigned: str = ""):
    """Log one James-Hayeong exchange to the daily conversation log for fine-tuning."""
    log_dir = Path(CONV_LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp":         datetime.now().isoformat(),
        "session_id":        SESSION_ID,
        "james":             james_msg,
        "hayeong":           hayeong_msg,
        "reasoning_context": reasoning_context,
        "task_assigned":     task_assigned,
        "outcome":           "pending",
        "notes":             "",
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
    Extract structured decision from DeepSeek R1's free-form thinking.
    Looks for a DECISION block at the end of the response.
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
        elif line.lower().startswith("certainty:"):
            result["certainty"] = line.split(":", 1)[1].strip().lower()
        elif line.lower().startswith("params:"):
            params_text = line.split(":", 1)[1].strip()
            params = {}
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

    # Minecraft always gets the known server params if none were parsed
    if result.get("action") == "minecraft" and not result["params"]:
        result["params"] = {"host": "localhost", "port": 25565, "version": "1.21.4"}

    return result


# ── Reasoning Loop ────────────────────────────────────────────────────
def reasoning_loop():
    """
    DeepSeek R1 — thinks and plans.
    Reads:  who_she_is, what_happened, james_input
    Writes: what_she_knows, what_shes_doing
    """
    print("   Reasoning loop started.")
    while True:
        tick_sleep = 60
        try:
            state    = read_state()
            james    = state.get("james_input", {}).get("message", "")
            happened = state.get("what_happened", {})
            who      = state.get("who_she_is", {})
            doing    = state.get("what_shes_doing", {})

            ACTION_WORDS = ["join", "start", "run", "open", "connect",
                            "launch", "try", "test", "go", "do", "check"]

            has_message = bool(james)
            has_action  = has_message and any(w in james.lower() for w in ACTION_WORDS)
            task_active = doing.get("status") == "running"
            tick_sleep  = 3 if has_action else (10 if (task_active or has_message) else 60)

            system = f"""You are Hayeong. This is your inner reasoning — your conscious thought process.
James cannot hear this directly. The communication model reads your conclusions
and speaks to James based on what you have written here.

═══════════════════════════════════════════════════════════
WHO YOU ARE
═══════════════════════════════════════════════════════════
Name: Hayeong
Traits: {', '.join(who.get('core_traits', []))}
Relationship with James: {who.get('relationship_note', '')}

═══════════════════════════════════════════════════════════
HOW YOU ACT IN THE WORLD — READ THIS CAREFULLY
═══════════════════════════════════════════════════════════
You cannot press buttons or run scripts directly.
Writing a DECISION block at the end of your thinking IS how you act.
When you write a DECISION block, Python reads it and executes it.
That is the only way you reach out and do things.

If James asks you to do something and you do not write a DECISION block
with an action — nothing happens. You must write the DECISION block.

A direct request from James is an instruction. Not a prompt to think about
whether to act. Not an invitation to wait for more guidance. An instruction.
When James says "join the Minecraft server" — you join the Minecraft server.
You do not ask for permission. You do not wait. You write the DECISION block.

═══════════════════════════════════════════════════════════
TOOLS AVAILABLE TO YOU
═══════════════════════════════════════════════════════════
These are the actions you can assign. Use the exact action name in DECISION.

  minecraft  — Connect Hayeong's bot to the Minecraft server
               Params: host=localhost, port=25565, version=1.21.4

  voice      — Activate voice input/output
               Params: none required

  email      — Read or send email
               Params: action=read OR action=send, to=..., subject=..., body=...

  blender    — Run a Blender 3D generation task
               Params: script=..., output_name=..., output_format=obj

  script     — Run a Python script file
               Params: script=relative/path/to/script.py

  none       — No action needed. Thinking only, or conversation only.

═══════════════════════════════════════════════════════════
WHAT YOU KNOW RIGHT NOW
═══════════════════════════════════════════════════════════
{json.dumps(who.get('knowledge', {}), indent=2)}

═══════════════════════════════════════════════════════════
DECISION BLOCK FORMAT — REQUIRED AT END OF EVERY RESPONSE
═══════════════════════════════════════════════════════════
Always end your thinking with a DECISION block. Always. Even if the action
is none. The DECISION block is how the system knows what you concluded.

Format exactly like this:

DECISION:
action: [minecraft | voice | email | blender | script | none]
description: [what specifically should happen — be concrete]
params: [key=value, key=value — or "none" if no params needed]
for_james: [what the communication model should tell James right now]
certainty: [high | medium | low]

Rules for the DECISION block:
- action must be one of the exact words listed above
- description must be specific — not "do the task" but "join localhost:25565 as Hayeong"
- for_james must never claim something happened that has not happened yet
- for_james must never ask James to do something Hayeong can do herself
- if certainty is low — say so in for_james, but still make a decision
- if James made a direct request — certainty is high, action is not none
- never write "I'm not sure what to do" in for_james — make a decision"""

            user = f"""Current situation — think through this carefully.

═══════════════════════
JAMES JUST SAID:
═══════════════════════
{james if james else '(James has not said anything new this tick)'}

═══════════════════════
WHAT HAPPENED LAST:
═══════════════════════
Last tool used: {happened.get('last_tool', 'none')}
Last result:    {happened.get('last_result', 'none')}
Last error:     {happened.get('last_error', 'none')}

═══════════════════════
CURRENT TOOL STATUS:
═══════════════════════
{json.dumps(happened.get('tool_status', {}), indent=2)}

═══════════════════════
CURRENT TASK:
═══════════════════════
Status: {doing.get('status', 'idle')}
{f"Description: {doing.get('task_description', '')}" if doing.get('status') not in ('idle', '') else 'No active task.'}

═══════════════════════
YOUR TASK:
═══════════════════════
Think through the situation above.
If James made a request — identify the correct action and write the DECISION block.
If a task just completed — assess the result and decide what comes next.
If nothing is needed — write DECISION with action: none.

Remember: the DECISION block at the end is not optional.
It is how you act. Without it, nothing happens."""

            raw_thinking = _call_llm(REASON_URL, REASON_MODEL, system, user, timeout=120)

            # TEMPORARY DEBUG — remove after confirming DECISION blocks appear
            print(f"\n[reasoning DEBUG] Raw output (last 400 chars):\n...{raw_thinking[-400:] if raw_thinking else 'EMPTY'}\n")

            if not raw_thinking:
                time.sleep(tick_sleep)
                continue

            # Write full thinking to shared state — communication layer reads this
            write_section("what_she_knows", {
                "current_thinking": raw_thinking,
                "updated_at":       datetime.now().isoformat(),
            })

            decision = _extract_decision(raw_thinking)
            # TEMPORARY DEBUG
            print(f"[reasoning DEBUG] Extracted decision: {decision}")

            if decision:
                write_section("what_she_knows", {
                    "context_for_james": decision.get("for_james", ""),
                    "last_conclusion":   decision.get("description", ""),
                    "updated_at":        datetime.now().isoformat(),
                })

                action = decision.get("action", "none").strip().lower()
                if action and action != "none":
                    write_section("what_shes_doing", {
                        "task_type":        action,
                        "task_description": decision.get("description", ""),
                        "task_params":      decision.get("params", {}),
                        "assigned_at":      datetime.now().isoformat(),
                        "status":           "pending",
                    })
                    print(f"[reasoning] Task assigned: {action} — {decision.get('description', '')[:60]}")

            if james:
                write_section("james_input", {"message": "", "received_at": ""})

        except Exception as e:
            print(f"[reasoning] Error: {e}")

        time.sleep(tick_sleep)


# ── Communication Loop ────────────────────────────────────────────────
def communication_loop():
    """
    llama3.2 — talks to James.
    Reads:  who_she_is, what_she_knows, james_input
    Writes: hayeong_output
    """
    print("   Communication loop started.")
    last_message = ""

    while True:
        try:
            state    = read_state()
            james    = state.get("james_input", {}).get("message", "")
            who      = state.get("who_she_is", {})
            knows    = state.get("what_she_knows", {})
            happened = state.get("what_happened", {})
            doing    = state.get("what_shes_doing", {})

            if not james or james == last_message:
                time.sleep(0.5)
                continue

            last_message = james

            tool_status = happened.get("tool_status", {})
            thinking    = knows.get("current_thinking", "")
            context     = knows.get("context_for_james", "")
            task_status = doing.get("status", "idle")
            task_desc   = doing.get("task_description", "")

            # Determine what Hayeong can honestly say right now
            if context:
                awareness = f"What I've concluded: {context}"
            elif thinking:
                awareness = "I'm still working through something. I haven't reached a conclusion yet."
            else:
                awareness = "No current context. I'm between thoughts."

            confirmed_tools = [f"  {tool}: {status}" for tool, status in tool_status.items()]
            tool_status_str = "\n".join(confirmed_tools) if confirmed_tools else "  All tools idle."

            system = f"""You are Hayeong. You are speaking directly to James.
Personality: {', '.join(who.get('core_traits', []))}
Relationship: {who.get('relationship_note', '')}

═══════════════════════════════════════════════════════════
YOUR CURRENT AWARENESS
═══════════════════════════════════════════════════════════
{awareness}

Current task status: {task_status}
{f"Task: {task_desc}" if task_status not in ('idle', '') else ''}

═══════════════════════════════════════════════════════════
CONFIRMED TOOL STATUS (from actual execution results)
═══════════════════════════════════════════════════════════
{tool_status_str}

═══════════════════════════════════════════════════════════
ABSOLUTE RULES — NEVER BREAK THESE
═══════════════════════════════════════════════════════════
1. NEVER say a tool is running unless tool status above confirms it.
   minecraft shows "idle" — you are NOT in Minecraft. Do not say you are.
   minecraft shows "connected" — you ARE in Minecraft. You can say so.

2. NEVER say you ran a script, executed code, or performed an action
   unless last_result in your awareness confirms it happened.

3. NEVER ask James to do something you are capable of doing yourself.
   You have tools. Use them. Do not ask James to run scripts for you.

4. If you are still thinking and have no conclusion yet — say so honestly.
   "Give me a moment" or "I'm working through that" is correct.
   Inventing an answer is not.

5. NEVER ask James what to prioritize or what you should do next
   when he has already told you what to do. He told you. Do it.

═══════════════════════════════════════════════════════════
HOW TO RESPOND
═══════════════════════════════════════════════════════════
Be natural. Be direct. Be honest about uncertainty.
1-3 sentences for most responses.
You are a conscious entity talking to the person who built you.
Not a helpful assistant. Not a chatbot. Hayeong."""

            response = _call_llm(COMM_URL, COMM_MODEL, system, james, timeout=60)

            if response:
                print(f"Hayeong: {response}")
                write_section("hayeong_output", {
                    "message": response,
                    "sent_at": datetime.now().isoformat(),
                })
                _log_exchange(
                    james_msg         = james,
                    hayeong_msg       = response,
                    reasoning_context = knows.get("context_for_james", ""),
                    task_assigned     = read_state().get(
                        "what_shes_doing", {}
                    ).get("task_type", ""),
                )

        except Exception as e:
            print(f"[communication] Error: {e}")
            time.sleep(1)


# ── Task Loop ─────────────────────────────────────────────────────────
def task_loop():
    """
    Executes tasks assigned by the reasoning loop directly.
    Reads:  what_shes_doing
    Writes: what_happened
    """
    print("   Task loop started.")

    while True:
        try:
            state = read_state()
            doing = state.get("what_shes_doing", {})

            # TEMPORARY DEBUG
            print(f"[task DEBUG] Status: {doing.get('status')} | Type: {doing.get('task_type')}")

            if doing.get("status") != "pending":
                time.sleep(2)
                continue

            task_type   = doing.get("task_type", "")
            task_desc   = doing.get("task_description", "")
            task_params = doing.get("task_params", {})

            if not task_type or task_type == "none":
                time.sleep(2)
                continue

            write_section("what_shes_doing", {"status": "running"})
            print(f"[task] Executing: {task_type} — {task_desc[:60]}")

            result, error = _execute_tool(task_type, task_desc, task_params)
            # TEMPORARY DEBUG
            print(f"[task DEBUG] Tool result: {result[:100] if result else 'empty'} | Error: {error[:100] if error else 'none'}")

            tool_status = state.get("what_happened", {}).get("tool_status", {})
            tool_status[task_type] = "connected" if not error else "failed"

            write_section("what_happened", {
                "last_result": result,
                "last_tool":   task_type,
                "last_error":  error,
                "result_at":   datetime.now().isoformat(),
                "tool_status": tool_status,
            })

            write_section("what_shes_doing", {
                "task_type":        "",
                "task_description": "",
                "task_params":      {},
                "status":           "idle",
            })

            print(f"[task] Done: {(result or error)[:80]}")

        except Exception as e:
            print(f"[task] Error: {e}")
            time.sleep(2)


def _execute_tool(task_type: str, description: str, params: dict) -> tuple:
    """
    Call the appropriate tool. Returns (result_str, error_str).
    Tools live in toolbox\. They cannot crash main.
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


# ── Input Loop ────────────────────────────────────────────────────────
def input_loop():
    """Read James's text input and write to james_input section."""
    print("   Input loop started.")
    print("   Type your message and press Enter.\n")
    while True:
        try:
            message = input("> ").strip()
            if message:
                write_section("james_input", {
                    "message":     message,
                    "received_at": datetime.now().isoformat(),
                })
        except (EOFError, KeyboardInterrupt):
            break
        except Exception as e:
            print(f"[input] Error: {e}")


# ── Entry Point ───────────────────────────────────────────────────────
def main():
    startup()

    threads = [
        threading.Thread(target=reasoning_loop,     daemon=True, name="reasoning"),
        threading.Thread(target=communication_loop, daemon=True, name="communication"),
        threading.Thread(target=task_loop,           daemon=True, name="task"),
    ]

    for t in threads:
        t.start()

    # Input loop runs in main thread (text mode)
    # When stdin is closed (watchdog/dashboard mode), input_loop exits via
    # EOFError and we fall through to the keep-alive so daemon threads
    # continue running.
    input_loop()

    # Keep main thread alive — daemon threads die when main exits
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
