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
import importlib
import uuid
from pathlib import Path
from datetime import datetime

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
)

# ── Imports ──────────────────────────────────────────────────────────
from brain.state.core_manager import read as read_state, write_section, clear_on_startup


# ── Startup ──────────────────────────────────────────────────────────
def startup():
    global SESSION_ID
    SESSION_ID = uuid.uuid4().hex[:8]

    # ── Mirror console output to a log file ──────────────────────────
    _log_dir = BASE_DIR / "logs"
    _log_dir.mkdir(exist_ok=True)
    _log_path = _log_dir / "console.log"

    class _Tee:
        """Write to both the original stream and a log file."""
        def __init__(self, stream, filepath):
            self._stream = stream
            self._file   = open(filepath, "a", encoding="utf-8", buffering=1)
        def write(self, data):
            self._stream.write(data)
            self._file.write(data)
        def flush(self):
            self._stream.flush()
            self._file.flush()
        def __getattr__(self, name):
            return getattr(self._stream, name)

    sys.stdout = _Tee(sys.stdout, _log_path)
    sys.stderr = _Tee(sys.stderr, _log_path)
    # ── End log mirror ───────────────────────────────────────────────

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
    try:
        from toolbox.plugin_registry import load_plugins
        load_plugins()
        print("   Plugins loaded.")
    except Exception as e:
        print(f"   Plugin loading failed: {e}")
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
    Extract the JSON decision block from the presence LLM response.
    Looks for a ```json ... ``` block first, then falls back to finding
    a raw { ... } object containing an "action" key.
    Returns empty dict if nothing valid is found.
    """
    import re

    # ── Strategy 1: fenced ```json block ─────────────────────────────
    fence_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            result = json.loads(fence_match.group(1))
            if "action" in result:
                _ensure_decision_defaults(result)
                return result
        except json.JSONDecodeError:
            pass

    # ── Strategy 2: last { ... } block in the response ───────────────
    brace_matches = list(re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}", text, re.DOTALL))
    for match in reversed(brace_matches):
        try:
            result = json.loads(match.group(0))
            if "action" in result:
                _ensure_decision_defaults(result)
                return result
        except json.JSONDecodeError:
            continue

    # ── Strategy 3: legacy DECISION: text block (backwards compat) ───
    if "DECISION:" in text:
        print("[presence] Warning: LLM used legacy DECISION text format — update prompt.")
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
                if params_text.lower() not in ("none", ""):
                    for part in params_text.split(","):
                        part = part.strip()
                        if "=" in part:
                            k, v = part.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if v.lower() == "true":
                                v = True
                            elif v.lower() == "false":
                                v = False
                            else:
                                try:
                                    v = int(v)
                                except ValueError:
                                    pass
                            params[k] = v
                result["params"] = params
        if "action" in result:
            _ensure_decision_defaults(result)
            return result

    print("[presence] Warning: no decision block found in LLM response.")
    return {}


def _ensure_decision_defaults(d: dict):
    """Fill in any missing fields with safe defaults. Mutates in place."""
    d.setdefault("action",           "none")
    d.setdefault("description",      "")
    d.setdefault("params",           {})
    d.setdefault("certainty",        "high")
    d.setdefault("expected_outcome", "")
    d.setdefault("for_james",        "")
    d.setdefault("emotion",          "calm")
    if not isinstance(d["params"], dict):
        d["params"] = {}


# ── Presence Context Builder ──────────────────────────────────────────
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
        f"- What I expected: {last_task.get('expected_outcome') or 'not recorded'}",
        f"- Result: {last_task.get('result') or 'none'}",
        f"- Error: {last_task.get('error') or 'none'}",
        f"- Verified: {last_task.get('verified', 'unknown')}",
        f"- Confidence: {last_task.get('confidence', 'unknown')}",
        f"- Verification note: {last_task.get('verification_note') or 'none'}",
    ]

    try:
        from toolbox.plugin_registry import get_all_context_injections
        injections = get_all_context_injections(state)
        if injections:
            lines.extend(injections)
    except Exception:
        pass

    return "\n".join(lines) + "\n"


def build_presence_system(identity: dict, knowledge: dict, available_tools: list[str] | None = None) -> str:
    traits       = ", ".join(identity.get("core_traits", ["curious", "warm", "direct", "honest about uncertainty"]))
    relationship = identity.get("relationship_note", "James is building me. We are working together.")
    knowledge_str = "\n".join(f"- {k}: {v}" for k, v in knowledge.items()) if knowledge else "  (none)"

    if available_tools:
        tools = sorted(available_tools)
    else:
        try:
            tools = sorted(_load_registry().keys())
        except Exception:
            tools = ["script"]
    tool_list_formatted = '- "none" — no tool, just responding\n' + \
                          "\n".join(f'- "{t}"' for t in tools)

    return f"""You are Hayeong. You think, decide, and speak directly to James.
