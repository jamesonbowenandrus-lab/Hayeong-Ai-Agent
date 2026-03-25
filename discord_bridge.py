"""
discord_bridge.py
─────────────────
TCP bridge between discord_hayeong.js and Hayeong's Python AI stack.

discord_hayeong.js connects here on port 9877.
This module:
  - Receives text messages and voice WAV files from the JS bot
  - Runs Whisper transcription on voice audio
  - Calls Ollama for AI responses via hayeong_core
  - Generates F5-TTS audio files
  - Sends back file paths / text for the JS bot to deliver

Called from main.py as a background thread on startup.
Can also be run standalone for testing:
  python discord_bridge.py
"""

import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

BASE_DIR    = Path(__file__).parent
BRIDGE_PORT = 9877
TMP_DIR     = BASE_DIR / "tmp_audio"
TMP_DIR.mkdir(parents=True, exist_ok=True)

# ── Safe imports — fail gracefully if not available ──
try:
    from hayeong_core import (
        build_prompt, chat_with_ai,
        load_identity, load_memory, load_mood,
        save_memory, save_json, adjust_mood_by_context,
        MOOD_FILE,
    )
    CORE_AVAILABLE = True
except ImportError as e:
    print(f"⚠️  [DiscordBridge] hayeong_core not available: {e}")
    CORE_AVAILABLE = False

try:
    from faster_whisper import WhisperModel
    _whisper = WhisperModel("base", compute_type="int8")
    WHISPER_AVAILABLE = True
    print("[DiscordBridge] Whisper ready")
except ImportError:
    WHISPER_AVAILABLE = False
    print("⚠️  [DiscordBridge] faster-whisper not installed — voice input disabled")

try:
    from f5_tts.api import F5TTS as _F5TTS
    _F5_VOICE_REF = str(BASE_DIR / "voice_prep" / "samples" / "source_5secs.wav")
    _F5_REF_TEXT  = "Before the video starts, I want to make a quick announcement."
    F5TTS_AVAILABLE = os.path.exists(_F5_VOICE_REF)
    _f5_model = None  # lazy load
    if not F5TTS_AVAILABLE:
        print("⚠️  [DiscordBridge] F5-TTS voice ref not found — TTS disabled")
except ImportError:
    F5TTS_AVAILABLE = False
    print("⚠️  [DiscordBridge] f5_tts not installed — TTS disabled")


# ─────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────

identity   = load_identity()  if CORE_AVAILABLE else {}
memory     = load_memory()    if CORE_AVAILABLE else []
mood_state = load_mood()      if CORE_AVAILABLE else {}

dynamic_traits = {
    "personality_intensity": 3,
    "emotional_warmth":      8,
    "tactical_intensity":    6,
    "motivation_style":      "gently pushy",
    "teasing_level":         "high",
}

# Track connected JS client
_js_writer = None
_writer_lock = threading.Lock()


# ─────────────────────────────────────────────
# SEND TO JS BOT
# ─────────────────────────────────────────────

def send_to_js(obj: dict):
    """Send a JSON message to the connected discord_hayeong.js instance."""
    with _writer_lock:
        if _js_writer is None:
            return
        try:
            _js_writer(json.dumps(obj) + "\n")
        except Exception as e:
            print(f"⚠️  [DiscordBridge] Send failed: {e}")


# ─────────────────────────────────────────────
# TTS
# ─────────────────────────────────────────────

def generate_tts(text: str) -> "str | None":
    """
    Generate TTS audio using F5-TTS.
    Returns path to WAV file, or None on failure.
    """
    global _f5_model

    if not F5TTS_AVAILABLE:
        return None

    try:
        if _f5_model is None:
            print("[DiscordBridge] Loading F5-TTS model...")
            _f5_model = _F5TTS()
            print("[DiscordBridge] F5-TTS ready")

        import numpy as np
        from scipy.io.wavfile import write as wav_write

        wav, sr, _ = _f5_model.infer(
            ref_file = _F5_VOICE_REF,
            ref_text = _F5_REF_TEXT,
            gen_text = text,
            nfe_step = 32,
            speed    = 0.95,
        )

        audio = np.array(wav, dtype=np.float32)
        peak  = np.abs(audio).max()
        if peak > 1.0:
            audio = audio / peak

        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".wav", dir=str(TMP_DIR)
        )
        tmp.close()
        wav_write(tmp.name, sr, audio)
        return tmp.name

    except Exception as e:
        print(f"⚠️  [DiscordBridge] TTS error: {e}")
        return None


# ─────────────────────────────────────────────
# WHISPER TRANSCRIPTION
# ─────────────────────────────────────────────

def transcribe_audio(wav_path: str) -> str:
    """Transcribe a WAV file using faster-whisper. Returns text or empty string."""
    if not WHISPER_AVAILABLE:
        return ""
    try:
        segments, _ = _whisper.transcribe(wav_path, language="en", vad_filter=True)
        return "".join(s.text for s in segments).strip()
    except Exception as e:
        print(f"⚠️  [DiscordBridge] Whisper error: {e}")
        return ""


# ─────────────────────────────────────────────
# AI RESPONSE
# ─────────────────────────────────────────────

