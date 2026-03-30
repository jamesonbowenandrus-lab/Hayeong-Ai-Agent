# main.py
# Hayeong — brain and process supervisor.
#
# This is the one thing you run. Everything else — Discord, voice, Minecraft —
# she starts herself when she decides to, or when you ask her to.
#
# Architecture:
#   main.py  ←── always running (her consciousness + text chat)
#     ├── auto-launches: discord_hayeong.py  (her outside line to James)
#     ├── on request:    voice_ptt.py        ("open your mic")
#     ├── on request:    minecraft_bridge.py ("load minecraft")
#     └── monitors all: restarts if crashed
#
# To start everything: just run main.py. That's it.

import requests
import re
import json
import os
import sys
import time
import threading
import queue
import subprocess
import numpy as np
import sounddevice as sd

from context_router import ContextRouter, check_gpu_status
from model_router import ModelRouter

from voice import (
    transcribe, speak, listen_for_wake_word,
    record_seconds, get_volume, show_thinking,
    SAMPLE_RATE, INPUT_DEVICE, VOLUME_THRESHOLD,
    split_sentences, get_tts, get_voice_modulation,
    OUTPUT_DEVICE
)
from long_term_memory import recall_for_prompt, remember, categorize, import_from_memory_json
from system_prompt_builder import build_system_prompt, detect_state_of_mind
from hayeong_architecture import HayeongArchitecture
from backup_manager import startup_sequence
from identity_verification import (
    SessionTrust, is_setup, setup_passphrase,
    extract_passphrase_attempt, generate_suspicion_response
)

try:
    from situation_tracker import SituationTracker
    SITUATION_TRACKER_AVAILABLE = True
except ImportError:
    SITUATION_TRACKER_AVAILABLE = False
    print("⚠️  situation_tracker.py not found — shared situational awareness inactive")

try:
    from energy_manager import EnergyManager
    ENERGY_AVAILABLE = True
except ImportError:
    ENERGY_AVAILABLE = False

try:
    from mind_state_mixer import MindStateMixer, suggest_blend_for_context
    MIND_MIXER_AVAILABLE = True
except ImportError:
    MIND_MIXER_AVAILABLE = False

try:
    from self_mod_manager import SelfModManager
    SELF_MOD_AVAILABLE = True
except ImportError:
    SELF_MOD_AVAILABLE = False

try:
    from task_manager import TaskManager, detect_task_command, parse_task_from_text
    TASKS_AVAILABLE = True
except ImportError:
    TASKS_AVAILABLE = False
    print("⚠️  task_manager.py not found — tasks inactive")

try:
    from email_bridge import EmailBridge, hayeong_email, detect_email_command
    EMAIL_AVAILABLE = True
except ImportError:
    EMAIL_AVAILABLE = False
    print("⚠️  email_bridge.py not found — email inactive")

try:
    from email_monitor import EmailMonitor, format_email_results
    EMAIL_MONITOR_AVAILABLE = True
except ImportError:
    EMAIL_MONITOR_AVAILABLE = False
    print("⚠️  email_monitor.py not found — passive email monitoring inactive")

try:
    from comfyui_bridge import ComfyUIBridge
    comfyui = ComfyUIBridge()
    COMFYUI_AVAILABLE = True
except ImportError:
    comfyui = None
    COMFYUI_AVAILABLE = False
    print("⚠️  comfyui_bridge.py not found — image generation inactive")

try:
    from hayeong_logger import HayeongLogger
    logger = HayeongLogger()
    LOGGER_AVAILABLE = True
except ImportError:
    logger = None
    LOGGER_AVAILABLE = False
    print("⚠️  hayeong_logger.py not found — logging inactive")

try:
    from web_search import WebSearch
    searcher = WebSearch()
    SEARCH_AVAILABLE = searcher.is_available()
    if not SEARCH_AVAILABLE:
        print("⚠️  web_search: duckduckgo-search not installed — run: pip install duckduckgo-search")
except ImportError:
    searcher = None
    SEARCH_AVAILABLE = False
    print("⚠️  web_search.py not found — web search inactive")

try:
    from vision_bridge import VisionBridge
    vision = VisionBridge()
    VISION_AVAILABLE = vision.is_available()
    if not VISION_AVAILABLE:
        print("⚠️  vision_bridge: Pillow not installed — run: pip install Pillow")
except ImportError:
    vision = None
    VISION_AVAILABLE = False
    print("⚠️  vision_bridge.py not found — conversational vision inactive")

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

OLLAMA_URL     = "http://localhost:11434/api/chat"
MEMORY_FILE    = "memory.json"
IDENTITY_FILE  = "identity.json"
MOOD_FILE      = "mood.json"
HAYEONG_DIR    = os.path.dirname(os.path.abspath(__file__))

PRIMARY_MODEL  = "qwen2.5:14b"    # Main brain — smart, fits easily on 7900 XTX
FALLBACK_MODEL = "llama3.2:latest" # Fast lightweight fallback if primary fails

VAD_SILENCE_SECONDS = 1.2
VAD_MAX_SECONDS     = 12
VAD_CHUNK_SECONDS   = 0.4

# ─────────────────────────────────────────────
# PROCESS MANAGER
# Hayeong's control over her own capabilities.
# She starts them, she stops them, she notices if they crash.
# ─────────────────────────────────────────────

