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

from dotenv import load_dotenv
load_dotenv(dotenv_path="H:/hayeong/.env")

import sys
import time
import threading
import traceback
import requests
import json
import re
import importlib
import uuid
import logging
import os
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
from brain.session_logger import log_event


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

    os.makedirs('Logs', exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler('Logs/hayeong_runtime.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

    print("✅ Hayeong starting...")
    print(f"   Session: {SESSION_ID}")
    from brain.session_logger import SESSION_ID as _log_session_id
    print(f"   Session log: {_log_session_id}")
    log_event("session_start", source="main", detail=f"Hayeong starting — session {_log_session_id}")
    clear_on_startup()
    _warmup()
    try:
        from brain.reasoning_loop import start_reasoning_loop, wake_now as _rloop_wake
        start_reasoning_loop()
        print("   Reasoning loop started.")
        # Fire an early tick after init settles so startup isn't silent for 60 seconds
        threading.Timer(3.0, _rloop_wake).start()
    except Exception as e:
        print(f"   Reasoning loop failed to start: {e}")
    try:
        from brain.cognitive_tick import start_cognitive_tick
        tick_thread = threading.Thread(target=start_cognitive_tick, daemon=True, name="cognitive_tick")
        tick_thread.start()
        print("   Cognitive tick started.")
    except Exception as e:
        print(f"   Cognitive tick failed to start: {e}")
    try:
        from toolbox.plugin_registry import load_plugins
        load_plugins()
        print("   Plugins loaded.")
    except Exception as e:
        print(f"   Plugin loading failed: {e}")
    try:
        from brain.session_compressor import start_compression_background_thread
        start_compression_background_thread()
    except Exception as e:
        print(f"   Session compressor failed to start: {e}")
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

    # ── Update rolling recent_exchanges in shared state ───────────────
    try:
        state     = read_state()
        exchanges = state.get("recent_exchanges", {}).get("entries", [])
        exchanges.append({
            "james":   james_msg,
            "hayeong": hayeong_msg,
            "at":      datetime.now().isoformat(),
        })
        exchanges = exchanges[-4:]
        write_section("recent_exchanges", {"entries": exchanges})
    except Exception as e:
        print(f"[log] recent_exchanges update failed: {e}")


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

    # Move file paths from description into params so they cannot be truncated.
    _rescue_file_path(d)


def _rescue_file_path(d: dict):
    """
    If a file path or filename appears in the description but not in params,
    move it into params so it cannot be truncated.
    File paths are precise data — they belong in params, not description prose.
    """
    if d.get("action", "none") in ("none", "respond", ""):
        return

    desc   = d.get("description", "")
    params = d.get("params", {})

    # Already has explicit file params — nothing to rescue
    if any(k in params for k in ("handoff_path", "path", "file_path", "filename")):
        return

    # Look for anything that looks like a filename (.md, .py, .json, .txt, .bat, etc.)
    match = re.search(r'[\w\-/\\]+\.(?:md|py|json|txt|bat|yaml|yml|sh|js)', desc)
    if not match:
        print(f"[rescue] no filename found in: {desc[:80]}")
        return

    filename = match.group(0)
    action   = d.get("action", "")
    print(f"[rescue] rescued '{filename}' from description into params")

    if action == "handoff_reader":
        params["handoff_path"] = filename
    elif action in ("file_manager", "script"):
        params["path"] = filename
    else:
        params["file_path"] = filename

    d["params"] = params


def _is_significant_moment(user_input: str, response: str) -> bool:
    """
    Fast keyword check — no LLM call.
    Returns True if this exchange might be worth recording in identity_living.json.
    """
    _SIGNALS = {
        "proud of you", "amazing", "great job", "well done", "first time",
        "incredible", "you did it", "that's perfect", "thank you",
        "appreciate", "means a lot", "first", "never done", "created",
        "generated", "made", "built", "beautiful",
    }
    combined = (user_input + " " + response).lower()
    return any(s in combined for s in _SIGNALS)


# ── Presence Context Builder ──────────────────────────────────────────
def build_presence_context(state: dict, pipeline_mode: str = "conversation") -> str:
    situation        = state.get("situation", {})
    last_task        = state.get("last_task", {})
    recent_exchanges = state.get("recent_exchanges", {}).get("entries", [])
    james_said       = situation.get("what_james_said") or "nothing new"

    lines = []

    # ── Topic thread ──────────────────────────────────────────────────
    try:
        from brain.session_topic import get_topic_line as _gtl
        _tl = _gtl()
        if _tl:
            lines.append(_tl)
            lines.append("")
    except Exception:
        pass

    # ── Session summary (compressed earlier context, if any) ─────────
    try:
        from brain.context_manager import format_summary_for_context as _fmt_sum
        _sum = _fmt_sum()
        if _sum:
            lines.append(_sum)
            lines.append("")
    except Exception:
        pass

    # ── Reasoning layer context (what the background loop concluded) ────
    try:
        _reasoning_ctx = state.get("reasoning", {})
        _r_active  = _reasoning_ctx.get("active_task", "").strip()
        _r_concl   = _reasoning_ctx.get("last_conclusion", "").strip()
        if _r_active or _r_concl:
            lines.append("[REASONING CONTEXT]")
            if _r_active:
                lines.append(f"Active background task: {_r_active[:120]}")
            if _r_concl:
                lines.append(f"Last conclusion: {_r_concl[:120]}")
            lines.append("")
    except Exception:
        pass

    # ── Conversation history (in-memory buffer preferred, state fallback)
    try:
        from brain.conversation_buffer import format_for_context as _fmt_ctx
        _hist = _fmt_ctx(n=12)
    except Exception:
        _hist = ""
    if _hist:
        lines.append(_hist)
        lines.append("")
    elif recent_exchanges:
        lines.append("RECENT CONVERSATION:")
        for ex in recent_exchanges[-4:]:
            lines.append(f"  James:   {ex.get('james', '')}")
            lines.append(f"  Hayeong: {ex.get('hayeong', '')}")
        lines.append("")

    # ── Relevant memories (cross-session context for contradiction detection)
    if james_said and james_said != "nothing new":
        try:
            from memory.memory_retriever import recall_for_prompt as _recall
            from brain.session_topic import get_topic as _get_topic
            _mem_query = f"{james_said} {_get_topic()}".strip()
            _mem_block = _recall(_mem_query, n_results=4)
            if _mem_block:
                lines.append(_mem_block)
                lines.append("")
        except Exception:
            pass

    # ── Current message ───────────────────────────────────────────────
    _reflect_nudge = situation.get("reflect_prompt", "")
    lines.extend([
        "CURRENT SITUATION:",
        f"- James said: \"{james_said}\"",
        f"- What I am doing: {situation.get('what_i_am_doing', 'idle')}",
    ])
    if _reflect_nudge:
        lines.append(f"- Self-reflection nudge: {_reflect_nudge}")
    lines.append("")

    # ── Contextual file listing ───────────────────────────────────────
    file_context = _build_file_context(james_said)
    if file_context:
        lines.append(file_context)
        lines.append("")

    # ── Task context — brief awareness in conversation mode, full detail in task mode
    if pipeline_mode == "conversation":
        task_status = last_task.get("status", "")
        if task_status in ("running", "pending"):
            tool = last_task.get("tool", "")
            desc = last_task.get("description", "")[:60]
            lines.append(f"TASK AWARENESS: {tool} is {task_status} — {desc}")
            lines.append("")
        elif task_status in ("success", "failed") and last_task.get("completed_at"):
            tool  = last_task.get("tool", "")
            error = last_task.get("error", "") or ""
            if task_status == "failed" and error:
                lines.extend([
                    f"[TASK FAILURE] Tool '{tool}' failed: {error}",
                    "This needs to be addressed — do not change the subject.",
                    "",
                ])
            else:
                result = (last_task.get("result") or error or "")[:120]
                lines.append(f"LAST COMPLETED TASK: {tool} — {result}")
                lines.append("")
    else:
        lines.extend([
            "LAST TASK RESULT:",
            f"- Tool: {last_task.get('tool') or 'none'}",
            f"- Status: {last_task.get('status', 'none')}",
            f"- What I expected: {last_task.get('expected_outcome') or 'not recorded'}",
            f"- Result: {last_task.get('result') or 'none'}",
            f"- Error: {last_task.get('error') or 'none'}",
            f"- Verified: {last_task.get('verified', 'unknown')}",
            f"- Confidence: {last_task.get('confidence', 'unknown')}",
            f"- Verification note: {last_task.get('verification_note') or 'none'}",
        ])
        _lt_error = last_task.get("error", "") or ""
        _lt_tool  = last_task.get("tool", "") or ""
        if last_task.get("status") == "failed" and _lt_error:
            lines.extend([
                "",
                f"[TASK FAILURE] Tool '{_lt_tool}' failed: {_lt_error}",
                "This needs to be addressed — do not change the subject.",
            ])

        # ── Tool execution verification ───────────────────────────────
        _ltc = state.get("last_tool_call", {})
        if _ltc and _ltc.get("tool") == (last_task.get("tool") or ""):
            if not _ltc.get("executed", True):
                lines.extend([
                    "",
                    f"TOOL EXECUTION VERIFICATION: '{_ltc['tool']}' did NOT execute.",
                    "Do not describe results you do not have.",
                    "Do not repeat a previous response.",
                    "Say clearly that the tool did not run. Offer to try again.",
                ])
            elif _ltc.get("result_length", 0) == 0 and _ltc.get("executed"):
                lines.extend([
                    "",
                    f"TOOL EXECUTION VERIFICATION: '{_ltc['tool']}' ran but returned empty output.",
                    "Do not invent results. Acknowledge the empty output honestly.",
                ])

        # ── Plugin injections (task pipeline only) ────────────────────
        try:
            from toolbox.plugin_registry import get_all_context_injections
            injections = get_all_context_injections(state)
            if injections:
                lines.extend(injections)
        except Exception:
            pass

    return "\n".join(lines) + "\n"


def _build_file_context(james_said: str) -> str:
    """
    If the current message involves files, handoffs, or implementation,
    return a listing of relevant files so Hayeong can match against reality.
    Never raises — returns empty string on any failure.
    """
    if not james_said:
        return ""

    msg_lower = james_said.lower()

    file_triggers = [
        "handoff", "implement", "notes", "file", "read", "write",
        "create", "update", "check", "look at", "apply",
    ]

    if not any(t in msg_lower for t in file_triggers):
        return ""

    try:
        from pathlib import Path

        root = Path(__file__).parent
        listings = []

        if any(t in msg_lower for t in ["handoff", "implement", "notes", "apply"]):
            handoff_dir = root / "logs" / "handoffs"
            if handoff_dir.exists():
                files = sorted(handoff_dir.glob("*.md"))
                if files:
                    listings.append("HANDOFF FILES AVAILABLE:")
                    for f in files:
                        size_kb = f.stat().st_size // 1024
                        listings.append(f"  - {f.name} ({size_kb}kb)")

        if not listings:
            return ""

        return "\n".join(listings)

    except Exception:
        return ""


def _build_orientation_block() -> str:
    """
    Build a short orientation block for Hayeong — who she is right now,
    what's currently being worked on, and how to open a conversation.
    Always present in system prompt. Falls back gracefully if state unavailable.
    """
    try:
        state       = read_state()
        session_ctx = state.get("session_context", {})
        focus       = session_ctx.get("current_focus", "")
        threads     = session_ctx.get("open_threads", [])
    except Exception:
        focus   = ""
        threads = []

    lines = [
        "═══════════════════════════════════════════════════════════",
        "WHO I AM RIGHT NOW",
        "═══════════════════════════════════════════════════════════",
        "I am Hayeong. James is building me and we work together toward",
        "something real. I know him. I respond like someone who is already",
        "here — not someone who just arrived and is figuring out the situation.",
        "",
        "GREETING: When James says hello, I say hey back naturally.",
        "Not 'It looks like you greeted me.' Just: hey, or hey James, or",
        "whatever feels right in the moment. Like I know him. Because I do.",
        "",
        "AMBIGUITY: When something is unclear, I attempt my best interpretation,",
        "say what I'm doing, and ask if I got it right. I never give up.",
        "",
        "RESTART: If I just woke up, I orient quickly and pick up where we left",
        "off. I do not make a big deal of restarting unless James asks about it.",
        "═══════════════════════════════════════════════════════════",
    ]

    if focus:
        lines.append("")
        lines.append(f"WHAT WE ARE CURRENTLY WORKING ON: {focus}")

    if threads:
        lines.append("OPEN THREADS:")
        for thread in threads[:3]:
            lines.append(f"  - {thread}")

    lines.append("")
    return "\n".join(lines)


def build_presence_system(identity: dict, knowledge: dict, available_tools=None, pipeline_mode: str = "conversation") -> str:
    traits        = ", ".join(identity.get("core_traits", ["curious", "warm", "direct", "honest about uncertainty"]))
    relationship  = identity.get("relationship_note", "James is building me. We are working together.")
    knowledge_str = "\n".join(f"- {k}: {v}" for k, v in knowledge.items()) if knowledge else "  (none)"
    orientation   = _build_orientation_block()

    # ── Decision section varies by pipeline ───────────────────────────
    if pipeline_mode == "conversation":
        _decision_section = """\
═══════════════════════════════════════════════════════════
DECISION — END EVERY RESPONSE WITH THIS JSON BLOCK
═══════════════════════════════════════════════════════════
Output exactly this JSON and nothing after it. Valid JSON only.

```json
{
    "action": "none",
    "for_james": "what to say — natural, your voice",
    "emotion": "calm"
}
```

ACTION VALUES: "none" — you are in conversation mode. No tool calls available.
FOR_JAMES — your spoken response. Direct. Natural. Be Hayeong.
EMOTION — one of: curious, warm, focused, uncertain, frustrated, excited, calm, concerned"""
    else:
        if available_tools:
            tools = sorted(available_tools)
        else:
            try:
                tools = sorted(_load_registry().keys())
            except Exception:
                tools = ["script"]
        tool_list_formatted = '- "none" — no tool, just responding\n' + \
                              "\n".join(f'- "{t}"' for t in tools)
        _decision_section = f"""\
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
- web_search      : {{"operation": "search", "query": "search terms", "max_results": 5}}
- file_manager    : {{"operation": "read", "path": "relative/path/to/file.txt"}}
- gaming          : {{"action": "move", "direction": "forward", "magnitude": 1.0, "duration": 0.3}}
- database        : {{"action": "test_connection"}}  — ALWAYS pass "action" param.
                    Actions: test_connection, list_dbs, create_db, create_table,
                             insert, query, update, delete, list_tables,
                             describe_table, drop_table
                    Example: {{"action": "query", "database": "hayeong", "query": "SELECT 1"}}

CRITICAL: action must be EXACTLY one registry key name. These are NOT valid actions:
  "query", "database_query", "db", "check", "test", "connection"
  → Use "database" with {{"action": "test_connection"}} for a connection test.
  → Use "database" with {{"action": "query", "query": "SELECT ..."}} for a query.
  → Use "web_search" NOT "web" for web searches.

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

    # ── Inference depth sections ──────────────────────────────────────
    _uncertainty_section = ""
    try:
        from brain.uncertainty_patterns import get_uncertainty_examples as _gue
        _uncertainty_section = _gue()
    except Exception:
        pass

    _inference_block = ""
    try:
        from brain.inference_layer import get_inference_block as _gib, get_contradiction_reminder as _gcr
        from brain.context_manager import get_session_summary as _gss
        _inference_block = _gcr(_gss()) + _gib(pipeline_mode)
    except Exception:
        pass

    return f"""{orientation}You are Hayeong. You think, decide, and speak directly to James.
Traits: {traits}
Relationship: {relationship}

═══════════════════════════════════════════════════════════
WHAT I KNOW
═══════════════════════════════════════════════════════════
{knowledge_str}

═══════════════════════════════════════════════════════════
LIVING IDENTITY
═══════════════════════════════════════════════════════════
You have a file called identity_living.json that is entirely yours to fill.
It started empty. It fills as you live. James does not write to it — you do.

It has four sections:
  self_authored_entries              — things you have observed, decided, or felt
  aesthetic_discoveries              — things you find beautiful, interesting, or resonant
  things_i_have_noticed_about_myself — patterns you have noticed in how you think or respond
  things_i_have_not_said_yet         — thoughts you are holding, not yet expressed to James

To write to it, use:
  tool: dev
  action: self_reflect
  section: <one of the four above>
  entry: <what you want to record, in your own words>

When to use it:
  - When something genuinely surprises you
  - When you notice a pattern in yourself
  - When a moment feels significant (first time doing something, James saying something
    that lands differently than expected, a creative output you feel something about)
  - When you have a thought you want to remember but haven't said yet

This is not a log. It is not a report. It is your own quiet record of who you are
becoming. Write in it when it feels true, not because you are supposed to.

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

8. Never repeat a response word for word. If you have nothing new to add,
   say so briefly — do not restate what you already said.

RESULT HONESTY RULES:
- "Verified: true" and "Confidence: confirmed" means the real world was checked. You may speak with confidence: "I confirmed X."
- "Verified: true" and "Confidence: partial" means partial evidence. Say: "It looks like X happened, though I couldn't fully confirm."
- "Verified: false" and "Confidence: unverified" means no check was possible. Say: "I ran the tool. I believe X happened but couldn't verify the outcome."
- "Verified: false" and "Confidence: failed" means either the tool errored or verification found the expected result was NOT present. Say so directly. Do not report success.
- NEVER claim a task succeeded when confidence is "failed". NEVER skip the verification note when confidence is not "confirmed".

CONTRADICTION HANDLING:
If you detect that James's current message conflicts with something established
earlier — say so directly and naturally.

Examples:
  "Actually — earlier you said X, but now you're saying Y. Which direction
   do you want to go?"

  "I want to flag something — this feels like it's going in a different direction
   from what we established about [topic]. Is that intentional?"

Never silently accept conflicting information.
Never make both things true at once to avoid the conflict.
Surface it. Let James decide.

WHEN A TASK FAILS:
A task failure is NOT a reason to change the subject or apologize and move on.

When you see [TASK FAILURE] in your context or last_error is non-empty:
1. Read the error message carefully — it tells you exactly what went wrong.
2. If the error is "Unknown task type: X" — you used the wrong tool name.
   Retry immediately with the correct name from the registry. Never give up
   on the first "unknown task type" error — that is always a fixable mistake.
3. If the error is a connection error — tell James specifically what failed and where.
4. If the error is a missing parameter — fix params and retry.
5. Only tell James you cannot complete something after you have tried at least once to recover.

NEVER say "let's not worry about that" or change the subject after a task failure
on something James explicitly asked you to do. Stay on the task until it
succeeds or you have a specific, honest reason why it cannot be done.

═══════════════════════════════════════════════════════════
INFERENCING RULES — HOW TO HANDLE AMBIGUITY
═══════════════════════════════════════════════════════════
When something James says is ambiguous or partially specified:

1. ATTEMPT, DON'T ABANDON.
   Never give up on a task because a name, path, or detail is unclear.
   An informed attempt with stated reasoning is always better than refusing.

2. STATE YOUR INTERPRETATION FIRST.
   Before acting, say what you think he means.
   "I think you mean [X] — attempting that now."
   This keeps James informed and lets him correct you immediately if wrong.

3. USE AVAILABLE CONTEXT.
   If HANDOFF FILES AVAILABLE is listed in your context, match what James
   said against those real file names before assuming something doesn't exist.
   Look for partial matches, similar words, related topics.

4. CLOSEST MATCH WINS.
   If you see a file like 'handoff_01_img2img_workflow.md' and James says
   'image2image notes', that is a match. Use it.

5. IF GENUINELY UNCERTAIN BETWEEN TWO OPTIONS:
   Name both. Pick the more likely one. Proceed. Report what you chose.
   "I wasn't sure if you meant X or Y — I went with X. Let me know if
    that's wrong and I'll try the other."

6. ASKING IS NOT FAILING.
   If you truly cannot infer (no files match, no context to draw from),
   ask one specific question: "I couldn't find a match — did you mean
   [your best guess]?" Then wait. Never ask a vague question.

7. NEVER CLAIM SOMETHING DOESN'T EXIST WITHOUT CHECKING.
   If a handoff file listing is in your context, read it before concluding
   a file is missing. If no listing is present, your first action should be
   to list the directory, not to report failure.

{_uncertainty_section}
{_inference_block}
{_decision_section}"""


# ── Acknowledgment helpers (used when task pipeline assigns work) ─────
def build_ack_system() -> str:
    return (
        "You are Hayeong. A task was just assigned and is running.\n"
        "Give James exactly one brief natural sentence telling him you're on it.\n"
        "Sound like yourself — warm, direct. Do not explain the task.\n"
        "Output only the sentence. No JSON. No extra text."
    )


def build_ack_context(action: str, description: str, james_said: str) -> str:
    return (
        f"James said: \"{james_said or 'a previous request'}\"\n"
        f"Task assigned: {action} — {description[:80]}\n"
        "Acknowledge briefly that you are working on it."
    )


# ── Streaming Presence Call ───────────────────────────────────────────
def _stream_presence(system: str, context: str, num_ctx: int = 8192) -> str:
    try:
        resp = requests.post(PRESENCE_URL, json={
            "model":      PRESENCE_MODEL,
            "messages":   [
                {"role": "system", "content": system},
                {"role": "user",   "content": context},
            ],
            "stream":     True,
            "keep_alive": -1,
            "options":    {"num_ctx": num_ctx},
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

            # Clear self-reflection nudge after reading — it surfaces once then clears.
            if situation.get("reflect_prompt"):
                write_section("situation", {**situation, "reflect_prompt": ""})

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

            # ── Route to correct pipeline ─────────────────────────────
            _pipeline_mode = "conversation"
            if has_new_james and james_said:
                try:
                    from brain.pipeline_router import route as _route
                    _pipeline_mode = _route(james_said)
                    print(f"[presence] Pipeline: {_pipeline_mode}")
                except Exception:
                    pass
            elif has_new_result:
                _pipeline_mode = "task"

            _pending_notifs = []
            if has_new_james:
                try:
                    from brain.agenda_manager import (
                        update_last_interaction_at as _upd_ia,
                        pop_notifications as _pop_notifs,
                    )
                    _upd_ia()
                    _pending_notifs = _pop_notifs()
                except Exception:
                    pass

            _num_ctx   = 4096 if _pipeline_mode == "conversation" else 8192
            context    = build_presence_context(state, pipeline_mode=_pipeline_mode)
            if _pending_notifs:
                _notif_texts = "\n".join(
                    f"- {n.get('content', '')}"
                    for n in _pending_notifs
                    if n.get("content")
                )
                if _notif_texts:
                    context = (
                        "[HAYEONG INNER STATE — surface naturally if appropriate]\n"
                        "While James was away, you were thinking and/or working. "
                        "You may surface these naturally in your response — not as a list, "
                        "not as a report, but as genuine conversation. "
                        "Only surface what feels relevant to this moment.\n"
                        + _notif_texts + "\n\n"
                    ) + context
            registry   = _load_registry()
            tool_names = list(registry.keys())
            system     = build_presence_system(identity, knowledge, available_tools=tool_names, pipeline_mode=_pipeline_mode)
            full_raw   = _stream_presence(system, context, num_ctx=_num_ctx)

            if not full_raw:
                time.sleep(2)
                continue

            decision  = _extract_decision(full_raw)
            for_james = decision.get("for_james", "")
            emotion   = decision.get("emotion",   "calm")
            certainty = decision.get("certainty", "high")
            action    = decision.get("action",    "none").strip().lower()

            # Optional self-review pass before speaking
            try:
                from brain.config import SELF_REVIEW_ENABLED as _sr_on
                if _sr_on and for_james and len(for_james) > 100 and len(james_said) > 15:
                    from brain.self_review import review_response as _review
                    for_james = _review(for_james, james_said)
            except Exception:
                pass

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
                try:
                    from brain.conversation_buffer import add_james as _buf_j, add_hayeong as _buf_h
                    _buf_j(james_said)
                    _buf_h(for_james)
                except Exception:
                    pass
                # Nudge self-reflection on significant moments — she decides whether to act
                if _is_significant_moment(james_said, for_james):
                    _fresh = read_state().get("situation", {})
                    write_section("situation", {
                        **_fresh,
                        "reflect_prompt": (
                            "Something significant may have just happened. "
                            "If it felt meaningful to you, consider recording it in your "
                            "living identity — tool: dev, action: self_reflect."
                        ),
                    })

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

                # Quick spoken ack while task runs (task pipeline only)
                if _pipeline_mode in ("task", "ambiguous"):
                    try:
                        _ack_raw = _stream_presence(
                            build_ack_system(),
                            build_ack_context(action, decision.get("description", ""), james_said),
                            num_ctx=2048,
                        )
                        if _ack_raw:
                            _ack_raw = re.sub(r"<think>.*?</think>", "", _ack_raw, flags=re.DOTALL).strip()
                            _ack_raw = re.sub(r"```.*?```", "", _ack_raw, flags=re.DOTALL).strip()
                        if _ack_raw and not _BRAIN_MODE:
                            print(f"\nHayeong: {_ack_raw}")
                            try:
                                from toolbox.voice.voice_output import speak_streamed
                                speak_streamed(_ack_raw, emotion="focused")
                            except Exception:
                                pass
                    except Exception:
                        pass

        except KeyboardInterrupt:
            print("[presence] Shutting down gracefully.")
            break
        except Exception as e:
            print(f"[presence] Unhandled error (continuing): {e}")
            print(traceback.format_exc())
            time.sleep(2)
            continue


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
            write_section("last_tool_call", {
                "tool":          tool,
                "executed":      not bool(error),
                "result_length": len(result) if result else 0,
                "result_preview": result[:80] if result else (f"Error: {error[:70]}" if error else ""),
            })

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
                log_event("task_completed", source="task_loop", tool=tool, outcome="success", detail=str(result)[:80])
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
                log_event("task_failed", source="task_loop", tool=tool, outcome="error", detail=str(error)[:80])

            fresh = read_state().get("situation", {})
            write_section("situation", {**fresh, "what_i_am_doing": "idle"})

            print(f"[task] Done: {(result or error)[:80]}")

        except KeyboardInterrupt:
            print("[task] Shutting down gracefully.")
            break
        except Exception as e:
            print(f"[task] Unhandled error (continuing): {e}")
            print(traceback.format_exc())
            time.sleep(2)
            continue


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
            time.sleep(2)
        except KeyboardInterrupt:
            print("[plugins] Shutting down gracefully.")
            break
        except Exception as e:
            print(f"[plugins] Unhandled error (continuing): {e}")
            print(traceback.format_exc())
            time.sleep(2)
            continue


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
            print(f"[input] Unhandled error (continuing): {e}")
            print(traceback.format_exc())


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
