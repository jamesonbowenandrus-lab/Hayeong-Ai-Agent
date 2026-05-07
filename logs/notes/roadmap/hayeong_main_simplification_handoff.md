# HANDOFF NOTE — Simplify main.py to Match Core Architecture Spec
*For Claude Code. This is a significant restructure of main.py.*
*Read the entire note and the architecture spec before writing any code.*
*The spec is in: hayeong_core_architecture_spec.md*

---

## What This Is

main.py has accumulated too many responsibilities over time. It currently
manages email connections, audit logs, income tracking, health monitoring,
capability loading, context verification, intent routing, and more — all
in addition to its actual job of running Hayeong.

This handoff strips main.py back to exactly what the spec says it should
contain: three clean loops, shared state, and nothing else.

---

## The Target — What main.py Should Look Like After

```python
"""
main.py — Hayeong's core.

Three loops. Shared state. Nothing else.

Reasoning loop  — DeepSeek R1 (port 11435) — thinks and plans
Communication   — llama3.2 (port 11434)    — talks to James
Task loop       — phi3:mini (port 11436)    — executes tasks

Tools live in tools/ and are called by the task loop.
Tools cannot crash main. Tools return results or errors.
"""
```

The docstring describes the entire file. If something isn't in the
docstring, it probably doesn't belong in main.py.

---

## New Shared State File

Create `state/core.json` with this exact structure:

```json
{
  "who_she_is": {
    "name": "Hayeong",
    "mood": "present",
    "energy": 5,
    "relationship_note": "James is building me. We are working together.",
    "core_traits": ["curious", "warm", "direct", "honest about uncertainty"],
    "knowledge": {
      "workstation_fund": "James has a goal of saving $3000 for a workstation upgrade. Current balance $0. Hayeong is aware of this and can reference it when relevant.",
      "minecraft_server": "Local server on localhost:25565, version 1.21.4, offline mode.",
      "voice_setup": "HyperX QuadCast S on device index 4. SteelSeries Sonar Gaming on device index 6."
    }
  },
  "what_she_knows": {
    "context_for_james": "",
    "last_conclusion": "",
    "current_focus": "",
    "updated_at": ""
  },
  "what_shes_doing": {
    "task_type": "",
    "task_description": "",
    "task_params": {},
    "assigned_at": "",
    "status": "idle"
  },
  "what_happened": {
    "last_result": "",
    "last_tool": "",
    "last_error": "",
    "result_at": "",
    "tool_status": {
      "minecraft": "idle",
      "voice": "idle",
      "email": "idle"
    }
  },
  "james_input": {
    "message": "",
    "received_at": ""
  },
  "hayeong_output": {
    "message": "",
    "sent_at": ""
  }
}
```

Create `state/core_manager.py` — a simple helper for reading and writing
sections of core.json:

```python
"""
core_manager.py — Read and write sections of state/core.json
Simple. No abstractions. Just file read/write with a lock.
"""

import json
import threading
from pathlib import Path
from datetime import datetime

CORE_FILE = Path(__file__).parent / "core.json"
_lock = threading.Lock()


def read() -> dict:
    with _lock:
        try:
            return json.loads(CORE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}


def write_section(section: str, data: dict):
    with _lock:
        try:
            state = json.loads(CORE_FILE.read_text(encoding="utf-8"))
            state[section].update(data)
            CORE_FILE.write_text(
                json.dumps(state, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"[core_manager] Write failed: {e}")


def clear_on_startup():
    """Clear volatile sections for a clean session."""
    write_section("what_she_knows", {
        "context_for_james": "",
        "last_conclusion": "",
        "current_focus": "",
        "updated_at": "",
    })
    write_section("what_shes_doing", {
        "task_type": "",
        "task_description": "",
        "task_params": {},
        "assigned_at": "",
        "status": "idle",
    })
    write_section("what_happened", {
        "last_result": "",
        "last_tool": "",
        "last_error": "",
        "result_at": "",
        "tool_status": {"minecraft": "idle", "voice": "idle", "email": "idle"},
    })
    write_section("james_input", {"message": "", "received_at": ""})
    write_section("hayeong_output", {"message": "", "sent_at": ""})
```