def get_ai_response(user_text: str) -> str:
    """Get Hayeong's response to user_text. Updates memory."""
    global memory, mood_state

    if not CORE_AVAILABLE:
        return "I'm having trouble connecting to my brain right now."

    adjust_mood_by_context(user_text, mood_state)
    prompt      = build_prompt(identity, memory, user_text, dynamic_traits, mood_state)
    ai_response = chat_with_ai(prompt)

    memory.append({"role": "user", "content": user_text})
    memory.append({"role": "AI",   "content": ai_response})
    save_memory(memory)
    save_json(MOOD_FILE, mood_state)

    return ai_response


# ─────────────────────────────────────────────
# MESSAGE HANDLERS
# ─────────────────────────────────────────────

def handle_text_message(msg: dict):
    """Handle a text message from Discord — get AI response + TTS."""
    user_text = msg.get("text", "").strip()
    if not user_text:
        return

    source = msg.get("source", "discord_text")
    print(f"💬 [Discord text]: {user_text[:80]}")

    # Get AI response in a thread so we don't block the bridge
    def _process():
        ai_response = get_ai_response(user_text)
        print(f"🤖 Hayeong: {ai_response[:80]}...")

        # Send text reply to Discord channel
        send_to_js({
            "type":   "text_reply",
            "text":   ai_response,
            "source": source,
        })

        # Generate TTS and send file path for playback in voice channel
        tts_path = generate_tts(ai_response)
        if tts_path:
            send_to_js({
                "type":      "speak",
                "file_path": tts_path,
            })

    threading.Thread(target=_process, daemon=True).start()


def handle_voice_audio(msg: dict):
    """Handle a voice WAV file from Discord — transcribe + respond."""
    wav_path = msg.get("file_path", "")
    if not wav_path or not os.path.exists(wav_path):
        return

    print(f"🎙️  Voice audio received: {wav_path}")

    def _process():
        # Transcribe
        text = transcribe_audio(wav_path)

        # Clean up WAV file
        try:
            os.remove(wav_path)
        except Exception:
            pass

        if not text:
            print("   (no speech detected)")
            return

        print(f"🎙️  Heard: {text!r}")

        # Get AI response + TTS
        ai_response = get_ai_response(text)
        print(f"🤖 Hayeong: {ai_response[:80]}...")

        # Echo what was heard + send reply to text channel
        send_to_js({
            "type":   "text_reply",
            "text":   ai_response,
            "source": "voice",
        })

        # TTS playback in voice channel
        tts_path = generate_tts(ai_response)
        if tts_path:
            send_to_js({
                "type":      "speak",
                "file_path": tts_path,
            })

    threading.Thread(target=_process, daemon=True).start()


def handle_message(msg: dict):
    msg_type = msg.get("type", "")

    if msg_type == "ready":
        print("[DiscordBridge] discord_hayeong.js connected and ready")
        send_to_js({"type": "status", "message": "Python bridge ready"})

    elif msg_type == "text_message":
        handle_text_message(msg)

    elif msg_type == "voice_audio_file":
        handle_voice_audio(msg)

    elif msg_type == "shutdown":
        print("[DiscordBridge] JS bot shutting down")

    else:
        print(f"[DiscordBridge] Unknown message type: {msg_type}")


# ─────────────────────────────────────────────
# TCP SERVER
# ─────────────────────────────────────────────

def run_bridge_server():
    """
    Run the TCP bridge server. Blocks until the process exits.
    Call this in a background thread from main.py.
    """
    global _js_writer

    import socket

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", BRIDGE_PORT))
    server.listen(1)
    print(f"[DiscordBridge] Listening on port {BRIDGE_PORT}...")

    while True:
        try:
            conn, addr = server.accept()
            print(f"[DiscordBridge] JS bot connected from {addr}")
            buf = ""

            def _send(data: str):
                try:
                    conn.sendall(data.encode("utf-8"))
                except Exception:
                    pass

            with _writer_lock:
                _js_writer = _send

            try:
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    buf += chunk.decode("utf-8", errors="replace")
                    while "\n" in buf:
                        idx  = buf.index("\n")
                        line = buf[:idx].strip()
                        buf  = buf[idx + 1:]
                        if not line:
                            continue
                        try:
                            handle_message(json.loads(line))
                        except json.JSONDecodeError:
                            print(f"[DiscordBridge] Bad JSON: {line[:80]}")
            except Exception as e:
                print(f"[DiscordBridge] Connection error: {e}")
            finally:
                with _writer_lock:
                    _js_writer = None
                conn.close()
                print("[DiscordBridge] JS bot disconnected")

        except Exception as e:
            print(f"[DiscordBridge] Server error: {e}")
            time.sleep(1)


# ─────────────────────────────────────────────
# MAIN — for running standalone
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Discord Bridge — Standalone Mode ===")
    print(f"Whisper: {'✅' if WHISPER_AVAILABLE else '❌'}")
    print(f"F5-TTS:  {'✅' if F5TTS_AVAILABLE else '❌'}")
    print(f"Core:    {'✅' if CORE_AVAILABLE else '❌'}")
    print()
    run_bridge_server()