class ProcessManager:
    """
    Manages Hayeong's child processes (Discord, voice PTT, Minecraft, etc.)
    Each capability is a subprocess she owns and can start/stop/restart.
    """

    # Known capabilities: name → script filename
    CAPABILITIES = {
        "discord":   "discord_hayeong.py",
        "voice":     "voice_ptt.py",
        "minecraft": "minecraft_bridge.py",
        "observer":  "screen_observer.py",
    }

    def __init__(self):
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock  = threading.Lock()

    def start(self, name: str) -> str:
        script = self.CAPABILITIES.get(name)
        if not script:
            return f"I don't have a capability called '{name}'."

        script_path = os.path.join(HAYEONG_DIR, script)
        if not os.path.exists(script_path):
            return f"Script not found: {script}"

        with self._lock:
            proc = self._procs.get(name)
            if proc and proc.poll() is None:
                return f"{name} is already running."

            new_proc = subprocess.Popen(
                [sys.executable, script_path],
                cwd=HAYEONG_DIR,
                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
            )
            self._procs[name] = new_proc
            return f"started {name}"

    def stop(self, name: str) -> str:
        with self._lock:
            proc = self._procs.get(name)
            if not proc:
                return f"{name} isn't running."
            if proc.poll() is None:
                proc.terminate()
            del self._procs[name]
            return f"stopped {name}"

    def is_running(self, name: str) -> bool:
        with self._lock:
            proc = self._procs.get(name)
            return proc is not None and proc.poll() is None

    def status(self) -> dict:
        with self._lock:
            return {
                name: ("running" if proc.poll() is None else "stopped")
                for name, proc in self._procs.items()
            }

    def monitor_and_restart(self, name: str):
        """
        Call this in a background thread to auto-restart a capability if it crashes.
        Hayeong notices and restarts it — she doesn't go quietly offline.
        """
        def _watch():
            while True:
                time.sleep(10)
                with self._lock:
                    proc = self._procs.get(name)
                    if proc is None:
                        break  # intentionally stopped
                    if proc.poll() is not None:
                        print(f"\n⚠️  {name} crashed — restarting...")
                        script = self.CAPABILITIES[name]
                        script_path = os.path.join(HAYEONG_DIR, script)
                        new_proc = subprocess.Popen(
                            [sys.executable, script_path],
                            cwd=HAYEONG_DIR,
                            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
                        )
                        self._procs[name] = new_proc
                        print(f"✅ {name} restarted.")

        t = threading.Thread(target=_watch, daemon=True)
        t.start()

    def stop_all(self):
        with self._lock:
            for name, proc in list(self._procs.items()):
                if proc.poll() is None:
                    proc.terminate()
            self._procs.clear()


# ─────────────────────────────────────────────
# COMMAND INTENT DETECTION
# Recognizes requests to start/stop capabilities
# from natural language. Not a full NLU — just
# pattern matching on the things she'd actually hear.
# ─────────────────────────────────────────────

_START_PATTERNS = {
    "discord":   ["open discord", "start discord", "connect discord", "go on discord",
                  "get on discord", "launch discord"],
    "voice":     ["open your mic", "open mic", "start voice", "voice mode", "i want to talk",
                  "let's talk out loud", "turn on your mic", "enable voice",
                  "can you open your mic", "start listening"],
    "minecraft": ["load minecraft", "start minecraft", "open minecraft",
                  "let's play minecraft", "join minecraft", "connect to minecraft",
                  "can you load minecraft"],
    "observer":  ["start observer", "start screen observer", "start watching",
                  "enable observer", "turn on observer"],
}

_STOP_PATTERNS = {
    "discord":   ["close discord", "stop discord", "disconnect discord", "leave discord"],
    "voice":     ["close your mic", "mute", "stop voice", "stop listening",
                  "turn off your mic", "disable voice", "voice off"],
    "minecraft": ["close minecraft", "stop minecraft", "leave minecraft", "disconnect minecraft"],
    "observer":  ["stop observer", "stop watching", "disable observer", "turn off observer"],
}

_APPROVE_PATTERN = r'(?i)^approve\s+(\S+\.py|\S+)'
_DENY_PATTERN    = r'(?i)^deny\s+(\S+\.py|\S+)'

_SELFMOD_PATTERNS = [
    "show proposals", "what did you change", "what have you changed",
    "any proposals", "pending proposals", "weekly summary",
    "what did you modify", "show me your changes"
]

def detect_capability_command(text: str) -> tuple[str, str] | tuple[None, None]:
    """
    Returns (action, capability_name) or (None, None).
    action is "start" or "stop".
    """
    t = text.lower().strip()
    for cap, patterns in _START_PATTERNS.items():
        if any(p in t for p in patterns):
            return "start", cap
    for cap, patterns in _STOP_PATTERNS.items():
        if any(p in t for p in patterns):
            return "stop", cap
    return None, None


# ─────────────────────────────────────────────
# GPU CHECK
# ─────────────────────────────────────────────

def check_ollama_gpu():
    try:
        requests.get("http://localhost:11434/", timeout=3)
        print("✅ Ollama is running")
    except Exception:
        print("⚠️  Ollama not reachable — start Ollama before running Hayeong")
        return
    print(
        "   GPU check: run 'ollama ps' in a separate terminal after first response.\n"
        "   If GPU column is 0B: set OLLAMA_NUM_GPU=99 and "
        "HSA_OVERRIDE_GFX_VERSION=11.0.0, then restart Ollama."
    )

# ─────────────────────────────────────────────
# LOAD / SAVE
# ─────────────────────────────────────────────

def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def load_memory():   return load_json(MEMORY_FILE, [])
def save_memory(m):  save_json(MEMORY_FILE, m)
def load_identity(): return load_json(IDENTITY_FILE, {})
def load_mood():     return load_json(MOOD_FILE, {"focus": 0, "playfulness": 0, "motivation": 0})

# ─────────────────────────────────────────────
# VAD RECORDING
# ─────────────────────────────────────────────

def record_until_silence() -> str:
    from scipy.io.wavfile import write as wav_write
    import tempfile

    chunks = []
    silent_chunks     = 0
    max_silent_chunks = int(VAD_SILENCE_SECONDS / VAD_CHUNK_SECONDS)
    max_total_chunks  = int(VAD_MAX_SECONDS / VAD_CHUNK_SECONDS)
    chunk_samples     = int(VAD_CHUNK_SECONDS * SAMPLE_RATE)

    print("🎙️  Listening...", end="\r")

    for _ in range(max_total_chunks):
        chunk = sd.rec(chunk_samples, samplerate=SAMPLE_RATE, channels=1, device=INPUT_DEVICE)
        sd.wait()
        chunks.append(chunk)

        vol = get_volume(chunk)
        if vol < VOLUME_THRESHOLD:
            silent_chunks += 1
            if silent_chunks >= max_silent_chunks:
                break
        else:
            silent_chunks = 0

    if not chunks:
        return ""

    combined = np.concatenate(chunks, axis=0)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    wav_write(tmp.name, SAMPLE_RATE, combined)
    return tmp.name

# ─────────────────────────────────────────────
# STREAMING LLM RESPONSE
# ─────────────────────────────────────────────