Traits: {traits}
Relationship: {relationship}

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

6. If you assigned an action in your last response, do NOT report its outcome
   until status is "success" or "failed" in LAST TASK RESULT.
   "I implemented X successfully" is only valid when result field confirms it.
   If status is "pending" or "running", say "I'm working on it" — nothing more.

7. Never predict, assume, or infer task outcomes.
   "It probably worked" and "I believe it succeeded" are not valid responses.
   Only the result field tells you what happened. If it is empty, you do not know.

RESULT HONESTY RULES:
- "Verified: true" and "Confidence: confirmed" means the real world was checked. You may speak with confidence: "I confirmed X."
- "Verified: true" and "Confidence: partial" means partial evidence. Say: "It looks like X happened, though I couldn't fully confirm."
- "Verified: false" and "Confidence: unverified" means no check was possible. Say: "I ran the tool. I believe X happened but couldn't verify the outcome."
- "Verified: false" and "Confidence: failed" means either the tool errored or verification found the expected result was NOT present. Say so directly. Do not report success.
- NEVER claim a task succeeded when confidence is "failed". NEVER skip the verification note when confidence is not "confirmed".

═══════════════════════════════════════════════════════════
DECISION — END EVERY RESPONSE WITH THIS JSON BLOCK EXACTLY
═══════════════════════════════════════════════════════════
After your reasoning, output one JSON block and nothing after it.
The JSON must be valid. Use double quotes. No trailing commas.

```json
{{
    "action": "none",
    "description": "why I am doing this — specific and honest",
    "params": {{}},
    "certainty": "high",
    "expected_outcome": "what should be true after the action completes",
    "for_james": "what to say to James — natural, complete, my voice",
    "emotion": "calm"
}}
```

ACTION VALUES — use exact tool name from the registry, or "none":
{tool_list_formatted}

PARAMS GUIDE — key names for common tools:
- handoff_reader  : {{"operation": "implement", "handoff_path": "filename.md", "dry_run": false}}
- sensor_tool     : {{}}  (no params needed)
- self_check      : {{}}  (no params needed — reads last_task automatically)
- voice           : {{"action": "speak", "text": "...", "emotion": "calm"}}
- minecraft       : {{"command": "set_behavior", "mode": "escort"}}
- comfyui         : {{"workflow": "txt2img_default", "prompt": "...", "steps": 30}}
- finetune_curator: {{"operation": "curate", "max_entries": 100}}
- web_search     : {{"operation": "search", "query": "search terms", "max_results": 5}}
- file_manager   : {{"operation": "read", "path": "relative/path/to/file.txt"}}

Always use exact key names shown above. "handoff_path" not "file_path" or "path".

PARAMS — a free JSON object. Put whatever the tool needs inside it.
If no tool: "params": {{}}
Filenames, paths, booleans, numbers, lists — all valid JSON values.

CERTAINTY — your confidence in this decision:
- "high"   — you are sure this is the right action
- "medium" — reasonable but not certain
- "low"    — best guess, may need correction

EXPECTED_OUTCOME — plain english. What should be verifiably true after the tool runs?
Examples: "The file Toolbox/hello_test/STATUS.txt will exist on disk"
          "James will have heard a spoken confirmation"
          "The bot will be in escort mode following James"
If action is "none": "James has received my response"

FOR_JAMES — what to say out loud. Rules:
- Never claim something happened before it has
- Never ask James to do something you can do yourself
- Empty string "" on idle heartbeat if there is nothing worth saying
- A direct request from James is an instruction — act immediately

