"""
hayeong_core.py
───────────────
Lightweight shared utilities used by both main.py and discord_hayeong.py.

IMPORTANT: This file must NOT import sounddevice, voice, TTS, or any
audio library. It is the safe shared layer between the main process
and the Discord bot process.

Provides:
  - JSON load/save helpers
  - Ollama chat call
  - build_prompt (assembles messages list for Ollama)
  - adjust_mood_by_context
  - is_worth_remembering
  - _strip_markdown
  - infer_emotion_fast / _FAST_EMOTION_MAP
  - update_mood
"""

import re
import json
import os
import requests
from pathlib import Path
from filelock import FileLock

# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────

BASE_DIR       = Path(__file__).parent
MEMORY_FILE    = BASE_DIR / "memory.json"
# identity.json is preserved as historical record — not loaded at runtime
_IDENTITY_FILE_HISTORICAL = BASE_DIR / "identity.json"
_IDENTITY_CONSTITUTIONAL  = BASE_DIR / "identity_constitutional.json"
_IDENTITY_BEHAVIORAL      = BASE_DIR / "identity_behavioral.json"
_IDENTITY_LIVING          = BASE_DIR / "identity_living.json"
MOOD_FILE      = BASE_DIR / "mood.json"

# ── Single-model architecture ──
# All LLM calls go through Qwen 2.5 32b on port 11435.
# main.py (presence loop) and reasoning_loop.py both use this model.
OLLAMA_URL    = "http://localhost:11435/api/chat"
PRIMARY_MODEL = "qwen2.5:32b-instruct-q4_K_M"

# ─────────────────────────────────────────────
# JSON HELPERS
# ─────────────────────────────────────────────

def load_json(path, default=None):
    path = Path(path)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default if default is not None else {}