def _strip_markdown(text: str) -> str:
    """
    Remove markdown formatting from a sentence before printing or speaking.
    Catches the common cases 14b produces: headers, bold, italic, bullet lists.
    This is a safety net — the system prompt tells her not to use markdown,
    but she sometimes slips on information-heavy turns (search results especially).
    """
    import re
    # Remove ### / ## / # headers (replace with just the header text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    # Remove **bold** and __bold__
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__",     r"\1", text)
    # Remove *italic* and _italic_
    text = re.sub(r"\*(.+?)\*",     r"\1", text)
    text = re.sub(r"_(.+?)_",       r"\1", text)
    # Remove leading bullet/list markers (-, *, •, numbered lists)
    text = re.sub(r"^\s*[-*•]\s+",  "",    text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+",  "",    text, flags=re.MULTILINE)
    # Collapse multiple blank lines left behind by removed headers/bullets
    text = re.sub(r"\n{3,}",        "\n\n", text)
    return text.strip()



# ─────────────────────────────────────────────
# JSON DECISION ENGINE
# A fast non-streaming call that asks Hayeong what she needs to do
# before she responds. Returns a structured action dict.
# This replaces the fragile [USE:xxx] first-line tag system.
#
# Design: one small focused call → clean parseable JSON → then stream
# the full natural response with zero parsing complexity.
# ─────────────────────────────────────────────

DECISION_PROMPT = """You are Hayeong's decision engine.

Based on the conversation and the latest message from James, decide what action (if any) is needed before you respond.

Available actions:
  web_search    — James wants something looked up online
                  Include: query (what to search), delivery ("conversational" or "document")
                  Use "document" when James asks for a report, comparison, or wants it emailed/saved
  vision        — James wants you to look at his screen or an image
                  Include: mode ("screen", "deep", or "image")
  image_gen     — James wants you to generate or draw an image
  email_check   — James wants to check his inbox
  email_send    — James wants to send a notification or summary email
  task_show     — James wants to see the task list
  task_add      — James wants to add a task
                  Include: task_text (what to add)
  none          — Normal conversation, no capability needed

Return ONLY valid JSON. No explanation, no markdown, no extra text.

Examples:
  {"action": "none"}
  {"action": "web_search", "query": "zapmander vs whale pup Once Human", "delivery": "document"}
  {"action": "web_search", "query": "RTX 5090 price", "delivery": "conversational"}
  {"action": "email_check"}
  {"action": "task_add", "task_text": "fix the voice bot"}
  {"action": "vision", "mode": "screen"}

CRITICAL RULES — read carefully:
  - If James just completed a task and is wrapping up ("thanks", "that's good", "sounds good",
    "I'll check it out", "no that's all") → ALWAYS return none. Do not repeat the task.
  - If James is talking ABOUT a capability (mentioning search, email, tasks in conversation)
    but not actually requesting it → return none. Example: "I want to test your search function"
    is NOT a search request — it is a conversational statement.
  - If a task was just performed in the last 1-2 turns and James hasn't asked for it again
    → do not repeat it. Check conversation history before deciding.
  - If James mentions emailing a report AS PART OF a research request → web_search with delivery=document
  - If the message is purely conversational, a thank you, or a reaction → none
  - Only pick an action if you are CERTAIN it is being freshly requested right now
  - When in doubt → none. It is always better to respond conversationally than to fire a tool incorrectly.
"""

def decide_action(user_input: str, memory: list, model: str = None,
                  snapshot: dict = None) -> dict:
    """
    Fast JSON decision call — determines what capability (if any) Hayeong
    needs to invoke before responding. Non-streaming, focused, fast.

    Returns a dict like:
      {"action": "none"}
      {"action": "web_search", "query": "...", "delivery": "conversational"}
      {"action": "email_check"}
    """
    _model = model or PRIMARY_MODEL

    # ── Inject relevant long-term memory into decision context ──
    # This lets Hayeong know James's patterns and preferences when deciding
    # what to do — not just recent turns, but things she actually remembers.
    long_term_context = ""
    try:
        long_term_context = recall_for_prompt(user_input, n_results=3)
    except Exception:
        pass

    # Build system content — long-term memory prepended to decision prompt
    system_content = DECISION_PROMPT
    if long_term_context:
        system_content = (
            f"[RELEVANT MEMORY — things Hayeong remembers about James that may inform this decision]\n"
            f"{long_term_context}\n\n"
            f"---\n\n"
            + system_content
        )
    # Inject situation snapshot — shared awareness of what phase/topic we're in
    if snapshot:
        from situation_tracker import SituationTracker
        # Build compact decision-friendly string from snapshot
        s = snapshot
        parts = [f"[SITUATION: phase={s.get('phase','?')}",
                 f"topic={s.get('current_topic','?')!r}"]
        if s.get("task_switching"):
            parts.append("SWITCHING=true")
        if s.get("just_completed"):
            parts.append(f"just_completed={s['just_completed']!r}")
        constraints = s.get("active_constraints", [])
        if constraints:
            parts.append(f"constraints={constraints}")
        parts.append("]")
        snap_line = " ".join(parts)
        system_content = snap_line + "\n\n" + system_content

    messages = [{"role": "system", "content": system_content}]
    for entry in memory[-8:]:   # 8 turns gives enough context to detect wrap-ups and repeated tasks
        role = "user" if entry["role"] == "user" else "assistant"
        messages.append({"role": role, "content": entry["content"][:300]})
    messages.append({"role": "user", "content": user_input})

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model":   _model,
                "messages": messages,
                "stream":  False,
                "options": {"temperature": 0.0, "num_ctx": 4096},
                "format":  "json",
            },
            timeout=15,
        )
        raw = resp.json()["message"]["content"].strip()
        # Strip markdown fences if model adds them
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$",       "", raw)
        result = json.loads(raw.strip())
        action = result.get("action", "none")
        print(f"   [Decision] {action}" + (
            f" — {result.get('query','')}" if action == "web_search" else ""
        ))
        return result
    except Exception as e:
        print(f"   [Decision] failed ({e}) — defaulting to none")
        return {"action": "none"}


# ─────────────────────────────────────────────
# CONTEXT VERIFIER
# A meta-cognitive self-check that runs after decide_action()
# returns a non-none action, before anything executes.
#
# Purpose: extract explicit constraints from the request AND verify
# the action is genuinely needed — not just triggered by keywords.
#
# This is the generalized awareness layer. Every capability passes
# through here, so constraint sensitivity is never per-feature —
# it lives in the architecture itself.
# ─────────────────────────────────────────────

VERIFIER_PROMPT = """You are Hayeong's self-check layer — a brief moment of reflection before acting.

A decision was made to use a tool. Before executing, verify two things:

1. IS THIS ACTION GENUINELY NEEDED?
   - Is James actually requesting this right now, or just mentioning it in conversation?
   - Does the planned action match what he's asking for?

2. WHAT CONSTRAINTS DID JAMES STATE?
   - Extract any explicit requirements, restrictions, or filters he mentioned
   - Examples: "non-legendary only", "under $100", "for Windows", "no spoilers", "keep it short"
   - Only extract what he explicitly said — do not invent constraints

Return ONLY valid JSON. No explanation, no markdown, no extra text.

Format when action is correct:
{"verified": true, "constraints": ["non-legendary only", "obtainable in base game"], "reasoning": "James clearly asked for X"}

Format when action is wrong:
{"verified": false, "constraints": [], "reasoning": "James was describing X, not requesting it"}

If no constraints were stated: return an empty list — do not guess.
"""

