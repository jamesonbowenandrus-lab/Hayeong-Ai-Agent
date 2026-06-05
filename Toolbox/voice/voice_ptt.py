# voice_ptt.py
# Push-to-talk and toggle voice mode for Hayeong.
# Launched by main.py when you say "open your mic."
#
# Two modes:
#   PTT    — hold a key to speak to Hayeong (default: Right Shift)
#            release to send. Good when you're in a game with others.
#   TOGGLE — press a key once to start listening, again to stop.
#            Good for one-on-one conversations.
#
# Mode switching: press F8 to toggle between PTT and TOGGLE mode.
# Quit: press F9 (or Ctrl+C in terminal).
#
# Install:  pip install pynput
# The key bindings are configurable below.

import os
import sys
import time
import threading
import queue
import tempfile
import json
import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write as wav_write
from pynput import keyboard

# Add Hayeong's directory to path so we can import from main
HAYEONG_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HAYEONG_DIR)

from voice import (
    transcribe, speak, get_volume, show_thinking,
    get_tts, get_voice_modulation,
    SAMPLE_RATE, INPUT_DEVICE, VOLUME_THRESHOLD, OUTPUT_DEVICE
)
from hayeong_core import (
    chat_with_ai, build_prompt, adjust_mood_by_context,
    load_memory, save_memory, load_mood, save_json,
    load_identity, is_worth_remembering, MOOD_FILE
)
from long_term_memory import recall_for_prompt, remember, categorize
from system_prompt_builder import build_system_prompt, detect_state_of_mind

# ─────────────────────────────────────────────
# KEY CONFIGURATION
# Change these to whatever keys work for your setup.
# ─────────────────────────────────────────────

PTT_KEY         = keyboard.Key.shift_r   # hold to talk
MODE_SWITCH_KEY = keyboard.Key.f8        # toggle between PTT and TOGGLE mode
QUIT_KEY        = keyboard.Key.f9        # exit voice_ptt

# ─────────────────────────────────────────────
# AUDIO SETTINGS
# ─────────────────────────────────────────────

CHUNK_SECONDS    = 0.3    # how often to check volume while recording
MAX_RECORD_SECS  = 15     # hard cap per utterance
SILENCE_SECS     = 1.2    # stop recording after this much quiet (TOGGLE mode)
OLLAMA_URL       = "http://localhost:11435/api/chat"
PRIMARY_MODEL    = "llama3.2:latest"
FALLBACK_MODEL   = "llama3.2:latest"

# ─────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────

