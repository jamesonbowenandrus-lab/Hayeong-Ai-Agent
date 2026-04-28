# main.py
# Hayeong — brain and process supervisor.
#
# This is the one thing you run. Everything else — voice, Minecraft —
# she starts herself when she decides to, or when you ask her to.
#
# Architecture:
#   main.py  ←── always running (her consciousness + text chat)
#     ├── on request:    voice_ptt.py        ("open your mic")
#     ├── on request:    minecraft_bridge.py ("load minecraft")
#     └── monitors all: restarts if crashed
#
# To start everything: just run main.py. That's it.

# ── Singleton lock — only one instance of Hayeong may run at a time ──
import sys as _sys
try:
    from filelock import FileLock, Timeout
    _lock = FileLock("hayeong.lock", timeout=0)
    _lock.acquire()
except ImportError:
    print("⚠️  filelock not installed — run: pip install filelock")
    _sys.exit(1)
except Timeout:
    print("Hayeong is already running.")
    _sys.exit(1)

import requests
import re
import json
import os
import time
import threading
import queue
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from context_router import check_gpu_status
from model_router import ModelRouter

# sounddevice — only needed for voice mode; import safely so a device failure
# doesn't crash the whole process in text/brain mode
try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except Exception as _sd_err:
    sd = None
    SOUNDDEVICE_AVAILABLE = False
    print(f"⚠️  sounddevice unavailable ({_sd_err}) — voice input disabled")

# voice — wrapped so a Kokoro/Whisper/espeak failure never crashes main.py
# All symbols get safe stubs when unavailable so the rest of the file compiles.
try:
    from voice import (
        transcribe, speak, listen_for_wake_word,
        record_seconds, get_volume, show_thinking,
        SAMPLE_RATE, INPUT_DEVICE, VOLUME_THRESHOLD,
        split_sentences, get_pipeline, get_tts,
        KOKORO_AVAILABLE, F5TTS_AVAILABLE,
        HAYEONG_VOICE, get_voice_modulation,
        REF_AUDIO, REF_TEXT,
        OUTPUT_DEVICE,
    )
    VOICE_AVAILABLE = True
except Exception as _voice_err:
    VOICE_AVAILABLE     = False
    KOKORO_AVAILABLE    = False
    F5TTS_AVAILABLE     = False
    SAMPLE_RATE         = 16000
    INPUT_DEVICE        = None
    OUTPUT_DEVICE       = None
    VOLUME_THRESHOLD    = 0.01
    HAYEONG_VOICE       = "af_heart"
    REF_AUDIO           = None
    REF_TEXT            = None
    def transcribe(f):            return ""
    def speak(text, emotion="neutral"): pass
    def listen_for_wake_word():   pass
    def record_seconds(n):        return None
    def get_volume(chunk):        return 0.0
    def show_thinking():          pass
    def split_sentences(text):    return [text]
    def get_pipeline():           return None
    def get_tts():                return None
    def get_voice_modulation(e):  return {"speed": 1.0, "pitch": 1.0}
    print(f"⚠️  Voice unavailable ({_voice_err}) — text/brain mode only")
from long_term_memory import recall_for_prompt, remember, categorize, import_from_memory_json
from system_prompt_builder import build_system_prompt, detect_state_of_mind
from hayeong_architecture import HayeongArchitecture
from backup_manager import startup_sequence
from identity_verification import (
    SessionTrust, is_setup, setup_passphrase,
    extract_passphrase_attempt, generate_suspicion_response
)

try:
    from async_presence import PresenceLayer, detect_intent, build_process_fn
    ASYNC_PRESENCE_AVAILABLE = True
except ImportError:
    ASYNC_PRESENCE_AVAILABLE = False
    print("⚠️  async_presence.py not found — synchronous mode only")

try:
    from app_manager import get_app_manager
    APP_MANAGER_AVAILABLE = True
except ImportError:
    APP_MANAGER_AVAILABLE = False
    print("⚠️  app_manager.py not found — process management inactive")

try:
    from capability_loader import get_loader
    CAPABILITY_LOADER_AVAILABLE = True
except ImportError:
    CAPABILITY_LOADER_AVAILABLE = False
    print("⚠️  capability_loader.py not found — using legacy dispatch")

try:
    from situation_tracker import (
        SituationTracker,
        format_snapshot_for_decision,
        format_snapshot_for_verifier,
    )
    SITUATION_TRACKER_AVAILABLE = True
except ImportError:
    SITUATION_TRACKER_AVAILABLE = False
    format_snapshot_for_decision = lambda s: ""
    format_snapshot_for_verifier = lambda s: ""
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
    from hayeong_logger import HayeongLogger
    logger = HayeongLogger()
    LOGGER_AVAILABLE = True
except ImportError:
    logger = None
    LOGGER_AVAILABLE = False
    print("⚠️  hayeong_logger.py not found — logging inactive")

try:
    from presence_governor import is_james_present, get_mode as get_presence_mode, start_monitoring as start_presence_monitoring
    PRESENCE_GOVERNOR_AVAILABLE = True
except ImportError:
    PRESENCE_GOVERNOR_AVAILABLE = False
    is_james_present = lambda: True   # safe fallback — assume present, never run background tasks
    get_presence_mode = lambda: "present"

try:
    from rollback_manager import RollbackManager
    rollback = RollbackManager()
    ROLLBACK_AVAILABLE = True
    print("   [Rollback] Audit log active")
except ImportError:
    rollback = None
    ROLLBACK_AVAILABLE = False

try:
    from filler_system import FillerTimer
    FILLER_AVAILABLE = True