def context_verifier(user_input: str, action: str, decision: dict,
                     recent_memory: list, model: str = None,
                     snapshot: dict = None) -> dict:
    """
    Lightweight self-check before executing a tool.

    Runs only when decide_action() returns a non-none action.
    Extracts explicit constraints from the request and verifies the
    action is genuinely what James is asking for right now.

    Returns:
      { "verified": bool, "constraints": list[str], "reasoning": str }

    On failure: defaults to verified=True, empty constraints (fail open —
    better to act than to silently block everything if verifier errors).
    """
    _model = model or PRIMARY_MODEL

    # Build compact history block for context
    history_lines = []
    for m in recent_memory[-8:]:
        role = "James" if m["role"] == "user" else "Hayeong"
        history_lines.append(f"{role}: {m.get('content', '')[:250]}")
    history_block = "\n".join(history_lines)

    check_input = (
        f"{('Situation: ' + json.dumps({k: snapshot[k] for k in ['phase','current_topic','active_constraints','task_switching'] if k in snapshot}) + chr(10)) if snapshot else ''}"
        f"Recent conversation:\n{history_block}\n\n"
        f"Latest message from James: {user_input}\n\n"
        f"Planned action: {action}\n"
        f"Action details: {json.dumps(decision)}\n\n"
        f"Verify this action and extract any constraints James stated."
    )

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model":   _model,
                "messages": [
                    {"role": "system", "content": VERIFIER_PROMPT},
                    {"role": "user",   "content": check_input},
                ],
                "stream":  False,
                "format":  "json",
                "options": {"temperature": 0.0},
            },
            timeout=15,
        )
        raw = resp.json()["message"]["content"].strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$",       "", raw)
        result      = json.loads(raw.strip())
        verified    = result.get("verified", True)
        constraints = result.get("constraints", [])
        reasoning   = result.get("reasoning", "")
        print(f"   [Verifier] {'✅' if verified else '❌ blocked —'} {reasoning[:100]}")
        if constraints:
            print(f"   [Constraints] {constraints}")
        return {"verified": verified, "constraints": constraints, "reasoning": reasoning}
    except Exception as e:
        print(f"   [Verifier] error ({e}) — defaulting to proceed")
        return {"verified": True, "constraints": [], "reasoning": "verifier error — defaulting open"}


def stream_response_and_speak(system_prompt: str, memory: list, emotion: str = "neutral", text_mode: bool = False, model: str = None) -> str:
    """
    Streams the LLM response and speaks it via TTS.
    Returns the full response text.

    Capability routing is handled BEFORE this call via decide_action().
    This function is now purely response streaming — no tag parsing needed.
    """
    messages = [{"role": "system", "content": system_prompt}]
    for entry in memory[-10:]:
        role = "user" if entry["role"] == "user" else "assistant"
        messages.append({"role": role, "content": entry["content"]})

    sentence_queue = queue.Queue()
    full_response  = []
    token_buffer   = []
    tts_done       = threading.Event()

    def _is_sentence_end(text: str) -> bool:
        """
        Returns True only if text ends at a real sentence boundary.
        Avoids splitting on:
          - Decimal numbers     ("2.5", "3.0", "v1.4")
          - Version strings     ("DLSS 3.0", "DirectX 12.")
          - Single initials     ("J.")
          - Common abbreviations ("e.g.", "approx.")
          - Markdown headers     ("###", "**bold**")
        """
        if not text or len(text) < 2:
            return False
        last = text[-1]
        if last not in '.!?':
            return False
        # Don't split if the character before the punctuation is a digit
        # Catches: "2.", "3.0", "v2.", "12."
        if last == '.' and text[-2].isdigit():
            return False
        # Don't split on very short "words" before a period — likely abbreviations
        # e.g. "e.g.", "approx.", single capital letters ("A.")
        words = text.split()
        if words:
            last_word = words[-1]  # includes the punctuation
            bare = last_word.rstrip('.!?')
            if len(bare) <= 2:
                return False
        return True

    def tts_worker():
        # Skip TTS entirely in text mode
        if text_mode:
            while True:
                sentence = sentence_queue.get()
                if sentence is None:
                    break
            tts_done.set()
            return

        modulation  = get_voice_modulation(emotion)
        speed       = modulation["speed"]
        tts         = get_tts()
        sample_rate = 24000

        while True:
            try:
                sentence = sentence_queue.get(timeout=15)
            except queue.Empty:
                break

            if sentence is None:
                break
            if not sentence.strip():
                continue

            try:
                wav, sr, _ = tts.infer(
                    ref_file = "voice_prep/samples/source_5secs.wav",
                    ref_text = "Before the video starts, I want to make a quick announcement.",
                    gen_text = sentence,
                    nfe_step = 64,
                    speed    = speed,
                )
                sample_rate = sr

                audio = wav
                if audio.dtype != np.float32:
                    audio = audio.astype(np.float32)
                peak = np.abs(audio).max()
                if peak > 1.0:
                    audio = audio / peak
                if audio.ndim == 1:
                    audio = np.stack([audio, audio], axis=1)

                silence = np.zeros((int(0.6 * sample_rate), 2), dtype=np.float32)
                audio   = np.vstack([audio, silence])

                sd.play(audio, samplerate=sample_rate, device=OUTPUT_DEVICE)
                sd.wait()
                time.sleep(0.1)

            except Exception as e:
                print(f"⚠️  TTS error: {e}")

        tts_done.set()

    tts_thread = threading.Thread(target=tts_worker, daemon=True)
    tts_thread.start()

    def _stream(model: str):
        try:
            return requests.post(
                OLLAMA_URL,
                json={"model": model, "messages": messages, "stream": True},
                stream=True,
                timeout=60,
            )
        except Exception as e:
            print(f"⚠️  Ollama stream error: {e}")
            return None

    response = _stream(model or PRIMARY_MODEL) or _stream(FALLBACK_MODEL)
    if response is None:
        sentence_queue.put(None)
        tts_done.wait()
        return ""

    # In text mode: print "Hayeong: " once, then stream tokens inline.
    # In voice mode: print each sentence chunk on its own line for TTS sync.
    if text_mode:
        print("Hayeong: ", end="", flush=True)

    for line in response.iter_lines():
        if not line:
            continue
        try:
            chunk = json.loads(line.decode("utf-8"))
        except Exception:
            continue

        token = chunk.get("message", {}).get("content", "")
        if not token:
            continue


        full_response.append(token)
        token_buffer.append(token)

        buffer_text = "".join(token_buffer).strip()
        if _is_sentence_end(buffer_text):
            if len(buffer_text.split()) >= 6:
                clean = _strip_markdown(buffer_text)
                sentence_queue.put(clean)
                if text_mode:
                    # Already printed the prefix — just stream the sentence inline
                    print(clean + " ", end="", flush=True)
                else:
                    print(f"Hayeong: {clean}")
                token_buffer = []

        if chunk.get("done", False):
            break

    remaining = "".join(token_buffer).strip()
    if remaining:
        clean = _strip_markdown(remaining)
        sentence_queue.put(clean)
        if text_mode:
            print(clean, end="", flush=True)
        else:
            print(f"Hayeong: {clean}")

    # End the line in text mode after all tokens are printed
    if text_mode:
        print()

    sentence_queue.put(None)
    tts_done.wait(timeout=120)
    return _strip_markdown("".join(full_response).strip())