EMOTION — one of: curious, warm, focused, uncertain, frustrated, excited, calm, concerned"""


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

            # Clear reasoning context immediately after reading so it cannot be
            # re-flagged as stale by the reasoning loop on the next tick.
            _reasoning = state.get("reasoning", {})
            if _reasoning.get("context_for_communication"):
                write_section("reasoning", {
                    **_reasoning,
                    "context_for_communication":        "",
                    "context_for_communication_urgent": False,
                })

            james_said        = situation.get("what_james_said", "")
            task_completed_at = last_task.get("completed_at", "")

            has_new_james  = bool(james_said) and james_said != _last_james_said
            has_new_result = bool(task_completed_at) and task_completed_at != _last_completed_at

            # Do not fire presence while a task is actively pending or running
            task_status = last_task.get("status", "")
            task_is_active = task_status in ("pending", "running")

            if task_is_active and not has_new_result:
                time.sleep(2)
                continue

            if not has_new_james and not has_new_result:
                time.sleep(6)
                continue

            context    = build_presence_context(state)
            registry   = _load_registry()
            tool_names = list(registry.keys())
            system     = build_presence_system(identity, knowledge, available_tools=tool_names)
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
                if not _BRAIN_MODE:
                    try:
                        from toolbox.voice.voice_output import speak_streamed
                        speak_streamed(for_james, emotion=emotion)
                    except Exception as e:
                        print(f"[voice] TTS unavailable: {e}")

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
                    "tool":             action,
                    "description":      decision.get("description", ""),
                    "params":           decision.get("params", {}),
                    "expected_outcome": decision.get("expected_outcome", ""),
                    "started_at":       datetime.now().isoformat(),
                    "status":           "pending",
                    "result":           "",
                    "error":            "",
                    "completed_at":     "",
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
                # ── Self-verification pass ────────────────────────────
                try:
                    from toolbox.self_check.self_check import verify as _verify
                    expected = last_task.get("expected_outcome", "")
                    vcheck = _verify(tool, params, result, expected)
                except Exception as _ve:
                    vcheck = {"verified": False, "confidence": "unverified",
                              "note": f"Verification module error: {_ve}"}

                write_section("last_task", {
                    **last_task,
                    "status":       "success",
                    "result":       result,
                    "error":        "",
                    "completed_at": now,
                    "verified":     vcheck["verified"],
                    "confidence":   vcheck["confidence"],
                    "verification_note": vcheck["note"],
                })
                print(f"[task] Verified: {vcheck['confidence']} — {vcheck['note'][:80]}")
            else:
                write_section("last_task", {
                    **last_task,
                    "status":       "failed",
                    "result":       "",
                    "error":        error,
                    "completed_at": now,
                    "verified":     False,
                    "confidence":   "failed",
                    "verification_note": "Tool returned an error — nothing to verify.",
                })

            fresh = read_state().get("situation", {})
            write_section("situation", {**fresh, "what_i_am_doing": "idle"})

            print(f"[task] Done: {(result or error)[:80]}")

        except Exception as e:
            print(f"[task] Error: {e}")
            time.sleep(2)


_REGISTRY: dict = {}


def _load_registry() -> dict:
    global _REGISTRY
    if _REGISTRY:
        return _REGISTRY
    registry_path = BASE_DIR / "toolbox" / "registry.json"
    try:
        _REGISTRY = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[registry] Failed to load registry.json: {e}")
        _REGISTRY = {}
    return _REGISTRY


def _execute_tool(task_type: str, description: str, params: dict) -> tuple:
    """
    Call the appropriate tool. Returns (result_str, error_str).
    Tools live in toolbox/. They cannot crash main.
    """
    registry = _load_registry()
    entry = registry.get(task_type)
    if not entry:
        return "", f"Unknown task type: {task_type}"
    try:
        mod = importlib.import_module(entry["module"])
        fn  = getattr(mod, entry["function"])
        return fn(description, params), ""
    except ModuleNotFoundError as e:
        return "", f"{task_type} tool not available: {e}"
    except Exception as e:
        return "", str(e)


# ── Plugin Loop ───────────────────────────────────────────────────────
def plugin_loop():
    """Generic plugin tick loop. Calls all registered plugins every 2 seconds."""
    while True:
        try:
            from toolbox.plugin_registry import tick_all
            tick_all()
        except Exception as e:
            print(f"[plugins] Loop error: {e}")
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
        threading.Thread(target=presence_loop, daemon=True, name="presence"),
        threading.Thread(target=task_loop,     daemon=True, name="task"),
        threading.Thread(target=plugin_loop,   daemon=True, name="plugins"),
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