except ImportError:
    FILLER_AVAILABLE = False

try:
    from income_manager import IncomeManager
    income_mgr = IncomeManager()
    INCOME_AVAILABLE = True
    print(f"   [Income] {income_mgr.summary().splitlines()[0]}")
    _income_pending = income_mgr.get_pending_proposals()
    if _income_pending:
        print(f"   [Income] {len(_income_pending)} proposal(s) waiting for your review.")
    # Auto-generate last month's summary on the 1st of each month
    from datetime import date as _date
    if _date.today().day == 1:
        try:
            import calendar as _cal
            _today     = _date.today()
            _prev_m    = _today.month - 1 or 12
            _prev_y    = _today.year if _today.month > 1 else _today.year - 1
            _sum_path  = income_mgr.generate_monthly_summary(_prev_y, _prev_m)
            if _sum_path:
                print(f"   [Income] Monthly summary generated: {_sum_path}")
        except Exception as _e:
            print(f"   [Income] Summary generation error: {_e}")
except ImportError:
    income_mgr = None
    INCOME_AVAILABLE = False

from hayeong_core import (
    save_json,
    load_memory, save_memory,
    load_identity, load_mood,
    build_prompt, chat_with_ai,
    adjust_mood_by_context,
    is_worth_remembering,
    _strip_markdown,
    infer_emotion_fast,
    update_mood,
    MOOD_FILE, FALLBACK_MODEL,
    COMMUNICATION_URL, COMMUNICATION_MODEL,
    REASONING_URL, REASONING_MODEL,
)

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

IDENTITY_FILE  = "identity.json"
HAYEONG_DIR    = os.path.dirname(os.path.abspath(__file__))

VAD_SILENCE_SECONDS = 1.2
VAD_MAX_SECONDS     = 12
VAD_CHUNK_SECONDS   = 0.4

# ─────────────────────────────────────────────
# WRAP-UP FAST PATH
# Detects thank-you / acknowledgment / close-out messages before
# any LLM call runs. These signals are unambiguous — running them
# through snapshot + decide_action + verifier wastes GPU cycles and
# introduces failure risk (as seen: all three layers misfired on
# "Thank you very much!").
#
# Same principle as capability fast-paths:
# when the signal is clear enough, don't ask an LLM.
# ─────────────────────────────────────────────

_WRAPUP_EXACT = {
    "thanks", "thank you", "ty", "thx", "cheers",
    "perfect", "great", "awesome", "nice", "cool",
    "sounds good", "looks good", "that's good", "that works",
    "got it", "understood", "noted",
}

_WRAPUP_CONTAINS = [
    "thank you", "thank you very much", "thanks a lot", "thanks so much",
    "great job", "good job", "nice work", "well done", "good work",
    "that's all i needed", "that's all for now", "that's perfect",
    "this is great", "this is perfect", "this is helpful", "this helps",
    "gives me great info", "gives me what i need",
    "i'll check it out", "i'll look it over", "i'll review it",
    "no that's all", "nothing else", "that'll do",
    "you're welcome", "appreciate it", "appreciate that",
]

def is_wrap_up(text: str) -> bool:
    """
    Returns True if the message is clearly a wrap-up / acknowledgment
    and no tool should fire regardless of conversation context.

    Intentionally conservative — only matches clear positive closings.
    Does NOT catch things like "thanks but can you also search X"
    because those have additional content after the thank-you.
    """
    t = text.lower().strip().rstrip("!.,")
    # Exact short matches
    if t in _WRAPUP_EXACT:
        return True
    # Contains check — but only if the message is short enough
    # that there's no real request hiding in it
    # (under ~120 chars = likely just an acknowledgment)
    if len(text) < 120:
        for phrase in _WRAPUP_CONTAINS:
            if phrase in t:
                return True
    return False


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

# ─────────────────────────────────────────────
# JSON DECISION ENGINE
# A fast non-streaming call that asks Hayeong what she needs to do
# before she responds. Returns a structured action dict.
# This replaces the fragile [USE:xxx] first-line tag system.
#
# Design: one small focused call → clean parseable JSON → then stream
# the full natural response with zero parsing complexity.
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# DECISION PROMPT — built dynamically from capability_registry.json
# When new capabilities are added to the registry, this updates
# automatically. main.py never needs to change for new capabilities.
# ─────────────────────────────────────────────