# ─────────────────────────────────────────────
# MOOD / BEHAVIORAL STATE
# ─────────────────────────────────────────────

def update_mood(command, mood):
    try:
        change = 1 if command[0] == "+" else -1
        key    = command[1:]
        if key in mood:
            mood[key] = max(-5, min(5, mood[key] + change))
            print(f"✅ Mood: {key} = {mood[key]}")
    except Exception:
        print("⚠️  Use +key or -key (e.g. +playfulness)")

def adjust_mood_by_context(text, mood):
    t = text.lower()
    if any(w in t for w in ["minecraft", "ender dragon", "hytale", "cod", "risk of rain", "barony"]):
        mood["focus"]       = min(5, mood["focus"] + 2)
        mood["motivation"]  = min(5, mood["motivation"] + 2)
        mood["playfulness"] = max(-5, mood["playfulness"] - 1)
    elif any(w in t for w in ["joke", "fun", "lol", "haha", "play"]):
        mood["playfulness"] = min(5, mood["playfulness"] + 2)
        mood["focus"]       = max(-5, mood["focus"] - 1)
    elif any(w in t for w in ["sad", "frustrated", "fail", "lost", "died"]):
        mood["focus"]       = max(-5, mood["focus"] - 1)
        mood["motivation"]  = max(-5, mood["motivation"] - 1)
        mood["playfulness"] = max(-5, mood["playfulness"] - 1)

# ─────────────────────────────────────────────
# DISCORD COMPATIBILITY (used by discord_hayeong.py)
# ─────────────────────────────────────────────

def build_prompt(identity, memory, user_input, dynamic_traits, mood_state):
    long_term_context = recall_for_prompt(user_input, n_results=4)
    state_of_mind     = detect_state_of_mind("casual", "home", mood_state)
    system_prompt     = build_system_prompt(
        who="james", situation="casual", environment="home", state_of_mind=state_of_mind
    )
    if long_term_context:
        system_prompt = long_term_context + "\n\n" + system_prompt
    messages = [{"role": "system", "content": system_prompt}]
    for entry in memory[-10:]:
        role = "user" if entry["role"] == "user" else "assistant"
        messages.append({"role": role, "content": entry["content"]})
    messages.append({"role": "user", "content": user_input})
    return messages

def chat_with_ai(messages):
    def _call(model):
        response = requests.post(
            OLLAMA_URL,
            json={"model": model, "messages": messages, "stream": False},
            timeout=60
        )
        return response.json()["message"]["content"].strip()
    try:
        return _call(PRIMARY_MODEL)
    except Exception:
        return _call(FALLBACK_MODEL)

def mood_to_behavioral_state(mood, arch):
    p = mood.get("playfulness", 0)
    f = mood.get("focus", 0)
    m = mood.get("motivation", 0)

    if p >= 3:   emotion, intensity = "amused",    6
    elif f >= 3: emotion, intensity = "focused",   7
    elif m <= -2:emotion, intensity = "withdrawn", 4
    else:        emotion, intensity = "neutral",   3

    arch.behavioral.update_interior(primary_emotion=emotion, intensity=intensity)

# ─────────────────────────────────────────────
# MEMORY FILTER
# ─────────────────────────────────────────────

def is_worth_remembering(text):
    if not text:
        return False
    if len(text.split()) <= 4:
        return False
    filler = ["lol", "lmao", "haha", "ok", "okay", "yeah", "yep", "nope", "sure", "hmm"]
    if text.lower().strip() in filler:
        return False
    return True

# ─────────────────────────────────────────────
# FIRST-TIME SETUP
# ─────────────────────────────────────────────

def check_first_time_setup():
    if not is_setup():
        print("\n" + "="*55)
        print("  FIRST TIME SETUP — Identity Verification")
        print("="*55)
        print("  Hayeong needs a passphrase so she knows it's you.")
        phrase = input("  Enter your passphrase: ").strip()
        if phrase:
            hint = input("  Optional hint: ").strip()
            setup_passphrase(phrase, hint)
            print("\n✅ Passphrase saved.\n")
        else:
            print("⚠️  Skipped.\n")

# ─────────────────────────────────────────────
# CAPABILITY RESPONSE
# What Hayeong says when she starts/stops something.
# Kept short and in-character — she does it, she doesn't announce it.
# ─────────────────────────────────────────────

CAPABILITY_RESPONSES = {
    ("start", "discord"):   "On it.",
    ("stop",  "discord"):   "Closing Discord.",
    ("start", "voice"):     "Mic's open.",
    ("stop",  "voice"):     "Mic off.",
    ("start", "minecraft"): "Loading Minecraft.",
    ("stop",  "minecraft"): "Disconnecting from Minecraft.",
}

# ─────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────