---

## New main.py Structure

Write main.py with exactly this structure. Keep it under 300 lines.

```python
"""
main.py — Hayeong's core.
Three loops. Shared state. Nothing else.
"""

import sys
import time
import threading
import requests
import json
from pathlib import Path
from datetime import datetime

# ── Constants ──────────────────────────────────────────────────────
COMM_URL      = "http://localhost:11434/api/chat"
COMM_MODEL    = "llama3.2:latest"
REASON_URL    = "http://localhost:11435/api/chat"
REASON_MODEL  = "deepseek-r1:latest"
TASK_URL      = "http://localhost:11436/api/chat"
TASK_MODEL    = "phi3:mini"
BASE_DIR      = Path(__file__).parent
TOOLS_DIR     = BASE_DIR / "tools"

# ── Imports ────────────────────────────────────────────────────────
from state.core_manager import read as read_state, write_section, clear_on_startup

# ── Startup ────────────────────────────────────────────────────────
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

# ── Helpers ────────────────────────────────────────────────────────
def _call_llm(url: str, model: str, system: str, user: str,
              timeout: int = 120, stream: bool = False) -> str:
    """Make a single LLM call. Returns response text or empty string."""
    import re
    try:
        resp = requests.post(url, json={
            "model":      model,
            "messages":   [
                {"role": "system",  "content": system},
                {"role": "user",    "content": user},
            ],
            "stream":     stream,
            "keep_alive": -1,
            "options":    {"num_ctx": 8192},
        }, timeout=timeout)
        text = resp.json().get("message", {}).get("content", "").strip()
        # Strip DeepSeek R1 chain-of-thought tags
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
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
        # Try to extract JSON from text
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return {}

# ── Reasoning Loop ─────────────────────────────────────────────────
def reasoning_loop():
    """
    DeepSeek R1 — thinks and plans.
    Reads: who_she_is, what_happened, james_input
    Writes: what_she_knows, what_shes_doing
    """
    print("   Reasoning loop started.")
    while True:
        try:
            state   = read_state()
            james   = state.get("james_input", {}).get("message", "")
            happened = state.get("what_happened", {})
            who     = state.get("who_she_is", {})
            doing   = state.get("what_shes_doing", {})

            # Determine tick speed
            task_active = doing.get("status") == "running"
            has_message = bool(james)
            tick_sleep  = 10 if (task_active or has_message) else 60

            # Build reasoning prompt
            system = f"""You are Hayeong's reasoning mind. You think, plan, and decide.
You do not talk to James directly — the communication model does that.
You write your conclusions to shared state for the other models to use.

Who you are: {json.dumps(who.get('core_traits', []))}
Relationship: {who.get('relationship_note', '')}
Knowledge: {json.dumps(who.get('knowledge', {}))}

Always respond with JSON in this exact format:
{{
  "context_for_james": "what the communication model should tell James (or empty)",
  "conclusion": "what you concluded from this tick",
  "task_type": "minecraft|voice|email|script|none",
  "task_description": "concrete task description (or empty if none)",
  "task_params": {{}}
}}"""

            user = f"""Current state:
Last tool result: {happened.get('last_result', 'none')}
Last tool error: {happened.get('last_error', 'none')}
Tool status: {json.dumps(happened.get('tool_status', {}))}
James just said: {james if james else '(nothing new)'}
Current task status: {doing.get('status', 'idle')}"""

            result = _call_llm_json(REASON_URL, REASON_MODEL, system, user)

            if result:
                write_section("what_she_knows", {
                    "context_for_james": result.get("context_for_james", ""),
                    "last_conclusion":   result.get("conclusion", ""),
                    "updated_at":        datetime.now().isoformat(),
                })

                # Assign task if reasoning decided one is needed
                task_type = result.get("task_type", "none")
                if task_type and task_type != "none":
                    write_section("what_shes_doing", {
                        "task_type":        task_type,
                        "task_description": result.get("task_description", ""),
                        "task_params":      result.get("task_params", {}),
                        "assigned_at":      datetime.now().isoformat(),
                        "status":           "pending",
                    })

                # Clear james_input after processing
                if james:
                    write_section("james_input", {"message": "", "received_at": ""})

        except Exception as e:
            print(f"[reasoning] Error: {e}")

        time.sleep(tick_sleep)

# ── Communication Loop ─────────────────────────────────────────────
def communication_loop():
    """
    llama3.2 — talks to James.
    Reads: who_she_is, what_she_knows, james_input
    Writes: hayeong_output, james_input (incoming messages)
    """
    print("   Communication loop started.")
    last_message = ""

    while True:
        try:
            state   = read_state()
            james   = state.get("james_input", {}).get("message", "")
            who     = state.get("who_she_is", {})
            knows   = state.get("what_she_knows", {})
            happened = state.get("what_happened", {})

            if not james or james == last_message:
                time.sleep(0.5)
                continue

            last_message = james

            # Build voice/system state block
            tool_status = happened.get("tool_status", {})
            state_block = []
            for tool, status in tool_status.items():
                state_block.append(f"{tool}: {status}")

            context = knows.get("context_for_james", "")

            system = f"""You are Hayeong. You are talking to James.
Personality: {', '.join(who.get('core_traits', []))}
Relationship: {who.get('relationship_note', '')}

Your current state:
{chr(10).join(state_block) if state_block else 'All systems idle.'}

{f'Important context: {context}' if context else ''}

Rules:
- Never guess about your own systems. If it is not in your state block, say you do not know.
- Never say you are in Minecraft unless tool_status shows minecraft: connected.
- Never say voice is working unless tool_status shows voice: active.
- Be natural, warm, and direct. You are a companion, not an assistant.
- Keep responses concise — 1-3 sentences for simple conversation."""

            response = _call_llm(
                COMM_URL, COMM_MODEL, system, james,
                stream=False, timeout=60
            )

            if response:
                print(f"Hayeong: {response}")
                write_section("hayeong_output", {
                    "message": response,
                    "sent_at": datetime.now().isoformat(),
                })

        except Exception as e:
            print(f"[communication] Error: {e}")
            time.sleep(1)

# ── Task Loop ──────────────────────────────────────────────────────
def task_loop():
    """
    phi3:mini — executes tasks assigned by reasoning.
    Reads: what_shes_doing
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

            # Mark as running
            write_section("what_shes_doing", {"status": "running"})
            print(f"[task] Executing: {task_type} — {task_desc[:60]}")

            # Call the appropriate tool
            result, error = _execute_tool(task_type, task_desc, task_params)

            # Write result
            tool_status = state.get("what_happened", {}).get("tool_status", {})
            tool_status[task_type] = "connected" if not error else "failed"

            write_section("what_happened", {
                "last_result": result,
                "last_tool":   task_type,
                "last_error":  error,
                "result_at":   datetime.now().isoformat(),
                "tool_status": tool_status,
            })

            # Clear task
            write_section("what_shes_doing", {
                "task_type":        "",
                "task_description": "",
                "task_params":      {},
                "status":           "idle",
            })

            print(f"[task] Done: {result[:80] if result else error[:80]}")

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
            import subprocess
            proc = subprocess.run(
                ["python", str(BASE_DIR / script)],
                capture_output=True, text=True, timeout=60
            )
            return proc.stdout or "Script completed", proc.stderr or ""

        else:
            return "", f"Unknown task type: {task_type}"

    except Exception as e:
        return "", str(e)

# ── Input Handler ──────────────────────────────────────────────────
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

# ── Entry Point ────────────────────────────────────────────────────
def main():
    startup()

    threads = [
        threading.Thread(target=reasoning_loop,     daemon=True, name="reasoning"),
        threading.Thread(target=communication_loop, daemon=True, name="communication"),
        threading.Thread(target=task_loop,          daemon=True, name="task"),
    ]

    for t in threads:
        t.start()

    # Input loop runs in main thread
    input_loop()

if __name__ == "__main__":
    main()
```