def build_decision_prompt() -> str:
    """
    Build the decision engine prompt from capability_registry.json.
    The "Available actions" section is generated from registry entries
    that have an "actions" field, using "action_hints" or "decision_hint"
    for per-action descriptions.
    """
    registry_path = os.path.join(HAYEONG_DIR, "capability_registry.json")
    action_lines  = []

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)

        for section in ("built_in_capabilities", "self_generated_capabilities"):
            for cap in registry.get(section, {}).get("capabilities", []):
                if cap.get("status") != "active":
                    continue
                actions = cap.get("actions", [])
                if not actions:
                    continue

                # Per-action hints take priority over a single decision_hint
                action_hints = cap.get("action_hints", {})
                fallback     = cap.get("decision_hint", cap.get("description", ""))

                for action in actions:
                    hint = action_hints.get(action, fallback)
                    action_lines.append(f"  {action:<14}— {hint}")

    except Exception as e:
        print(f"   [DecisionPrompt] failed to load registry: {e}")

    action_lines.append(f"  {'think_together':<14}— Request is ambiguous or James is thinking aloud — stay in conversation to align before acting")
    action_lines.append(f"  {'none':<14}— Normal conversation, no capability needed")
    actions_section = "\n".join(action_lines)

    return f"""You are Hayeong's decision engine.

Based on the conversation and the latest message from James, decide what action (if any) is needed before you respond.

Available actions:
{actions_section}

Return ONLY valid JSON. No explanation, no markdown, no extra text.

Examples:
  {{"action": "none"}}
  {{"action": "web_search", "query": "zapmander vs whale pup Once Human", "delivery": "document"}}
  {{"action": "web_search", "query": "RTX 5090 price", "delivery": "conversational"}}
  {{"action": "email_check"}}
  {{"action": "task_add", "task_text": "fix the voice bot"}}
  {{"action": "vision", "mode": "screen"}}
  {{"action": "image_gen", "prompt": "Hayeong in the orange frog jacket"}}
  {{"action": "app_start", "app_id": "comfyui"}}

CRITICAL RULES — read carefully:
  - WRAP-UP DETECTION: If James says "thanks", "that's all", "sounds good", "got it",
    "perfect", "nice work", "great", "I'll check it out", "no that's all", or any positive
    acknowledgment after a task was just completed → ALWAYS return none. The task is done.
    Check the last 2 turns — if a capability just ran and James is reacting positively → none.
    Never re-run a just-completed action.
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

DECISION_PROMPT = build_decision_prompt()


def _quick_intent(text: str) -> str:
    """Fast keyword intent for filler category — no LLM call."""
    t = text.lower()
    if any(w in t for w in ["search", "look up", "find", "what is", "news"]):
        return "search"
    if any(w in t for w in ["look at", "screen", "see", "image", "generate"]):
        return "vision"
    if any(w in t for w in ["task", "remind", "add", "show tasks"]):
        return "task"
    if any(w in t for w in ["minecraft", "mine", "craft", "build", "dig",
                              "farm", "chest", "inventory", "base"]):
        return "task"   # acknowledgment — heard, on it
    return "generic"


def decide_action(user_input: str, memory: list, model: str = None,
                  snapshot: dict = None) -> dict:
    """
    Fast JSON decision call — determines what capability (if any) Hayeong
    needs to invoke before responding. Non-streaming, focused, fast.
    Routes to the Reasoning LLM (14b, port 11435).

    Returns a dict like:
      {"action": "none"}
      {"action": "web_search", "query": "...", "delivery": "conversational"}
      {"action": "email_check"}
    """
    _model = model or REASONING_MODEL

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
    snap_line = format_snapshot_for_decision(snapshot)
    if snap_line:
        system_content = snap_line + "\n\n" + system_content

    messages = [{"role": "system", "content": system_content}]
    for entry in memory[-8:]:   # 8 turns gives enough context to detect wrap-ups and repeated tasks
        role = "user" if entry["role"] == "user" else "assistant"
        messages.append({"role": role, "content": entry["content"][:300]})
    messages.append({"role": "user", "content": user_input})

    try:
        resp = requests.post(
            REASONING_URL,
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
    _model = model or REASONING_MODEL

    # Build compact history block for context
    history_lines = []
    for m in recent_memory[-8:]:
        role = "James" if m["role"] == "user" else "Hayeong"
        history_lines.append(f"{role}: {m.get('content', '')[:250]}")
    history_block = "\n".join(history_lines)

    snap_line = format_snapshot_for_verifier(snapshot)
    check_input = (
        f"{snap_line + chr(10) if snap_line else ''}"
        f"Recent conversation:\n{history_block}\n\n"
        f"Latest message from James: {user_input}\n\n"
        f"Planned action: {action}\n"
        f"Action details: {json.dumps(decision)}\n\n"
        f"Verify this action and extract any constraints James stated."
    )

    try:
        resp = requests.post(
            REASONING_URL,
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
            timeout=20,
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


def stream_response_and_speak(system_prompt: str, memory: list, emotion: str = "neutral", text_mode: bool = False, model: str = None, cancel_filler_fn=None) -> str:
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

    # ── Three-thread pipeline ──
    # Thread 1 (main): token consumer + sentence detector  → sentence_queue
    # Thread 2:        TTS synthesizer                     → audio_queue
    # Thread 3:        audio playback                      (blocks on sd.wait, not TTS)
    #
    # No thread blocks another — synthesizer doesn't wait for playback to finish,
    # and playback doesn't wait for the next sentence to be synthesized.
    # First word reaches the speaker as soon as Sentence 1 is synthesized,
    # regardless of how long the full response takes.

    sentence_queue  = queue.Queue()
    audio_queue     = queue.Queue(maxsize=2)   # cap at 2 pre-synthesized chunks
    full_response   = []
    token_buffer    = []
    tts_done        = threading.Event()
    _first_token    = [True]    # cancelled once, then ignored
    # Emotion detected from response content — updated on first sentence,
    # read by synthesizer per sentence. Mutable list so closure can write to it.
    _emotion_live   = [emotion]
    _first_sentence = [True]    # flag: fast inference runs once on sentence 1 only

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
        if last == '.' and text[-2].isdigit():
            return False
        words = text.split()
        if words:
            last_word = words[-1]
            bare = last_word.rstrip('.!?')
            if len(bare) <= 2:
                return False
        return True

    def _synthesize(sentence: str, speed: float, sample_rate: int) -> np.ndarray | None:
        """Generate audio for one sentence. Returns float32 stereo array or None."""
        chunks = []
        if KOKORO_AVAILABLE:
            pipeline = get_pipeline()
            if pipeline is not None:
                try:
                    for _, _, audio in pipeline(sentence, voice=HAYEONG_VOICE, speed=speed):
                        chunks.append(audio)
                except Exception as e:
                    print(f"⚠️  Kokoro error: {e}")
        if not chunks and F5TTS_AVAILABLE:
            tts = get_tts()
            if tts is not None:
                try:
                    wav, sr, _ = tts.infer(
                        ref_file=REF_AUDIO, ref_text=REF_TEXT,
                        gen_text=sentence, nfe_step=64, speed=speed,
                    )
                    chunks.append(wav)
                    sample_rate = sr
                except Exception as e:
                    print(f"⚠️  F5-TTS error: {e}")
        if not chunks:
            return None
        audio = np.concatenate(chunks)
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        peak = np.abs(audio).max()
        if peak > 1.0:
            audio = audio / peak
        if audio.ndim == 1:
            audio = np.stack([audio, audio], axis=1)
        silence = np.zeros((int(0.6 * sample_rate), 2), dtype=np.float32)
        return np.vstack([audio, silence])

    def tts_synthesizer():
        """Thread 2: pulls sentences, synthesizes audio, pushes to audio_queue."""
        if text_mode:
            while sentence_queue.get() is not None:
                pass
            audio_queue.put(None)
            return

        while True:
            try:
                sentence = sentence_queue.get(timeout=15)
            except queue.Empty:
                break
            if sentence is None:
                audio_queue.put(None)
                break
            if not sentence.strip():
                continue
            # Use the live emotion (may have been updated by first-sentence inference)
            speed = get_voice_modulation(_emotion_live[0])["speed"]
            audio = _synthesize(sentence, speed, 24000)
            if audio is not None:
                audio_queue.put(audio)   # blocks if queue full — back-pressure

    def playback_worker():
        """Thread 3: pulls synthesized audio chunks and plays them sequentially."""
        while True:
            try:
                audio = audio_queue.get(timeout=20)
            except queue.Empty:
                break
            if audio is None:
                break
            try:
                sd.play(audio, samplerate=24000, device=OUTPUT_DEVICE)
                sd.wait()
                time.sleep(0.1)
            except Exception as e:
                print(f"⚠️  Playback error: {e}")
        tts_done.set()

    synth_thread    = threading.Thread(target=tts_synthesizer, daemon=True)
    playback_thread = threading.Thread(target=playback_worker,  daemon=True)
    synth_thread.start()
    playback_thread.start()

    def _stream(model: str):
        try:
            return requests.post(
                COMMUNICATION_URL,
                json={"model": model, "messages": messages, "stream": True},
                stream=True,
                timeout=60,
            )
        except Exception as e:
            print(f"⚠️  Ollama stream error: {e}")
            return None

    response = _stream(model or COMMUNICATION_MODEL) or _stream(FALLBACK_MODEL)
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

        # Cancel filler gate on first token — LLM has started responding
        if _first_token[0]:
            if cancel_filler_fn is not None:
                cancel_filler_fn()
            _first_token[0] = False

        full_response.append(token)
        token_buffer.append(token)

        buffer_text = "".join(token_buffer).strip()
        if _is_sentence_end(buffer_text):
            if len(buffer_text.split()) >= 6:
                clean = _strip_markdown(buffer_text)
                # Fast emotion inference on first sentence — updates voice modulation
                # before the synthesizer processes it, no LLM call needed.
                if _first_sentence[0]:
                    inferred = infer_emotion_fast(clean)
                    if inferred != "neutral":
                        _emotion_live[0] = inferred
                    _first_sentence[0] = False
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
# ERROR LOGGING
# ─────────────────────────────────────────────

import traceback as _traceback
from pathlib import Path as _Path
from datetime import datetime as _datetime

_ERROR_LOG    = _Path("hayeong_outputs/logs/brain_errors.log")
_RECOVERY_FILE = _Path("hayeong_outputs/recovery/last_recovery_note.json")
_STARTUP_MSG   = _Path("hayeong_outputs/recovery/startup_message.txt")

_INTERFACE_SCRIPTS = {
    "voice": str(_Path(__file__).parent / "voice_io.py"),
    "text":  str(_Path(__file__).parent / "text_io.py"),
}

_PROTECTED_FILES = {
    "main.py", "watchdog.py", "text_io.py", "voice_io.py",
    "hayeong_config.py", "hayeong_state.py", "hayeong_state.json",
}


def _log_brain_error(exc: Exception):
    _ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    timestamp = _datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(_ERROR_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {type(exc).__name__}: {exc}\n")
        f.write(_traceback.format_exc())
        f.write("---\n")


def write_recovery_note(reason: str, suggested_action: str = "notify_only",
                        notify_james: bool = True, message_to_james: str = None,
                        script_to_run: str = None):
    """Write a structured note before an intentional shutdown. Watchdog acts on it."""
    import json as _json
    _RECOVERY_FILE.parent.mkdir(parents=True, exist_ok=True)
    note = {
        "timestamp":        _datetime.now().isoformat(),
        "reason":           reason,
        "suggested_action": suggested_action,
        "notify_james":     notify_james,
        "message_to_james": message_to_james,
        "script_to_run":    script_to_run,
        "resolved":         False,
    }
    _RECOVERY_FILE.write_text(_json.dumps(note, indent=2), encoding="utf-8")
    print(f"[brain] Recovery note written: {reason}")


def check_startup_message():
    """Deliver any message the watchdog queued for James."""
    if not _STARTUP_MSG.exists():
        return
    try:
        message = _STARTUP_MSG.read_text(encoding="utf-8").strip()
        _STARTUP_MSG.unlink()
        if message:
            try:
                from hayeong_state import push_output as _push_output
                _push_output(None, message)
                print(f"[brain] Startup message queued for James.")
            except Exception:
                print(f"[brain] Startup message (state unavailable): {message}")
    except Exception as e:
        print(f"[brain] Could not read startup message: {e}")


def attempt_interface_restart(interface_name: str) -> bool:
    """Restart a failed interface process. Brain can do this without asking James."""
    import subprocess as _sp
    script = _INTERFACE_SCRIPTS.get(interface_name)
    if not script or not _Path(script).exists():
        print(f"[brain] Cannot restart {interface_name} — script not found: {script}")
        return False
    print(f"[brain] Restarting {interface_name} interface...")
    _sp.Popen(
        [_sys.executable, script],
        creationflags=_sp.CREATE_NEW_CONSOLE,
    )
    return True


def request_file_modification(file_path: str, proposed_change: str, reason: str) -> bool:
    """
    Propose a file modification. Protected files queue an approval request to James.
    Self-modifiable files (capabilities/, scripts/, prompts/) are applied and logged.
    Returns True if the change was applied immediately.
    """
    _base = _Path(file_path).name
    is_protected = _base in _PROTECTED_FILES

    try:
        from hayeong_state import push_output as _push_output
    except Exception:
        return False

    if is_protected:
        _push_output(None,
            f"I want to modify `{file_path}` to fix an issue.\n\n"
            f"Reason: {reason}\n\n"
            f"Proposed change:\n```\n{proposed_change}\n```\n\n"
            f"This is a protected file — I need your approval. Should I make this change?"
        )
        return False

    # Self-modifiable — apply and log
    _mod_log = _Path("hayeong_outputs/logs/self_modifications.log")
    _mod_log.parent.mkdir(parents=True, exist_ok=True)
    timestamp = _datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(_mod_log, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {file_path}\nReason: {reason}\nChange:\n{proposed_change}\n---\n")

    _push_output(None,
        f"I updated `{file_path}`: {reason}. "
        f"Change logged to hayeong_outputs/logs/self_modifications.log."
    )
    return True


# ─────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────

def main(text_mode: bool = False, brain_mode: bool = False):
    # brain_mode: no input(), no TTS — reads input queue, writes output queue.
    # Used by the three-window startup: brain window runs --brain, text window
    # runs text_io.py (which talks to the brain via hayeong_state.json).
    # text_mode is preserved for direct single-window use.
    if brain_mode:
        text_mode = True   # suppress TTS in brain process
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

    # ── STEP 2: First-time setup ──
    check_first_time_setup()

    # ── STEP 4: Load everything ──
    router   = ModelRouter()
    memory     = load_memory()
    mood_state = load_mood()
    arch       = HayeongArchitecture()
    session    = SessionTrust(environment="home")
    app_mgr    = get_app_manager()
    app_mgr.start_monitor()
    tracker    = SituationTracker() if SITUATION_TRACKER_AVAILABLE else None

    # Persistent executor for parallel memory lookups.
    # max_workers=1 — ChromaDB is not thread-safe for concurrent reads.
    _mem_executor = ThreadPoolExecutor(max_workers=1)

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

    # ── Deliver any watchdog message from a previous crash/restart ──
    if brain_mode:
        check_startup_message()

    # ── Validate shared state schema — safe merge of any missing keys ──
    try:
        from state_manager import validate_and_migrate
        validate_and_migrate()
    except Exception as _sm_err:
        print(f"   [StateManager] Migration failed: {_sm_err}")

    # ── Write session start marker to shared state ──
    try:
        from state_manager import write_conversation
        from datetime import datetime as _dt
        write_conversation({
            "session_start":         _dt.now().isoformat(),
            "last_james_message":    "",
            "last_hayeong_response": "",
        })
    except Exception as _ss_err:
        print(f"   [StateManager] Session start write failed: {_ss_err}")

    # ── Start reasoning loop — runs on its own thread, never speaks to James ──
    try:
        from reasoning_loop import start_reasoning_loop
        start_reasoning_loop()
        print("   [ReasoningLoop] Heartbeat started.")
    except Exception as _rl_err:
        print(f"   [ReasoningLoop] Failed to start: {_rl_err}")

    # ── Start system health monitor — background hardware awareness ──
    try:
        from system_monitor import start_monitor
        start_monitor()
        print("   [SystemMonitor] Health monitoring started.")
    except Exception as _sm_err:
        print(f"   [SystemMonitor] Failed to start: {_sm_err}")

    # ── Live2D — optional, starts only if VTube Studio is reachable ──
    try:
        from live2d_controller import start_live2d
        start_live2d()
        print("   [Live2D] Controller started.")
    except Exception as _l2d_err:
        print(f"   [Live2D] Not available ({_l2d_err}) — skipping.")

    energy = EnergyManager()  if ENERGY_AVAILABLE   else None
    mixer  = MindStateMixer() if MIND_MIXER_AVAILABLE else None

    # ── Presence governor — detect whether James is at the machine ──
    if PRESENCE_GOVERNOR_AVAILABLE:
        print(f"   [PresenceGovernor] Mode: {get_presence_mode()}")
        def _on_presence_change(new_mode: str):
            print(f"   [PresenceGovernor] → {new_mode.upper()}")
        start_presence_monitoring(on_change=_on_presence_change, interval=30)
    smm    = SelfModManager() if SELF_MOD_AVAILABLE   else None
    tasks  = TaskManager()    if TASKS_AVAILABLE       else None
    email  = hayeong_email    if EMAIL_AVAILABLE        else None

    # ── Capability loader — dynamic hot-reloadable dispatch ──
    _loader = None
    if CAPABILITY_LOADER_AVAILABLE:
        _loader = get_loader()
        _loader.start()
        print(f"   [CapabilityLoader] {len(_loader.list_loaded())} actions loaded: {_loader.list_loaded()}")

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

    # ── STEP 5b: Auto-launch Voice Server ──
    # The voice server is the primary voice pipeline.
    # Local client (voice_client_local.py) connects to it at the desktop.
    # Phone app (Phase 10) connects to it over Tailscale when away.
    print("\n🎙️  Starting voice server...")
    _, _vs_msg = app_mgr.start("voice_server")
    print(f"   [VoiceServer] {_vs_msg}")

    # ── STEP 5c: Start async presence layer ──
    # This is what makes her feel present even while working.
    # The presence layer always accepts input instantly and
    # dispatches slow work to a background thread.
    _presence: Optional["PresenceLayer"] = None

    if ASYNC_PRESENCE_AVAILABLE:
        def _on_ack(text: str):
            """Immediate acknowledgment — fires before any processing."""
            print(f"\nHayeong: {text}")
            _speak(text, emotion="neutral")

        def _on_result(text: str, emotion: str):
            """Full response — fires when background task completes."""
            clean = _strip_markdown(text)
            print(f"\nHayeong: {clean}")
            _speak(clean, emotion=emotion)
            print()

        _process_fn = build_process_fn(
            chat_fn        = chat_with_ai,
            build_prompt_fn= build_prompt,
            load_memory_fn = load_memory,
            save_memory_fn = save_memory,
            load_mood_fn   = load_mood,
            save_json_fn   = save_json,
            load_identity_fn = load_identity,
            adjust_mood_fn = adjust_mood_by_context,
            mood_file      = MOOD_FILE,
            dynamic_traits = {
                "personality_intensity": 3,
                "emotional_warmth":      8,
                "tactical_intensity":    6,
                "motivation_style":      "gently pushy",
                "teasing_level":         "high",
            },
            memory_lock    = threading.Lock(),
        )

        _presence = PresenceLayer(
            on_ack     = _on_ack,
            on_result  = _on_result,
            process_fn = _process_fn,
        )
        _presence.start()
        print("   [AsyncPresence] Presence layer active — she stays responsive mid-task")

    # ── Preload both models — eliminates cold-start latency ──
    for _url, _model, _label in [
        (COMMUNICATION_URL, COMMUNICATION_MODEL, "communication (7b)"),
        (REASONING_URL,     REASONING_MODEL,     "reasoning (14b)"),
    ]:
        try:
            print(f"   Warming {_label}...", end=" ", flush=True)
            requests.post(
                _url,
                json={
                    "model":   _model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream":  False,
                    "options": {"num_predict": 1, "num_ctx": 512},
                },
                timeout=30,
            )
            print("ready.")
        except Exception:
            print(f"(warmup failed — first {_label} response may be slow)")

    # ── Pre-warm filler cache ──
    if FILLER_AVAILABLE and not text_mode:
        try:
            print("   Warming filler cache...", end=" ", flush=True)
            from filler_system import _get_cached_audio, FILLERS
            _fw_speed = get_voice_modulation("neutral")["speed"]
            for _fw_variants in FILLERS.values():
                _get_cached_audio(_fw_variants[0], _fw_speed)
            print("ready.")
        except Exception as _fw_e:
            print(f"(skipped — {_fw_e})")

    # Shared state — imported here so voice failures during module load
    # don't block this import.
    try:
        from hayeong_state import pop_input, push_output, set_brain_status
        _state_available = True
        set_brain_status("running")
    except Exception:
        _state_available = False
        def pop_input():       return None
        def push_output(r, t): pass
        def set_brain_status(s): pass

    print("\n✅ Hayeong is ready.")
    if brain_mode:
        print("   Mode: BRAIN — reading from input queue (hayeong_state.json).")
    elif text_mode:
        print("   Mode: TEXT CHAT — type your message and press Enter. Type 'exit' to quit.")
    else:
        print("   Say her name to wake her up.")
    print(f"   Session trust: {session.get_trust_label()}")
    if energy:
        print(f"   Energy level: {energy.level}/5 ({energy.get_full_state()['label']})")
    print(f"   Running: {app_mgr.list_running() or ['none']}")
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

        # ── Get input — brain queue, text, or voice ──
        _filler_gate = None   # reset each turn; voice path overwrites below
        if brain_mode:
            msg = pop_input()
            if msg:
                user_input = msg.get("content", "").strip()
                _msg_id    = msg.get("id", "")
                if user_input:
                    print(f"[brain] Queue: {user_input[:80]}")
            else:
                time.sleep(0.1)
                continue
        elif text_mode:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nShutting down...")
                save_memory(memory)
                save_json(MOOD_FILE, mood_state)
                if _presence is not None:
                    _presence.stop()
                app_mgr.stop_all()
                try:
                    from capabilities.minecraft_cap import _stop_all as _mc_stop
                    _mc_stop()
                except Exception:
                    pass
                if energy:
                    energy.save_on_shutdown()
                if LOGGER_AVAILABLE:
                    logger.end_session()
                break
            if not user_input:
                continue

            # ── Quality flagging for fine-tuning ──
            _u_lower = user_input.lower()
            _QUALITY_GOOD = ["that was perfect", "exactly right", "that's right", "good answer", "well done", "perfect answer"]
            _QUALITY_BAD  = ["that was wrong", "that's not right", "wrong answer", "bad response", "no that's wrong", "that's incorrect"]
            try:
                from finetune_logger import conversation_logger as _ft_logger
                if any(p in _u_lower for p in _QUALITY_GOOD):
                    _ft_logger.flag_last_turn("good")
                elif any(p in _u_lower for p in _QUALITY_BAD):
                    _ft_logger.flag_last_turn("bad")
            except Exception:
                pass

            # ── Route through async presence if available ──
            if _presence is not None:
                intent = detect_intent(user_input)
                _presence.submit(user_input, intent=intent)
                # Don't fall through to the synchronous pipeline —
                # presence layer handles the full response.
                continue
        else:
            listen_for_wake_word()
            audio_file = record_until_silence()
            user_input = transcribe(audio_file) if audio_file else ""
            if not user_input:
                continue
            print(f"\nYou: {user_input}")

            # ── Start filler gate ──
            # Fires contextual audio if LLM doesn't respond within threshold.
            # Cancelled the moment the first token arrives.
            _filler_gate = None
            if FILLER_AVAILABLE:
                _filler_gate = FillerTimer(
                    intent=_quick_intent(user_input),
                    base_speed=get_voice_modulation("neutral")["speed"],
                    output_device=OUTPUT_DEVICE,
                )
                _filler_gate.start()

            # ── Route through async presence if available ──
            # Immediate ack fires, processing runs in background,
            # the loop returns to listening immediately.
            if _presence is not None:
                intent = detect_intent(user_input)
                _presence.submit(user_input, intent=intent)
                # Don't fall through to the synchronous pipeline below —
                # presence layer handles the full response.
                continue

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
            if _presence is not None:
                _presence.stop()
            app_mgr.stop_all()
            try:
                from capabilities.minecraft_cap import _stop_all as _mc_stop
                _mc_stop()
            except Exception:
                pass
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

        # ── Parallel memory lookup — fires NOW, retrieved before prompt assembly ──
        # ChromaDB lookup runs in the background while mood update, passphrase
        # check, model routing, snapshot, and decide_action all run sequentially.
        # By the time we need the result it's usually already done.
        _mem_future = _mem_executor.submit(recall_for_prompt, user_input, 4)
 
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
        arch.sync_mood_to_behavioral_state(mood_state)

        if mixer:
            blend = suggest_blend_for_context("casual", "home")
            mixer.blend_states(blend)
            mixer.step()

        # ── Build prompt ──
        who = session.get_privacy_context()
        memory.append({"role": "user", "content": user_input})

        long_term_context = _mem_future.result(timeout=10)
        state_of_mind     = detect_state_of_mind("casual", "home", mood_state)
        system_prompt     = build_system_prompt(
            who=who, situation="casual", environment="home", state_of_mind=state_of_mind
        )
        if long_term_context:
            system_prompt = long_term_context + "\n\n" + system_prompt

        # ── Consume reasoning context — what the 14b wants the 7b to know ──
        # consume_communication_context() reads AND clears atomically — never injected twice
        try:
            from state_manager import consume_communication_context
            _reasoning_ctx = consume_communication_context()
        except Exception:
            _reasoning_ctx = ""
        if _reasoning_ctx:
            system_prompt += (
                f"\n\n[REASONING CONTEXT — from your reasoning layer]\n"
                f"{_reasoning_ctx}\n"
                f"Use this context naturally in your response if relevant. "
                f"Do not announce it literally — weave it in as your own awareness."
            )

        # ── System health — inject warnings so Hayeong can mention hardware issues ──
        try:
            from system_monitor import format_for_prompt as _health_for_prompt
            _health_str = _health_for_prompt()
            if _health_str:
                system_prompt += "\n\n" + _health_str
        except Exception:
            pass

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

        # ── Think Together — align before acting ──
        # If either the router or the decision engine flagged ambiguity,
        # stay in conversation. Better to ask than to guess and fire the wrong tool.
        _think_together = action == "think_together" or route.get("intent") == "think_together"
        if _think_together:
            print(f"   [ThinkTogether] Staying in conversation — aligning before acting")
            action = "none"

        # ── Image Collab — collaborative design session flag ──
        _image_collab = route.get("intent") == "image_collab"
        if _image_collab:
            print(f"   [ImageCollab] Design session mode — Hayeong will engage as collaborator")

        # ── Context verifier — self-check before any tool executes ──
        # Only runs when an action was actually chosen (skip overhead on "none").
        # Extracts constraints and confirms the action is genuinely requested.
        _constraints = []

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

        if action != "none":
            if _loader and _loader.handles(action):
                # ── New path: capability loader (hot-reloadable) ──
                _cap_context = {
                    "memory":        memory,
                    "mood":          mood_state,
                    "decision":      decision,
                    "model":         selected_model,
                    "session":       session,
                    "speak_fn":      _speak,
                    "logger":        logger        if LOGGER_AVAILABLE       else None,
                    "email":         email,
                    "email_monitor": email_monitor if EMAIL_MONITOR_AVAILABLE else None,
                    "email_address": hayeong_email.to_address if EMAIL_AVAILABLE else None,
                    "constraints":   _constraints,
                }
                _cap_result = _loader.dispatch(action, user_input, _cap_context)

                # Speak ack if capability provided one
                if _cap_result.get("speak"):
                    _speak(_cap_result["speak"], emotion=_cap_result.get("emotion", "neutral"))

                # Inject context into prompt
                if _cap_result.get("response"):
                    _web_context = _cap_result["response"]

                if not _cap_result.get("success"):
                    print(f"   [Capability] {action} failed: {_cap_result.get('data', {}).get('reason', 'unknown')}")

            else:
                # ── Legacy fallback — action not yet migrated to capability system ──
                print(f"   [dispatch] no capability handler for {action!r} — falling through to conversation")

        # ── Inject any context into system prompt ──
        if _web_context:
            system_prompt = _web_context + "\n\n" + system_prompt
        if _vision_context:
            system_prompt = _vision_context + "\n\n" + system_prompt
        if tracker and _snapshot:
            system_prompt = tracker.format_for_prompt(include_backlog=True) + "\n\n" + system_prompt

        # Minecraft awareness — 7b reads game state from shared state, never controls the bot
        mc_active = False
        try:
            from state_manager import read_state as _read_state
            _shared   = _read_state()
            _mc       = _shared["reasoning"].get("minecraft_state", {})
            mc_active = _shared["reasoning"].get("minecraft_session_active", False)
            if mc_active and _mc and _mc.get("active"):
                _health   = _mc.get("health", 20)
                _food     = _mc.get("food", 20)
                _tod      = _mc.get("time_of_day", 0) or 0
                _time_str = "night" if _tod > 12000 else "day"
                _inv      = ", ".join(_mc.get("inventory", [])) or "empty"
                _mobs     = _mc.get("nearby_mobs", [])
                _mob_str  = ", ".join(f"{m['name']} {m['dist']}m" for m in _mobs) or "none"
                _mc_goal  = _shared["reasoning"].get("current_goal", "")
                _mc_last  = _shared["reasoning"].get("last_conclusion", "")
                system_prompt += (
                    f"\n\n[MINECRAFT ACTIVE — your awareness of the game]\n"
                    f"Health: {_health}/20  Food: {_food}/20  Time: {_time_str}\n"
                    f"Inventory: {_inv}\n"
                    f"Nearby mobs: {_mob_str}\n"
                    f"Current goal: {_mc_goal}\n"
                    f"Last action: {_mc_last}\n"
                    f"You are aware of this state and can describe it naturally to James.\n"
                    f"You do not control the bot — your reasoning layer handles all in-game decisions."
                )
        except Exception:
            pass

        # ── System health — inject any pending alerts so Hayeong can tell James ──
        if brain_mode:
            try:
                from hayeong_state import pop_system_alert, get_status as _get_status
                _alert = pop_system_alert()
                if _alert:
                    _iface   = _alert.get("interface", "unknown")
                    _reason  = _alert.get("reason", "")
                    system_prompt += (
                        f"\n\n━━━ SYSTEM HEALTH ALERT ━━━\n"
                        f"The {_iface} interface has gone down: {_reason}\n"
                        f"Mention this to James naturally — he should know so he can decide "
                        f"whether to restart it or continue without it."
                    )
                _sys_status = _get_status()
                _down = [k for k, v in _sys_status.get("interfaces", {}).items() if v in ("down", "error", "failed")]
                if _down and not _alert:
                    system_prompt += (
                        f"\n\n[System note: {', '.join(_down)} interface(s) are currently down. "
                        f"If James asks about it or it's relevant, let him know.]"
                    )
            except Exception:
                pass

        if _think_together:
            system_prompt += (
                "\n\n━━━ THINK TOGETHER MODE ━━━\n"
                "James's request is ambiguous or he's working through something.\n"
                "Your job right now is NOT to act — it's to understand.\n"
                "Ask one clarifying question if needed. Help him figure out what he actually wants.\n"
                "Do not guess and fire a capability. Do not assume you know the right next step.\n"
                "Stay in conversation. Align with him. When it's clear what he needs, then act.\n"
                "If he's venting or thinking aloud — sometimes the right move is just to listen."
            )
        if _image_collab:
            system_prompt += (
                "\n\n━━━ COLLABORATIVE DESIGN SESSION ━━━\n"
                "James wants to work WITH you on designing or refining an image — "
                "not just receive a result.\n"
                "You have opinions. Notice what looks right and what doesn't. "
                "Suggest what to iterate on.\n"
                "Engage with each generation as a creative collaborator, not a button.\n"
                "If an image came out wrong, say so. If something looks good, say that too.\n"
                "The session continues until both of you are happy with the result."
            )

        # ── Stream response ──
        show_thinking()

        # Suppress TTS when Minecraft is active — text-only in-game
        _effective_text_mode = text_mode or mc_active

        ai_response = stream_response_and_speak(
            system_prompt, memory,
            emotion=current_emotion,
            text_mode=_effective_text_mode,
            model=selected_model,
            cancel_filler_fn=_filler_gate.cancel if _filler_gate else None,
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
        if brain_mode:
            push_output(_msg_id, ai_response)

        # ── Write this turn to shared state for the reasoning LLM to read ──
        try:
            from state_manager import write_conversation
            write_conversation({
                "last_james_message":    user_input,
                "last_hayeong_response": ai_response[:500],
            })
        except Exception:
            pass

        # ── Fine-tuning log — append this turn for future training ──
        try:
            from finetune_logger import conversation_logger as _ft_logger
            _ft_logger.log_turn(
                user=user_input,
                assistant=ai_response,
                model=selected_model,
                mood=current_emotion,
            )
        except Exception:
            pass

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
    parser.add_argument("--text",  action="store_true", help="Text chat mode (no voice)")
    parser.add_argument("--brain", action="store_true", help="Brain-only mode: reads input queue, writes output queue (no terminal I/O)")
    args = parser.parse_args()

    while True:
        try:
            main(text_mode=args.text, brain_mode=args.brain)
            break
        except KeyboardInterrupt:
            print("\n[brain] Stopped.")
            break
        except Exception as _e:
            _log_brain_error(_e)
            print(f"[brain] Unexpected crash: {type(_e).__name__}: {_e}")
            print(f"[brain] Logged to {_ERROR_LOG}. Restarting in 3 seconds...")
            time.sleep(3)