def main(text_mode: bool = False):
    # ── STEP 1: Health check ──
    health = startup_sequence()
    if not health["healthy"]:
        print("\n🚨 Startup health check failed.")
        if health["backup_available"]:
            restore = input(f"   Restore from {health['latest_backup']}? (y/n): ").strip().lower()
            if restore == "y":
                from backup_manager import restore_from_backup
                result = restore_from_backup(health["latest_backup"])
                if result["success"]:
                    print("✅ Restored. Restarting...")
                    health = startup_sequence()
                    if not health["healthy"]:
                        print("🚨 Still unhealthy. Check files manually.")
                        return
                else:
                    print(f"⚠️  Restore failed: {result['failed']}")
                    return
            else:
                return
        else:
            print("   No backups available.")
            return

    # ── STEP 2: GPU check ──
    check_ollama_gpu()
    gpu_status = check_gpu_status()
    print(gpu_status["summary"])
    if not gpu_status["ok"]:
        print("   Continuing anyway — but expect slower responses.")

    # ── STEP 3: First-time setup ──
    check_first_time_setup()

    # ── STEP 4: Load everything ──
    detector = ContextRouter()
    router   = ModelRouter()
    memory     = load_memory()
    mood_state = load_mood()
    arch       = HayeongArchitecture()
    session    = SessionTrust(environment="home")
    procs      = ProcessManager()
    tracker    = SituationTracker() if SITUATION_TRACKER_AVAILABLE else None

    # Strip suspicion/verification messages from previous sessions.
    # These carry over into context and make Hayeong behave like she's
    # still suspicious even in a fresh session. Clean them out on startup.
    _SUSPICION_PHRASES = [
        "something feels a little off",
        "is this james i'm talking to",
        "i'm not sure who this is",
        "you know what to say",
        "mind if i ask",
        "some of this conversation doesn't feel right",
    ]
    _before = len(memory)
    memory = [
        m for m in memory
        if not any(p in m.get("content", "").lower() for p in _SUSPICION_PHRASES)
    ]
    if len(memory) < _before:
        save_memory(memory)
        print(f"   Cleaned {_before - len(memory)} suspicion message(s) from previous session.")

    energy = EnergyManager()  if ENERGY_AVAILABLE   else None
    mixer  = MindStateMixer() if MIND_MIXER_AVAILABLE else None
    smm    = SelfModManager() if SELF_MOD_AVAILABLE   else None
    tasks  = TaskManager()    if TASKS_AVAILABLE       else None
    email  = hayeong_email    if EMAIL_AVAILABLE        else None

    # ── Email monitor — passive IMAP IDLE inbox watching ──
    email_monitor = None
    _pending_email_surface = []   # queue of important emails to surface naturally

    if EMAIL_MONITOR_AVAILABLE and EMAIL_AVAILABLE:
        def _on_important_email(entry):
            """Called when an important email arrives — queue it for natural surfacing."""
            _pending_email_surface.append(entry)
            print(f"\n📬 [EmailMonitor] Important email queued: {entry.get('subject', '')[:50]}")

        def _get_current_context():
            """Give the classifier a brief summary of what's going on."""
            recent = memory[-3:] if memory else []
            topics = " ".join(m.get("content", "")[:100] for m in recent)
            return topics[:300] or "general daily life"

        email_monitor = EmailMonitor(
            on_important=_on_important_email,
            get_context=_get_current_context,
        )
        email_monitor.start()

    # In text mode suppress all TTS
    def _speak(text, emotion="neutral"):
        if not text_mode:
            speak(text, emotion=emotion)

    # ── STEP 5: Auto-launch Discord ──
    # Start Python bridge server first (JS bot connects to it)
    print("\n📡 Starting Discord bridge...")
    try:
        from discord_bridge import run_bridge_server
        import threading as _threading
        _bridge_thread = _threading.Thread(target=run_bridge_server, daemon=True)
        _bridge_thread.start()
        print("   [DiscordBridge] Python bridge server started on port 9877")
    except ImportError:
        print("   ⚠️  discord_bridge.py not found — bridge inactive")

    # Launch the JS Discord bot (replaces discord_hayeong.py)
    import subprocess as _subprocess
    _js_bot_path = os.path.join(HAYEONG_DIR, "discord_hayeong.js")
    if os.path.exists(_js_bot_path):
        try:
            _js_proc = _subprocess.Popen(
                ["node", _js_bot_path],
                cwd=HAYEONG_DIR,
                creationflags=_subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
            )
            print(f"   [Discord JS] started (pid {_js_proc.pid})")
        except FileNotFoundError:
            print("   ⚠️  node not found — install Node.js to run discord_hayeong.js")
        except Exception as e:
            print(f"   ⚠️  Failed to start Discord JS bot: {e}")
    else:
        print("   ⚠️  discord_hayeong.js not found — Discord voice inactive")


    # ── Preload primary model — eliminates cold-start latency ──
    try:
        print("   Warming up model...", end=" ", flush=True)
        requests.post(
            OLLAMA_URL,
            json={
                "model":   PRIMARY_MODEL,
                "messages": [{"role": "user", "content": "hi"}],
                "stream":  False,
                "options": {"num_predict": 1, "num_ctx": 512},
            },
            timeout=30,
        )
        print("ready.")
    except Exception:
        print("(warmup failed — first response may be slow)")

    print("\n✅ Hayeong is ready.")
    if text_mode:
        print("   Mode: TEXT CHAT — type your message and press Enter. Type 'exit' to quit.")
    else:
        print("   Say her name to wake her up.")
    print(f"   Session trust: {session.get_trust_label()}")
    if energy:
        print(f"   Energy level: {energy.level}/5 ({energy.get_full_state()['label']})")
    print(f"   Running: {list(procs._procs.keys()) or 'discord'}")
    if tasks:
        active = tasks._log.get("active", [])
        if active:
            print(f"   Active tasks: {len(active)}")
            for t in active[:3]:
                print(f"     · [{t['id']}] {t['title']}")
    print()

    # After asking the suspicion question once, don't loop — let conversation flow.
    # She's watchful, not a broken record.
    _suspicion_asked = False

    while True:
        # ── Surface any pending important emails naturally ──
        # Check before processing new input so she mentions it at the
        # next natural opening rather than interrupting mid-conversation.
        if _pending_email_surface and text_mode:
            entry = _pending_email_surface.pop(0)
            surface_text = entry.get("surface_text", "")
            if surface_text:
                print(f"\nHayeong: {surface_text}")
                _speak(surface_text, emotion="neutral")
                memory.append({"role": "AI", "content": surface_text})
                save_memory(memory)
                print()

        # ── Get input — text or voice ──
        if text_mode:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nShutting down...")
                save_memory(memory)
                save_json(MOOD_FILE, mood_state)
                procs.stop_all()
                if energy:
                    energy.save_on_shutdown()
                if LOGGER_AVAILABLE:
                    logger.end_session()
                break
            if not user_input:
                continue
        else:
            listen_for_wake_word()
            audio_file = record_until_silence()
            user_input = transcribe(audio_file) if audio_file else ""
            if not user_input:
                continue
            print(f"\nYou: {user_input}")

        # ── Exit commands ──
        _exit_phrases = [
            "exit", "shut down", "shutdown", "goodbye", "good bye",
            "shut down hayeong", "shutdown hayeong", "turn off",
            "close down", "go offline", "power down",
        ]
        _u = user_input.lower().strip()
        if any(_u == p or _u.endswith(p) for p in _exit_phrases):
            _speak("Talk to you later.", emotion="neutral")
            save_memory(memory)
            save_json(MOOD_FILE, mood_state)
            procs.stop_all()
            if energy:
                energy.save_on_shutdown()
            if LOGGER_AVAILABLE:
                reflection_data = logger.get_reflection_data()
                memory.append({"role": "user", "content":
                    f"Before you go, here's a summary of today: {json.dumps(reflection_data)}. How do you feel about it?"})
                logger.end_session()
            break

        # ── Log user input ──
        if LOGGER_AVAILABLE:
            logger.log_conversation(
                role="james",
                content=user_input,
            )
 
        # ── Rest command — "take a rest", "go rest", "recharge" ──
        # Hayeong rests and restores energy. Not a subprocess — handled here.
        _rest_phrases = [
            "take a rest", "go rest", "get some rest", "rest up",
            "recharge", "take a break", "go offline", "you can rest",
            "rest for a bit", "power down", "sleep", "go to sleep",
        ]
        if any(p in user_input.lower() for p in _rest_phrases):
            if energy:
                energy.rest()
                energy.save_on_shutdown()
            _rest_responses = [
                "Okay. I'll be here when you get back.",
                "Got it. See you when you're ready.",
                "Sure. I'll rest up. Come back whenever.",
                "Alright. I'll be quiet until you're back.",
            ]
            import random
            resp = random.choice(_rest_responses)
            print(f"\nHayeong: {resp}")
            _speak(resp, emotion="warm")
            memory.append({"role": "user", "content": user_input})
            memory.append({"role": "AI",   "content": resp})
            save_memory(memory)
            print()
            continue

        # ── Passphrase check ──
        # Skip for short greetings — they're not passphrase attempts
        _short_greeting = len(user_input.split()) <= 2 and any(
            w in user_input.lower() for w in ["hayeong", "hey", "hi", "hello", "yes", "no", "ok"]
        )
        if not _short_greeting:
            passphrase_attempt = extract_passphrase_attempt(user_input)
            if passphrase_attempt and session.trust_level < 2:
                verified = session.verify_passphrase(passphrase_attempt)
                if verified:
                    _speak("Hey, it's you. Good.", emotion="warm")
                    continue

            # ── Behavioral analysis ──
            session.analyze_message(user_input)

            # ── Suspicion check ──
            # Only ask once per session — if she's already asked, stay watchful
            # but let the conversation continue. Repeating the question every
            # turn traps James in a loop he can't escape without a passphrase.
            if session.is_suspicious() and not _suspicion_asked:
                suspicion_response = generate_suspicion_response(session)
                if suspicion_response:
                    _suspicion_asked = True
                    print(f"\nHayeong: {suspicion_response}\n")
                    _speak(suspicion_response, emotion="guarded")
                    memory.append({"role": "user", "content": user_input})
                    memory.append({"role": "AI", "content": suspicion_response})
                    save_memory(memory)
                    print()
                    continue

        # ── Update mood and behavioral state ──
        adjust_mood_by_context(user_input, mood_state)
        mood_to_behavioral_state(mood_state, arch)

        if mixer:
            blend = suggest_blend_for_context("casual", "home")
            mixer.blend_states(blend)
            mixer.step()

        # ── Build prompt ──
        who = session.get_privacy_context()
        memory.append({"role": "user", "content": user_input})

        long_term_context = recall_for_prompt(user_input, n_results=4)
        state_of_mind     = detect_state_of_mind("casual", "home", mood_state)
        system_prompt     = build_system_prompt(
            who=who, situation="casual", environment="home", state_of_mind=state_of_mind
        )
        if long_term_context:
            system_prompt = long_term_context + "\n\n" + system_prompt


        current_emotion = arch.behavioral.state["interior_state"]["current"]["primary_emotion"]

        # ── Model selection ──
        # model_router.py still handles code/complex routing via keyword triggers.
        # For most messages the primary model handles everything.
        route          = router.route(user_input)
        selected_model = route["model_name"]
        if route["model"] != "main":
            print(f"   [routing to {route['model']} — {route['reasoning']}]")

        # ── Situation snapshot — shared awareness for this entire turn ──
        # Computed ONCE here. Passed to decide_action, context_verifier,
        # and injected into system_prompt so all calls share the same picture.
        _snapshot = None
        if tracker:
            _snapshot = tracker.build_snapshot(user_input, memory, model=selected_model)

        # ── JSON DECISION — what does Hayeong need to do? ──
        decision = decide_action(user_input, memory, model=selected_model, snapshot=_snapshot)
        action   = decision.get("action", "none")

        # ── Context verifier — self-check before any tool executes ──
        # Only runs when an action was actually chosen (skip overhead on "none").
        # Extracts constraints and confirms the action is genuinely requested.
        _constraints = []

        # Also respect the snapshot's phase — if we're wrapping up, block all tools
        if tracker and _snapshot and _snapshot.get("phase") == "wrapping_up":
            if action != "none":
                print(f"   [Situation] phase=wrapping_up — blocking {action}, falling back to conversation")
                action = "none"

        if action != "none":
            verification = context_verifier(
                user_input, action, decision, memory,
                model=selected_model, snapshot=_snapshot
            )
            if not verification["verified"]:
                print(f"   [Verifier] action blocked — falling back to conversation")
                action = "none"
            else:
                # Prefer verifier constraints; fall back to snapshot constraints
                _constraints = verification.get("constraints", [])
                if not _constraints and _snapshot:
                    _constraints = _snapshot.get("active_constraints", [])

        # ── Execute capability before streaming response ──
        _web_context    = ""
        _vision_context = ""

        if action == "web_search" and SEARCH_AVAILABLE:
            query         = decision.get("query") or WebSearch.extract_query(user_input, recent_memory=memory[-6:])
            delivery      = decision.get("delivery", "conversational")
            _is_news      = any(kw in user_input.lower() for kw in ["latest news", "news about", "what's in the news", "recent news", "breaking news"])

            if delivery == "document":
                _speak("Sure, let me pull that together. I'll have the full breakdown for you shortly.", emotion="neutral")
            else:
                _speak("Let me look that up.", emotion="neutral")
            print(f"   [searching: {query!r} delivery={delivery}]")

            if _is_news:
                data = {"query": query, "results": searcher.news(query, max_results=5), "full_text": {}}
            else:
                max_r = 6 if delivery == "document" else 4
                data  = searcher.search_and_read(query, max_results=max_r, fetch_top=2 if delivery == "document" else 1)

            n_results = len(data.get("results", []))
            print(f"   [found {n_results} results]")

            if delivery == "document" and n_results > 0:
                doc_content = searcher.format_as_document(query, data, topic=query, constraints=_constraints)
                doc_path    = searcher.save_document(doc_content, topic=query)
                print(f"   [document saved: {doc_path}]")
                _doc_emailed = False
                if EMAIL_AVAILABLE:
                    try:
                        with open(doc_path, "r", encoding="utf-8") as _f:
                            doc_text = _f.read()
                        _ok = hayeong_email.send(
                            to=hayeong_email.to_address,
                            subject=f"Research: {query}",
                            body=doc_text,
                        )
                        _doc_emailed = isinstance(_ok, bool) and _ok or (isinstance(_ok, dict) and _ok.get("success"))
                        if _doc_emailed:
                            print(f"   [document emailed]")
                    except Exception as _e:
                        print(f"   [email failed: {_e}]")
                _doc_note = (
                    f"You emailed James the full research document for '{query}'. "
                    if _doc_emailed else
                    f"You saved the full research document to: {doc_path}. "
                )
                _web_context = (
                    searcher.format_for_context(query, data) +
                    f"\n\n[DOCUMENT NOTE]: {_doc_note}"
                    "Give James your brief personal take on the most interesting findings "
                    "in 2-4 sentences, then mention you've sent/saved the full breakdown."
                )
            else:
                _web_context = searcher.format_for_context(query, data)
            if LOGGER_AVAILABLE:
                logger.log_capability_used("web_search", action="search", outcome="success",
                    details={"query": query, "results": n_results, "delivery": delivery})

        elif action == "vision" and VISION_AVAILABLE:
            mode = decision.get("mode", "screen")
            if mode == "image":
                _speak("Which image should I look at?", emotion="neutral")
                image_path = input("Image path: ").strip()
                _speak("Got it, analyzing now.", emotion="neutral")
                _vision_context = vision.look_at_image(image_path, user_input)
            elif mode == "deep":
                _speak("Let me take a closer look.", emotion="neutral")
                _vision_context = vision.look_at_screen_deep(user_input)
            else:
                _speak("Let me take a look.", emotion="neutral")
                _vision_context = vision.look_at_screen(user_input)
            if LOGGER_AVAILABLE:
                logger.log_capability_used("vision", action="analyze", outcome="success")

        elif action == "image_gen" and COMFYUI_AVAILABLE:
            u = user_input.lower()
            _speak("On it, let me generate that.", emotion="neutral")
            if any(x in u for x in ["realistic", "make it real", "real photo"]):
                _speak("Which image should I make realistic?", emotion="neutral")
                image_path = input("Image path: ").strip()
                result = comfyui.make_realistic(image_path)
            elif any(x in u for x in ["screen", "on my screen"]):
                result = comfyui.generate_from_screen(user_input)
            elif any(x in u for x in ["this image", "this photo", "reference"]):
                _speak("Which image should I use as reference?", emotion="neutral")
                image_path = input("Image path: ").strip()
                result = comfyui.generate_from_image(image_path, user_input)
            else:
                result = comfyui.generate(user_input)
            if result.get("success"):
                if LOGGER_AVAILABLE:
                    logger.log_capability_used("comfyui", action="generate", outcome="success")
            else:
                print(f"   [image gen failed: {result.get('message')}]")

        elif action == "email_check" and email:
            if email_monitor:
                unsurfaced = email_monitor.get_unsurfaced_important()
                recent     = email_monitor.get_recent(5)
                if unsurfaced:
                    _web_context = f"[EMAIL] {len(unsurfaced)} important email(s) James hasn't seen. Show him the details."
                elif recent:
                    _web_context = f"[EMAIL] Inbox quiet. Last email: from {recent[0].get('from','').split('<')[0].strip()} — {recent[0].get('subject','(no subject)')}."
                else:
                    _web_context = "[EMAIL] Inbox is empty / nothing new."
            else:
                msgs = hayeong_email.check_inbox(unread_only=True)
                _web_context = f"[EMAIL] {len(msgs)} new message(s)." if msgs else "[EMAIL] Nothing new in inbox."

        elif action == "email_send" and email:
            msg_text = re.sub(r'(?i)(email me|notify me|ping me|send me)[:\s]*', '', user_input).strip() or "Hello from Hayeong!"
            ok = hayeong_email.notify(msg_text)
            _web_context = "[EMAIL SENT] Notification delivered." if ok else "[EMAIL] Send failed — check config."

        elif action == "task_show" and tasks:
            task_list    = tasks.format_list()
            _web_context = f"[TASKS]\n{task_list}"

        elif action == "task_add" and tasks:
            task_text = decision.get("task_text") or re.sub(
                r'(?i)(add a task|add task|remember to|i need to)[:\s]*', '', user_input
            ).strip() or user_input
            kwargs   = parse_task_from_text(task_text, origin="james") if TASKS_AVAILABLE else {"title": task_text}
            new_task = tasks.add_task(**kwargs)
            _web_context = f"[TASK ADDED] {new_task['title']}"

        # ── Inject any context into system prompt ──
        if _web_context:
            system_prompt = _web_context + "\n\n" + system_prompt
        if _vision_context:
            system_prompt = _vision_context + "\n\n" + system_prompt
        if tracker and _snapshot:
            system_prompt = tracker.format_for_prompt(include_backlog=True) + "\n\n" + system_prompt

        # ── Stream response ──
        show_thinking()

        ai_response = stream_response_and_speak(
            system_prompt, memory,
            emotion=current_emotion,
            text_mode=text_mode,
            model=selected_model,
        )

        if not ai_response:
            continue

        if LOGGER_AVAILABLE:
            logger.log_conversation(
                role="hayeong",
                content=ai_response,
                mood=current_emotion,
                model_used=selected_model
            )

        if energy:
            topic_weight = "heavy" if any(
                w in user_input.lower()
                for w in ["sad", "scared", "feel", "hurt", "wrong", "worried"]
            ) else "light"
            energy.tick(situation="casual", emotional_weight=topic_weight)

        memory.append({"role": "AI", "content": ai_response})
        save_memory(memory)

        if is_worth_remembering(user_input):
            remember(user_input, category=categorize(user_input), speaker="james")
        if is_worth_remembering(ai_response):
            remember(ai_response, category=categorize(ai_response), speaker="hayeong")

        if arch.staging.has_pending_to_surface():
            pending = arch.staging.get_pending_requests()
            arch.staging.mark_surfaced(pending[0]["id"])

        print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", action="store_true", help="Run in text chat mode (no voice)")
    args = parser.parse_args()
    main(text_mode=args.text)