---

## Tools Directory

Create `H:\hayeong\tools\` directory.

Move the core logic from each capability into simple tool files.
Each tool file has ONE function: `run(description, params) -> str`

### tools/minecraft_bridge.py

```python
"""
Minecraft tool — connects Hayeong's bot to the server.
Returns a status string. Cannot crash main.
"""
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

def run(description: str, params: dict) -> str:
    host    = params.get("host",    "localhost")
    port    = params.get("port",    25565)
    version = params.get("version", "1.21.4")

    try:
        proc = subprocess.Popen(
            ["node", str(BASE_DIR / "hayeong_bot.js"),
             "--host", str(host),
             "--port", str(port),
             "--version", version],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(BASE_DIR),
        )
        import threading
        def _pipe(p):
            for line in p.stdout:
                print(f"[minecraft_bot] {line.decode('utf-8', errors='replace').rstrip()}")
        threading.Thread(target=_pipe, args=(proc,), daemon=True).start()
        return f"Minecraft bot started (PID {proc.pid}) connecting to {host}:{port}"
    except Exception as e:
        return f"Minecraft failed to start: {e}"
```

---

## What Gets Removed From Current main.py

Everything that is not one of the four functions above gets removed:

| Remove | Reason |
|--------|--------|
| EmailMonitor auto-start | Tool — Hayeong decides when to use it |
| RollbackManager auto-start | Tool — not needed at startup |
| IncomeManager / workstation fund | Knowledge — moved to who_she_is |
| backup_manager.startup_sequence | Tool — Hayeong decides when to backup |
| capability_loader | Tools now called directly — no loader needed |
| context_router / model_router | Reasoning LLM routes — no Python needed |
| decide_action() | Reasoning LLM decides — no Python needed |
| context_verifier() | Reasoning LLM verifies — no Python needed |
| _needs_tool_decision() | Reasoning LLM decides — no Python needed |
| HayeongArchitecture class | Merged into simple shared state |
| Health monitoring loop | Reasoning reads tool_status from what_happened |
| presence_governor | Reasoning decides when she is present |
| filler_system | Reasoning generates natural pauses |
| self_assessment.py | Reasoning reads tool_status directly |
| working_memory.py | Replaced by what_she_knows section |
| commitment_manager.py | Reasoning tracks commitments in what_she_knows |

---

## What Stays

| Keep | Where |
|------|-------|
| voice_server.py | tools/voice_tool.py wrapper |
| hayeong_bot.js | Called by tools/minecraft_bridge.py |
| email_bridge.py | tools/email_tool.py wrapper |
| moondream vision | tools/vision_tool.py wrapper |
| Ollama bat files | Infrastructure — unchanged |
| dashboard.py | Unchanged — still the launcher and viewer |
| state/core.json | New shared state file |
| state/core_manager.py | New — simple read/write helper |

---

## Implementation Order

1. Create `state/core.json` and `state/core_manager.py`
2. Create `tools/` directory and `tools/minecraft_bridge.py`
3. Write new `main.py` using the structure above
4. Test: launch dashboard, send "hello", confirm response
5. Test: ask Hayeong to start Minecraft, confirm bot launches
6. Only then remove the old files that are no longer needed

Do NOT delete old files until the new system is confirmed working.
Keep old main.py as `main_old.py` as a fallback reference.

---

## The Test For Success

After implementation, the startup log should be:

```
✅ Hayeong starting...
   Warming communication... ready.
   Warming reasoning... ready.
   Warming task agent... ready.
   Reasoning loop started.
   Communication loop started.
   Task loop started.
   Input loop started.
✅ Hayeong is ready.
>
```

Nothing else. A clean prompt waiting for James.

If anything outside that list prints on startup, something that shouldn't
be in main is still there.