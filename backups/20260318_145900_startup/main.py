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


def stream_response_and_speak(system_prompt: str, memory: list, emotion: str = "neutral", text_mode: bool = False, model: str = None) -> str:
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

    # In text mode suppress all TTS
    def _speak(text, emotion="neutral"):
        if not text_mode:
            speak(text, emotion=emotion)

    # ── STEP 5: Auto-launch Discord ──
    print("\n📡 Starting Discord bridge...")
    result = procs.start("discord")
    print(f"   {result}")
    if procs.is_running("discord"):
        procs.monitor_and_restart("discord")

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

        
        # ── UNIFIED INTENT ROUTING ──
        # Context-aware — passes recent memory so the router understands
        # what's actually happening in the conversation, not just keywords.
        intent = detector.route(user_input, memory[-4:])

        # ── Log user input ──
        if LOGGER_AVAILABLE:
            logger.log_conversation(
                role="james",
                content=user_input,
                intent=intent.get("intent") if intent else None
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

        # ── Capability: start/stop a subprocess ──
        if intent["intent"] == "capability" and intent["action"] and intent["target"]:
            cap    = intent["target"]
            action = intent["action"]
            response_text = CAPABILITY_RESPONSES.get((action, cap), f"{action}ing {cap}.")
            print(f"\nHayeong: {response_text}")
            _speak(response_text, emotion="neutral")
 
            if action == "start":
                result = procs.start(cap)
                if procs.is_running(cap):
                    procs.monitor_and_restart(cap)
                print(f"   [{result}]")
            else:
                result = procs.stop(cap)
                print(f"   [{result}]")
 
            memory.append({"role": "user", "content": user_input})
            memory.append({"role": "AI",   "content": response_text})
            save_memory(memory)
            print()
            continue
 
        # ── Task commands ──
        if intent["intent"] == "task" and tasks:
            task_action = intent["action"]
 
            if task_action == "show":
                resp = tasks.format_list()
                print(f"\nHayeong:\n{resp}")
                _speak("Here's what's on my list.", emotion="neutral")
 
            elif task_action == "show_completed":
                resp = tasks.format_list(state="completed")
                print(f"\nHayeong:\n{resp}")
                _speak("Here's what I've finished.", emotion="neutral")
 
            elif task_action == "show_blocked":
                resp = tasks.format_list(state="blocked")
                print(f"\nHayeong:\n{resp}")
                _speak("Here's what's blocked.", emotion="neutral")
 
            elif task_action == "add":
                # Strip the command portion so only the task description remains
                raw = re.sub(
                    r'(?i)(add a task|add task|remember to|i need to|put on the list)[:\s]*',
                    '', user_input
                ).strip() or user_input
                kwargs   = parse_task_from_text(raw, origin="james")
                new_task = tasks.add_task(**kwargs)
                resp     = f"Added to backlog: {new_task['title']}"
                print(f"\nHayeong: {resp}")
                _speak(resp, emotion="neutral")
 
            else:
                # Unrecognised task sub-action — let LLM handle it naturally
                resp = None
 
            if resp is not None:
                memory.append({"role": "user", "content": user_input})
                memory.append({"role": "AI",   "content": resp})
                save_memory(memory)
                print()
                continue
 
        # ── Email commands ──
        if intent["intent"] == "email" and email:
            email_action = intent["action"]
 
            if email_action == "send_summary":
                task_sum  = tasks.summary() if tasks else None
                proc_stat = procs.status()
                ok   = hayeong_email.send_daily_summary(
                    task_summary=task_sum, process_status=proc_stat
                )
                resp = "Sent you a summary." if ok else "Couldn't send — check email config."
 
            elif email_action == "check_inbox":
                messages_inbox = hayeong_email.check_inbox(unread_only=True)
                if messages_inbox:
                    resp = f"{len(messages_inbox)} new message{'s' if len(messages_inbox) != 1 else ''}."
                    for m in messages_inbox[:3]:
                        print(f"  From: {m['from']}")
                        print(f"  Subject: {m['subject']}")
                        print(f"  {m['body'][:150]}\n")
                else:
                    resp = "Nothing new."
 
            else:  # notify — default email action
                msg_text = re.sub(
                    r'(?i)(email me|send me a message|notify me|send me a note|ping me)[:\s]*',
                    '', user_input
                ).strip() or "Hello from Hayeong!"
                ok   = hayeong_email.notify(msg_text)
                resp = "Done, sent." if ok else "Couldn't send — check email config."
 
            print(f"\nHayeong: {resp}")
            _speak(resp, emotion="neutral")
            memory.append({"role": "user", "content": user_input})
            memory.append({"role": "AI",   "content": resp})
            save_memory(memory)
            print()
            continue

        # ── Image generation ──
        if intent["intent"] == "image_generation" and COMFYUI_AVAILABLE:
            u = user_input.lower()
            if any(x in u for x in ["realistic", "make it real", "real photo", "turn this into"]):
                _speak("Which image should I make realistic?", emotion="neutral")
                image_path = input("Image path: ").strip()
                result = comfyui.make_realistic(image_path)
            elif any(x in u for x in ["screen", "on my screen"]):
                _speak("Let me look at your screen.", emotion="neutral")
                result = comfyui.generate_from_screen(user_input)
            elif any(x in u for x in ["this image", "this photo", "reference"]):
                _speak("Which image should I use as a reference?", emotion="neutral")
                image_path = input("Image path: ").strip()
                result = comfyui.generate_from_image(image_path, user_input)
            else:
                _speak("On it, let me generate that.", emotion="neutral")
                result = comfyui.generate(user_input)

            if result["success"]:
                resp = f"Done! Saved to {result['image_path']}"
                if LOGGER_AVAILABLE:
                    logger.log_image_generation(
                        prompt=result.get("prompt_used", ""),
                        output_path=result.get("image_path"),
                        model="ponyDiffusionV6XL",
                        outcome="success"
                    )
                    logger.log_capability_used("comfyui", action="generate", outcome="success")
            else:
                resp = result.get("message", "Something went wrong with image generation.")
                if LOGGER_AVAILABLE:
                    logger.log_capability_used("comfyui", action="generate", outcome="failed",
                                               error=result.get("message"))

            print(f"\nHayeong: {resp}")
            _speak(resp, emotion="neutral")
            memory.append({"role": "user", "content": user_input})
            memory.append({"role": "AI",   "content": resp})
            save_memory(memory)
            print()
            continue

        # ── Goal / progress report trigger ──
        if LOGGER_AVAILABLE and any(p in user_input.lower() for p in [
            "goal", "progress report", "workstation", "how much have we saved",
            "how are we doing", "weekly report"
        ]):
            goal = logger.goal_status()
            resp = (
                f"We've saved ${goal['earned']:.2f} of ${goal['target']:.2f} — "
                f"{goal['percent']:.1f}% of the workstation goal. "
                f"${goal['remaining']:.2f} to go."
            )
            # Feed data to memory so Hayeong can respond naturally and add her own thoughts
            memory.append({"role": "user", "content": user_input})
            memory.append({"role": "AI",   "content": resp})
            save_memory(memory)
            # Don't continue — fall through to LLM so she can elaborate naturally

        # ── Web search ──
        # Acknowledge immediately, run search in parallel, synthesize when done.
        _web_context = ""
        if intent["intent"] == "web_search" and SEARCH_AVAILABLE:
            _is_news        = any(kw in user_input.lower() for kw in ["news", "latest", "current"])
            _delivery_mode  = intent.get("delivery_mode", "conversational")

            # Step 1 — acknowledge instantly
            if _delivery_mode == "document":
                _speak("Sure, let me pull that together for you. I'll send you the full breakdown when I'm done.", emotion="neutral")
            else:
                _speak("Let me look that up.", emotion="neutral")
            print(f"   [searching... delivery={_delivery_mode}]")

            # Step 2 — extract query + run search
            query = WebSearch.extract_query(user_input, recent_memory=memory[-6:])
            if _is_news:
                data = {"query": query, "results": searcher.news(query, max_results=5), "full_text": {}}
            else:
                # Document mode fetches more results for a richer breakdown
                max_r  = 6 if _delivery_mode == "document" else 4
                data   = searcher.search_and_read(query, max_results=max_r, fetch_top=2 if _delivery_mode == "document" else 1)

            n_results = len(data.get("results", []))
            if n_results > 0:
                print(f"   [found {n_results} results]")
            else:
                print(f"   [no results — falling back to training knowledge]")

            if _delivery_mode == "document" and n_results > 0:
                # Document mode: generate doc, save it, email it, give Hayeong a brief
                # context so she can give her personal take before mentioning the doc
                doc_content = searcher.format_as_document(query, data, topic=query)
                doc_path    = searcher.save_document(doc_content, topic=query)
                print(f"   [document saved: {doc_path}]")

                # Try to email the document if email is available
                _doc_emailed = False
                if EMAIL_AVAILABLE:
                    try:
                        with open(doc_path, "r", encoding="utf-8") as f:
                            doc_text = f.read()
                        email_result = hayeong_email.send(
                            to=hayeong_email.james_email,
                            subject=f"Research: {query}",
                            body=doc_text,
                        )
                        _doc_emailed = email_result.get("success", False)
                        if _doc_emailed:
                            print(f"   [document emailed to James]")
                    except Exception as e:
                        print(f"   [email failed: {e}]")

                # Give Hayeong context for her conversational take + doc mention
                _doc_note = (
                    f"You emailed James the full research document for '{query}'. "
                    if _doc_emailed else
                    f"You saved the full research document to: {doc_path}. "
                )
                _web_context = (
                    searcher.format_for_context(query, data) +
                    f"\n\n[DOCUMENT NOTE]: {_doc_note}"
                    "Give James your brief personal take on the most interesting findings "
                    "in 2-4 sentences, then mention you've sent/saved the full breakdown. "
                    "Don't list everything — just your honest impression of what stands out."
                )
            else:
                # Conversational mode: standard context injection, she synthesizes naturally
                _web_context = searcher.format_for_context(query, data)

            if LOGGER_AVAILABLE:
                logger.log_capability_used(
                    "web_search", action="search", outcome="success",
                    details={"query": query, "results": n_results, "delivery": _delivery_mode}
                )

        # ── Vision ──
        # Acknowledge immediately, capture + analyze, then synthesize.
        _vision_context = ""
        if intent["intent"] == "vision" and VISION_AVAILABLE:
            u = user_input.lower()
            if any(x in u for x in ["image", "photo", "file", "this image", "this photo"]):
                _speak("Which image should I look at?", emotion="neutral")
                image_path = input("Image path: ").strip()
                _speak("Got it, analyzing now.", emotion="neutral")
                _vision_context = vision.look_at_image(image_path, user_input)
            elif any(x in u for x in ["deep", "detail", "explain", "what's in", "code"]):
                _speak("Let me take a closer look.", emotion="neutral")
                _vision_context = vision.look_at_screen_deep(user_input)
            else:
                _speak("Let me take a look.", emotion="neutral")
                _vision_context = vision.look_at_screen(user_input)
            if LOGGER_AVAILABLE:
                logger.log_capability_used("vision", action="analyze", outcome="success")

        # ── Approve / Deny self-generated capability ──
        if smm:
            approve_match = re.match(_APPROVE_PATTERN, user_input)
            deny_match    = re.match(_DENY_PATTERN, user_input)
            if approve_match or deny_match:
                match    = approve_match or deny_match
                approved = bool(approve_match)
                filename = match.group(1)
                ok       = smm.approve_capability(filename, approved=approved)
                resp     = f"{'Activated' if approved else 'Disabled'}: {filename}." if ok else f"Couldn't find '{filename}' in pending capabilities."
                print(f"\nHayeong: {resp}")
                _speak(resp, emotion="neutral")
                memory.append({"role": "user", "content": user_input})
                memory.append({"role": "AI",   "content": resp})
                save_memory(memory)
                print()
                continue

        # ── Self-mod summary ──
        if smm and any(p in user_input.lower() for p in _SELFMOD_PATTERNS):
            summary = smm.weekly_summary()
            pending = smm.pending_proposals()
            if summary["has_anything"]:
                lines = "\n".join(summary["summary_lines"])
                resp = f"Here's what I changed this week:\n{lines}"
            elif pending:
                resp = f"I have {len(pending)} pending proposal(s) waiting for your review."
            else:
                resp = "Nothing to report — no changes this week."
            print(f"\nHayeong: {resp}")
            _speak(resp, emotion="neutral")
            memory.append({"role": "user", "content": user_input})
            memory.append({"role": "AI", "content": resp})
            save_memory(memory)
            print()
            continue

        # ── Status command ──
        if any(p in user_input.lower() for p in ["what's running", "status", "what are you running"]):
            status = procs.status()
            if status:
                lines = ", ".join(f"{k} ({v})" for k, v in status.items())
                resp = f"Running: {lines}."
            else:
                resp = "Nothing extra running right now."
            print(f"\nHayeong: {resp}")
            _speak(resp, emotion="neutral")
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

        # Prepend any web search or vision context for this turn
        if _web_context:
            system_prompt = _web_context + "\n\n" + system_prompt
        if _vision_context:
            system_prompt = _vision_context + "\n\n" + system_prompt

        current_emotion = arch.behavioral.state["interior_state"]["current"]["primary_emotion"]

        # ── Model routing ──
        # Decide which model handles this message before calling the LLM.
        # Coding → DeepSeek 33b | Long/complex → Qwen 32b | Default → Qwen 14b
        route         = router.route(user_input)
        selected_model = route["model_name"]
        if route["model"] != "main":
            print(f"   [routing to {route['model']} — {route['reasoning']}]")

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