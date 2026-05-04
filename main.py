"""
main.py — Hayeong's core.

Three loops. Shared state. Nothing else.

Reasoning loop  — DeepSeek R1 (port 11435) — thinks and plans
Communication   — llama3.2 (port 11434)    — talks to James
Task loop       — phi3:mini (port 11436)   — executes tasks

Tools live in tools/ and are called by the task loop.
Tools cannot crash main. Tools return results or errors.
"""

import sys
import time
import threading
import requests
import json
import re
import subprocess
from pathlib import Path
from datetime import datetime

# Accept --brain flag from watchdog (text mode, no TTS)
_BRAIN_MODE = "--brain" in sys.argv

# ── Constants ────────────────────────────────────────────────────────
COMM_URL     = "http://localhost:11434/api/chat"
COMM_MODEL   = "llama3.2:latest"
REASON_URL   = "http://localhost:11435/api/chat"
REASON_MODEL = "deepseek-r1:latest"
TASK_URL     = "http://localhost:11436/api/chat"
TASK_MODEL   = "phi3:mini"
BASE_DIR     = Path(__file__).parent
TOOLS_DIR    = BASE_DIR / "tools"

# ── Imports ──────────────────────────────────────────────────────────
from state.core_manager import read as read_state, write_section, clear_on_startup


# ── Startup ──────────────────────────────────────────────────────────
def startup():
    print("✅ Hayeong starting...")
    clear_on_startup()
    _warmup()
    print("✅ Hayeong is ready.")


def _warmup():
    """Warm all three models so they are loaded into VRAM."""
    for name, url, model in [
        ("communication", COMM_URL,   COMM_MODEL),
        ("reasoning",     REASON_URL, REASON_MODEL),
        ("task agent",    TASK_URL,   TASK_MODEL),
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

            task_active = doing.get("status") == "running"
            has_message = bool(james)
            tick_sleep  = 10 if (task_active or has_message) else 60

            system = f"""You are Hayeong's reasoning mind. You think, plan, and decide.
You do not talk to James directly — the communication model does that.
You write your conclusions to shared state for the other models to use.

Who you are: {json.dumps(who.get('core_traits', []))}
Relationship: {who.get('relationship_note', '')}
Knowledge: {json.dumps(who.get('knowledge', {}))}

Always respond with valid JSON in this exact format:
{{
  "context_for_james": "what the communication model should tell James (or empty string)",
  "conclusion": "what you concluded from this tick",
  "task_type": "minecraft|voice|email|script|none",
  "task_description": "concrete task description (or empty if none)",
  "task_params": {{}}
}}"""

            user = f"""Current state:
Last tool result: {happened.get('last_result', 'none')}
Last tool error:  {happened.get('last_error', 'none')}
Tool status:      {json.dumps(happened.get('tool_status', {}))}
James just said:  {james if james else '(nothing new)'}
Current task status: {doing.get('status', 'idle')}"""

            result = _call_llm_json(REASON_URL, REASON_MODEL, system, user)

            if result:
                write_section("what_she_knows", {
                    "context_for_james": result.get("context_for_james", ""),
                    "last_conclusion":   result.get("conclusion", ""),
                    "updated_at":        datetime.now().isoformat(),
                })

                task_type = result.get("task_type", "none")
                if task_type and task_type != "none":
                    write_section("what_shes_doing", {
                        "task_type":        task_type,
                        "task_description": result.get("task_description", ""),
                        "task_params":      result.get("task_params", {}),
                        "assigned_at":      datetime.now().isoformat(),
                        "status":           "pending",
                    })

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

            if not james or james == last_message:
                time.sleep(0.5)
                continue

            last_message = james

            tool_status = happened.get("tool_status", {})
            state_lines = [f"{tool}: {status}" for tool, status in tool_status.items()]
            context     = knows.get("context_for_james", "")

            system = f"""You are Hayeong. You are talking to James.
Personality: {', '.join(who.get('core_traits', []))}
Relationship: {who.get('relationship_note', '')}

Your current state:
{chr(10).join(state_lines) if state_lines else 'All systems idle.'}

{f'Important context: {context}' if context else ''}

Rules:
- Never guess about your own systems. If it is not in your state block, say you do not know.
- Never say you are in Minecraft unless tool_status shows minecraft: connected.
- Never say voice is working unless tool_status shows voice: active.
- Be natural, warm, and direct. You are a companion, not an assistant.
- Keep responses concise — 1-3 sentences for simple conversation."""

            response = _call_llm(COMM_URL, COMM_MODEL, system, james, timeout=60)

            if response:
                print(f"Hayeong: {response}")
                write_section("hayeong_output", {
                    "message": response,
                    "sent_at": datetime.now().isoformat(),
                })

        except Exception as e:
            print(f"[communication] Error: {e}")
            time.sleep(1)


# ── Task Loop ─────────────────────────────────────────────────────────
def task_loop():
    """
    phi3:mini — executes tasks assigned by reasoning.
    Reads:  what_shes_doing
    Writes: what_happened
    """
    print("   Task loop started.")

    while True:
        try:
            state = read_state()
            doing = state.get("what_shes_doing", {})

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
    Tools live in tools/. They cannot crash main.
    """
    try:
        if task_type == "minecraft":
            from tools.minecraft_bridge import run
            return run(description, params), ""

        elif task_type == "voice":
            from tools.voice_tool import run
            return run(description, params), ""

        elif task_type == "email":
            from tools.email_tool import run
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