def save_json(path, data):
    """
    Write JSON safely using a file lock.
    A .lock sidecar file is created next to the target —
    whichever process gets there first holds it until done,
    the other waits. No corruption, no lost writes.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path) + ".lock", timeout=10)
    with lock:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

def load_memory():
    return load_json(MEMORY_FILE, [])

def save_memory(m):
    save_json(MEMORY_FILE, m)

def load_identity_layers() -> dict:
    """
    Load all three identity layers and merge them.
    Constitutional (highest authority) is applied last so its keys win on conflict.
    Living layer (lowest authority) is applied first.
    """
    living         = load_json(_IDENTITY_LIVING,         {})
    behavioral     = load_json(_IDENTITY_BEHAVIORAL,     {})
    constitutional = load_json(_IDENTITY_CONSTITUTIONAL, {})
    merged = {}
    merged.update(living)
    merged.update(behavioral)
    merged.update(constitutional)
    return merged

def load_identity() -> dict:
    """Runtime identity — loads from the three active layers."""
    return load_identity_layers()

def load_mood():
    return load_json(MOOD_FILE, {"focus": 0, "playfulness": 0, "motivation": 0})

def save_mood(m):
    save_json(MOOD_FILE, m)


# ─────────────────────────────────────────────
# MOOD
# ─────────────────────────────────────────────

def adjust_mood_by_context(text: str, mood: dict):
    t = text.lower()
    if any(w in t for w in ["minecraft", "ender dragon", "hytale", "cod", "risk of rain", "barony"]):
        mood["focus"]       = min(5, mood.get("focus", 0) + 2)
        mood["motivation"]  = min(5, mood.get("motivation", 0) + 2)
        mood["playfulness"] = max(-5, mood.get("playfulness", 0) - 1)
    elif any(w in t for w in ["joke", "fun", "lol", "haha", "play"]):
        mood["playfulness"] = min(5, mood.get("playfulness", 0) + 2)
        mood["focus"]       = max(-5, mood.get("focus", 0) - 1)
    elif any(w in t for w in ["sad", "frustrated", "fail", "lost", "died"]):
        mood["focus"]       = max(-5, mood.get("focus", 0) - 1)
        mood["motivation"]  = max(-5, mood.get("motivation", 0) - 1)
        mood["playfulness"] = max(-5, mood.get("playfulness", 0) - 1)


# ─────────────────────────────────────────────
# MEMORY FILTER
# ─────────────────────────────────────────────

def is_worth_remembering(text: str) -> bool:
    if not text:
        return False
    if len(text.split()) <= 4:
        return False
    filler = ["lol", "lmao", "haha", "ok", "okay", "yeah", "yep", "nope", "sure", "hmm"]
    if text.lower().strip() in filler:
        return False
    return True


# ─────────────────────────────────────────────
# PROMPT BUILDER
# Assembles the messages list Ollama expects.
# Tries to use the full system_prompt_builder if available,
# falls back to a simple identity-based prompt if not.
# ─────────────────────────────────────────────

def build_prompt(identity: dict, memory: list, user_input: str,
                 dynamic_traits: dict = None, mood_state: dict = None,
                 domain: str = None) -> list:
    """
    Returns a messages list ready for Ollama /api/chat.
    Safe to call from Discord — no audio dependencies.
    Pass domain="minecraft" (or any Toolbox folder name) to inject the
    domain prompt as the outermost layer of the system prompt.
    """

    # ── Domain path: use prompt_layer_manager when domain is specified ──
    if domain:
        try:
            from brain.prompt_layer_manager import build_layered_system_prompt
            system_prompt = build_layered_system_prompt(
                identity=identity, domain=domain, mood=mood_state,
            )
        except Exception:
            domain = None  # fall through to standard path

    # ── Standard path: system_prompt_builder + identity fallback ──
    if not domain:
        system_prompt = None
        try:
            from system_prompt_builder import build_system_prompt, detect_state_of_mind
            from long_term_memory import recall_for_prompt

            mood          = mood_state or {}
            state_of_mind = detect_state_of_mind("casual", "home", mood)
            system_prompt = build_system_prompt(
                who="james", situation="casual",
                environment="home", state_of_mind=state_of_mind,
            )

            long_term_context = recall_for_prompt(user_input, n_results=4)
            if long_term_context:
                system_prompt = long_term_context + "\n\n" + system_prompt

        except Exception:
            name        = identity.get("name", "Hayeong")
            personality = identity.get("personality", "")
            mood        = mood_state or {}
            mood_str    = ", ".join(f"{k}: {v}" for k, v in mood.items()) if mood else ""
            traits_str  = ""
            if dynamic_traits:
                traits_str = "\n".join(f"  {k}: {v}" for k, v in dynamic_traits.items())

            system_prompt = f"You are {name}."
            if personality:
                system_prompt += f"\n\n{personality}"
            if mood_str:
                system_prompt += f"\n\nCurrent mood — {mood_str}."
            if traits_str:
                system_prompt += f"\n\nPersonality traits:\n{traits_str}"

    # ── Assemble messages ──
    messages = [{"role": "system", "content": system_prompt}]
    for entry in memory[-10:]:
        role = "user" if entry.get("role") == "user" else "assistant"
        messages.append({"role": role, "content": entry.get("content", "")})
    messages.append({"role": "user", "content": user_input})
    return messages


# ─────────────────────────────────────────────
# OLLAMA CALL
# ─────────────────────────────────────────────

def chat_with_ai(messages: list) -> str:
    """
    Blocking Ollama call. Safe to run in a thread executor.
    Returns the AI response string.
    """
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": PRIMARY_MODEL, "messages": messages, "stream": False},
            timeout=90
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    except Exception as e:
        return f"[Ollama unreachable: {e}]"


# ─────────────────────────────────────────────
# TEXT UTILITIES
# ─────────────────────────────────────────────

def _strip_markdown(text: str) -> str:
    """
    Remove markdown formatting before printing or speaking.
    Catches the common cases 14b produces: headers, bold, italic, bullet lists.
    Safety net — the system prompt says no markdown, but she sometimes slips
    on information-heavy turns (search results especially).
    """
    # Remove ### / ## / # headers (keep the header text)
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
# FAST EMOTION INFERENCE
# ─────────────────────────────────────────────

_FAST_EMOTION_MAP: list[tuple[list[str], str]] = [
    # Each entry: ([keywords], emotion_key)
    # Listed in priority order — first match wins.
    (["i'm sorry", "sorry to hear", "that's hard", "that must be", "i understand"], "warm"),
    (["sad", "miss you", "lonely", "tired", "hurts", "hard day"], "weighted"),
    (["haha", "funny", "that's hilarious", "lol", "actually laughing"], "amused"),
    (["nice", "proud", "nailed it", "exactly right", "well done", "good call"], "proud"),
    (["let me think", "interesting question", "hmm", "complex", "good point"], "curious"),
    (["on it", "searching", "let me check", "pulling that up", "one sec"], "focused"),
    (["honestly", "look", "straight up", "real talk"], "ai_pride"),
    (["okay so", "alright", "here's the thing", "so basically"], "neutral"),
]

def infer_emotion_fast(text: str) -> str:
    """
    Keyword-based emotion inference from response content.
    No LLM call — runs in microseconds.
    Used to set voice modulation from the first sentence rather than
    waiting for the full response.

    Returns an emotion key from EMOTION_VOICE_MAP, or "neutral" if no match.
    """
    t = text.lower()
    for keywords, emotion in _FAST_EMOTION_MAP:
        if any(k in t for k in keywords):
            return emotion
    return "neutral"


# ─────────────────────────────────────────────
# MOOD HELPERS
# ─────────────────────────────────────────────

def update_mood(command: str, mood: dict):
    """
    Apply a manual mood delta command like "+playfulness" or "-focus".
    Clamps values to [-5, 5].
    """
    try:
        change = 1 if command[0] == "+" else -1
        key    = command[1:]
        if key in mood:
            mood[key] = max(-5, min(5, mood[key] + change))
            print(f"✅ Mood: {key} = {mood[key]}")
    except Exception:
        print("⚠️  Use +key or -key (e.g. +playfulness)")
