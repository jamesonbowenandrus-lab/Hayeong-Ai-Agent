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
"""

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
IDENTITY_FILE  = BASE_DIR / "identity.json"
MOOD_FILE      = BASE_DIR / "mood.json"

OLLAMA_URL     = "http://localhost:11434/api/chat"
PRIMARY_MODEL  = "qwen2.5:14b"    # Main brain — smart, fits easily on 7900 XTX
FALLBACK_MODEL = "llama3.2:latest" # Fast lightweight fallback if primary fails

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

def load_identity():
    return load_json(IDENTITY_FILE, {})

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
                 dynamic_traits: dict = None, mood_state: dict = None) -> list:
    """
    Returns a messages list ready for Ollama /api/chat.
    Safe to call from Discord — no audio dependencies.
    """

    # ── Try full system_prompt_builder ──
    system_prompt = None
    try:
        from system_prompt_builder import build_system_prompt, detect_state_of_mind
        from long_term_memory import recall_for_prompt

        mood = mood_state or {}
        state_of_mind = detect_state_of_mind("casual", "home", mood)
        system_prompt = build_system_prompt(
            who="james", situation="casual",
            environment="home", state_of_mind=state_of_mind
        )

        long_term_context = recall_for_prompt(user_input, n_results=4)
        if long_term_context:
            system_prompt = long_term_context + "\n\n" + system_prompt

    except Exception:
        # Fallback: build a simple prompt from identity.json directly
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
    def _call(model: str) -> str:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": model, "messages": messages, "stream": False},
            timeout=90
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()

    try:
        return _call(PRIMARY_MODEL)
    except Exception as e:
        print(f"⚠️  Primary model failed ({e}), trying fallback...")
        try:
            return _call(FALLBACK_MODEL)
        except Exception as e2:
            return f"[Ollama unreachable: {e2}]"