class VoicePTT:
    MODE_PTT    = "ptt"
    MODE_TOGGLE = "toggle"

    def __init__(self):
        self.mode           = self.MODE_PTT
        self.ptt_held       = False
        self.toggle_active  = False
        self.recording      = False
        self.should_quit    = False
        self.response_queue = queue.Queue()

        self.memory     = load_memory()
        self.mood_state = load_mood()
        self.identity   = load_identity()
        self.dynamic_traits = {
            "personality_intensity": 3,
            "emotional_warmth": 8,
            "tactical_intensity": 6,
            "motivation_style": "gently pushy",
            "teasing_level": "high"
        }

        print(self._banner())

    def _banner(self):
        return (
            "\n" + "─"*52 + "\n"
            "  Hayeong Voice PTT\n"
            f"  Mode: {self.mode.upper()}\n"
            f"  PTT key:    Right Shift (hold)\n"
            f"  Mode switch: F8\n"
            f"  Quit:        F9\n"
            "─"*52 + "\n"
            "  Waiting for you...\n"
        )

    # ─────────────────────────────────────────
    # RECORDING
    # ─────────────────────────────────────────

    def record_while_held(self) -> str:
        """PTT mode: record the entire time the key is held."""
        chunks = []
        chunk_samples = int(CHUNK_SECONDS * SAMPLE_RATE)
        max_chunks    = int(MAX_RECORD_SECS / CHUNK_SECONDS)

        print("🎙️  [PTT] Listening...", end="\r")
        self.recording = True

        for _ in range(max_chunks):
            if not self.ptt_held:
                break
            chunk = sd.rec(chunk_samples, samplerate=SAMPLE_RATE, channels=1, device=INPUT_DEVICE)
            sd.wait()
            chunks.append(chunk)

        self.recording = False

        if not chunks:
            return ""

        combined = np.concatenate(chunks, axis=0)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        wav_write(tmp.name, SAMPLE_RATE, combined)
        print("🎙️  [PTT] Processing...    ")
        return tmp.name

    def record_until_silence(self) -> str:
        """TOGGLE mode: record until silence detected."""
        chunks        = []
        silent_chunks = 0
        max_silent    = int(SILENCE_SECS / CHUNK_SECONDS)
        max_chunks    = int(MAX_RECORD_SECS / CHUNK_SECONDS)
        chunk_samples = int(CHUNK_SECONDS * SAMPLE_RATE)

        print("🎙️  [TOGGLE] Listening...", end="\r")
        self.recording = True

        for _ in range(max_chunks):
            if not self.toggle_active:
                break
            chunk = sd.rec(chunk_samples, samplerate=SAMPLE_RATE, channels=1, device=INPUT_DEVICE)
            sd.wait()
            chunks.append(chunk)

            vol = get_volume(chunk)
            if vol < VOLUME_THRESHOLD:
                silent_chunks += 1
                if silent_chunks >= max_silent:
                    break
            else:
                silent_chunks = 0

        self.recording = False
        self.toggle_active = False

        if not chunks:
            return ""

        combined = np.concatenate(chunks, axis=0)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        wav_write(tmp.name, SAMPLE_RATE, combined)
        print("🎙️  [TOGGLE] Processing...   ")
        return tmp.name

    # ─────────────────────────────────────────
    # AI RESPONSE
    # ─────────────────────────────────────────

    def respond(self, user_input: str):
        if not user_input.strip():
            return

        print(f"\nYou: {user_input}")
        adjust_mood_by_context(user_input, self.mood_state)

        prompt = build_prompt(
            self.identity, self.memory,
            user_input, self.dynamic_traits, self.mood_state
        )

        show_thinking()

        try:
            import requests
            messages = prompt
            def _call(model):
                r = requests.post(
                    OLLAMA_URL,
                    json={"model": model, "messages": messages, "stream": False},
                    timeout=60
                )
                return r.json()["message"]["content"].strip()
            try:
                ai_response = _call(PRIMARY_MODEL)
            except Exception:
                ai_response = _call(FALLBACK_MODEL)
        except Exception as e:
            print(f"⚠️  AI error: {e}")
            return

        print(f"Hayeong: {ai_response}")
        speak(ai_response, emotion="neutral")

        self.memory.append({"role": "user", "content": user_input})
        self.memory.append({"role": "AI",   "content": ai_response})
        save_memory(self.memory)
        save_json(MOOD_FILE, self.mood_state)

        if is_worth_remembering(user_input):
            remember(user_input, category=categorize(user_input), speaker="james")
        if is_worth_remembering(ai_response):
            remember(ai_response, category=categorize(ai_response), speaker="hayeong")

    # ─────────────────────────────────────────
    # KEY LISTENERS
    # ─────────────────────────────────────────

    def on_press(self, key):
        # Mode switch
        if key == MODE_SWITCH_KEY:
            self.mode = self.MODE_TOGGLE if self.mode == self.MODE_PTT else self.MODE_PTT
            print(f"\n🔄 Switched to {self.mode.upper()} mode")
            if self.mode == self.MODE_PTT:
                print("   Hold Right Shift to speak to Hayeong.")
            else:
                print("   Press Right Shift once to start, again to stop.")
            return

        # Quit
        if key == QUIT_KEY:
            print("\n👋 Closing voice PTT.")
            self.should_quit = True
            return

        # PTT mode: start recording on key down
        if key == PTT_KEY:
            if self.mode == self.MODE_PTT:
                if not self.ptt_held and not self.recording:
                    self.ptt_held = True
                    t = threading.Thread(target=self._ptt_record_and_respond, daemon=True)
                    t.start()
            elif self.mode == self.MODE_TOGGLE:
                if not self.toggle_active and not self.recording:
                    # Start listening
                    self.toggle_active = True
                    t = threading.Thread(target=self._toggle_record_and_respond, daemon=True)
                    t.start()
                elif self.toggle_active:
                    # Stop listening
                    self.toggle_active = False
                    print("\n🛑 Stopped listening.")

    def on_release(self, key):
        if key == PTT_KEY and self.mode == self.MODE_PTT:
            self.ptt_held = False

    def _ptt_record_and_respond(self):
        wav_path = self.record_while_held()
        if wav_path:
            text = transcribe(wav_path)
            if text:
                self.respond(text)
            else:
                print("   (nothing heard)")
        print("\n  Ready — hold Right Shift to speak.")

    def _toggle_record_and_respond(self):
        wav_path = self.record_until_silence()
        if wav_path:
            text = transcribe(wav_path)
            if text:
                self.respond(text)
            else:
                print("   (nothing heard)")
        print("\n  Ready — press Right Shift to speak.")

    # ─────────────────────────────────────────
    # RUN
    # ─────────────────────────────────────────

    def run(self):
        if self.mode == self.MODE_PTT:
            print("  Hold Right Shift to speak to Hayeong.")
            print("  (Your regular mic still works normally for other applications.)\n")
        else:
            print("  Press Right Shift once to speak, again to stop.\n")

        with keyboard.Listener(on_press=self.on_press, on_release=self.on_release) as listener:
            while not self.should_quit:
                time.sleep(0.1)
            listener.stop()


if __name__ == "__main__":
    ptt = VoicePTT()
    ptt.run()