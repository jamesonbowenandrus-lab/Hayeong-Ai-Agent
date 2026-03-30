# voice_server.py
# Hayeong's voice pipeline exposed as a FastAPI WebSocket server.
#
# WHY THIS ARCHITECTURE:
#   The same server handles both desktop use and the future iOS/iPad app.
#   Local client connects over localhost. Phone connects over Tailscale.
#   The middle — Whisper → Hayeong → F5-TTS — is identical in both cases.
#   Build once, inherit everywhere.
#
# ENDPOINTS:
#   WS  /ws/voice   — main voice pipeline (audio in, audio out)
#   GET /health     — quick status check (server alive, models loaded)
#
# WEBSOCKET PROTOCOL:
#   Client → Server:
#     {"type": "audio_start"}              — begin audio stream
#     <binary PCM frames>                  — raw int16 audio at 16000Hz mono
#     {"type": "audio_end"}               — done speaking, process now
#     {"type": "text_message", "text": "…"} — text input (skip audio path)
#     {"type": "ping"}                     — keepalive
#
#   Server → Client:
#     {"type": "transcript", "text": "…"}  — what Whisper heard
#     {"type": "thinking"}                 — AI is generating
#     {"type": "response_text", "text": "…", "emotion": "…"} — Hayeong's reply
#     <binary PCM frames>                  — F5-TTS audio at 24000Hz stereo
#     {"type": "audio_done"}              — audio stream finished
#     {"type": "error", "message": "…"}   — something went wrong
#     {"type": "pong"}                     — keepalive reply
#
# AUDIO FORMAT:
#   Incoming: int16, 16000Hz, mono
#   Outgoing: float32, 24000Hz, stereo (matches F5-TTS native output)
#   Chunk size: 4096 samples (~170ms at 24kHz) — smooth streaming
#
# INSTALL:
#   pip install fastapi uvicorn websockets
#   (voice.py dependencies already required)
#
# RUN:
#   python voice_server.py
#   Or from start_hayeong.bat alongside main.py
#
# CONNECT (local):
#   ws://localhost:8765/ws/voice
#
# CONNECT (remote via Tailscale):
#   ws://<tailscale-ip>:8765/ws/voice

import asyncio
import json
import logging
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from scipy.io.wavfile import write as wav_write

# ─────────────────────────────────────────────
# PATH SETUP
# ─────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [VoiceServer] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("voice_server")

# ─────────────────────────────────────────────
# LAZY IMPORTS — load heavy models once on first use
# ─────────────────────────────────────────────

_voice_loaded   = False
_core_loaded    = False
_whisper_model  = None
_tts_instance   = None
_speak_fn       = None
_transcribe_fn  = None
_chat_fn        = None
_build_prompt   = None
_load_memory    = None
_save_memory    = None
_load_mood      = None
_save_json      = None
_load_identity  = None
_adjust_mood    = None
_MOOD_FILE      = None
_remember_fn    = None
_recall_fn      = None
_build_system_prompt = None

def _load_voice_modules():
    global _voice_loaded, _speak_fn, _transcribe_fn
    if _voice_loaded:
        return
    log.info("Loading voice modules (Whisper + F5-TTS)...")
    from voice import speak, transcribe
    _speak_fn       = speak
    _transcribe_fn  = transcribe
    _voice_loaded   = True
    log.info("✅ Voice modules ready")

def _load_core_modules():
    global _core_loaded
    global _chat_fn, _build_prompt, _load_memory, _save_memory
    global _load_mood, _save_json, _load_identity, _adjust_mood
    global _MOOD_FILE, _remember_fn, _recall_fn, _build_system_prompt
    if _core_loaded:
        return
    log.info("Loading core modules...")
    try:
        from hayeong_core import (
            chat_with_ai, build_prompt, load_memory, save_memory,
            load_mood, save_json, load_identity, adjust_mood_by_context,
            MOOD_FILE
        )
        from long_term_memory import remember, recall_for_prompt
        from system_prompt_builder import build_system_prompt
        _chat_fn           = chat_with_ai
        _build_prompt      = build_prompt
        _load_memory       = load_memory
        _save_memory       = save_memory
        _load_mood         = load_mood
        _save_json         = save_json
        _load_identity     = load_identity
        _adjust_mood       = adjust_mood_by_context
        _MOOD_FILE         = MOOD_FILE
        _remember_fn       = remember
        _recall_fn         = recall_for_prompt
        _build_system_prompt = build_system_prompt
        _core_loaded       = True
        log.info("✅ Core modules ready")
    except ImportError as e:
        log.warning(f"Core modules not available: {e} — AI responses disabled")


# ─────────────────────────────────────────────
# SERVER STATE
# One active connection at a time (personal use).
# A lock prevents two simultaneous generations.
# ─────────────────────────────────────────────

_generation_lock = asyncio.Lock()
_server_start    = time.time()

# ─────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────

app = FastAPI(title="Hayeong Voice Server", version="1.0")


# ─────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────

@app.get("/health")
async def health():
    return JSONResponse({
        "status":       "online",
        "voice_loaded": _voice_loaded,
        "core_loaded":  _core_loaded,
        "uptime_s":     round(time.time() - _server_start),
    })


# ─────────────────────────────────────────────
# AUDIO HELPERS
# ─────────────────────────────────────────────

def _pcm_bytes_to_wav(pcm_bytes: bytes, sample_rate: int = 16000) -> str:
    """Convert raw int16 PCM bytes to a temp WAV file for Whisper."""
    audio = np.frombuffer(pcm_bytes, dtype=np.int16)
    tmp   = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    wav_write(tmp.name, sample_rate, audio)
    tmp.close()
    return tmp.name


def _audio_to_pcm_chunks(audio: np.ndarray, chunk_size: int = 4096) -> list:
    """
    Split F5-TTS float32 audio into sendable binary chunks.
    Converts to int16 for network efficiency (~50% smaller than float32).
    Receiver converts back to float32 for playback.
    """
    # Normalize
    peak = np.abs(audio).max()
    if peak > 0:
        audio = audio / max(peak, 1.0)

    # To int16
    audio_int16 = (audio * 32767).astype(np.int16)

    # Split into chunks
    chunks = []
    for i in range(0, len(audio_int16), chunk_size):
        chunks.append(audio_int16[i:i + chunk_size].tobytes())
    return chunks


# ─────────────────────────────────────────────
# AI RESPONSE (runs in thread — not async)
# ─────────────────────────────────────────────

def _get_ai_response(user_text: str, memory: list, mood_state: dict,
                      identity: dict, dynamic_traits: dict) -> tuple[str, str]:
    """
    Returns (response_text, emotion_key).
    Runs in a thread executor so it doesn't block the event loop.
    """
    if not _core_loaded:
        return "Core modules aren't loaded right now.", "neutral"

    try:
        _adjust_mood(user_text, mood_state)
        prompt   = _build_prompt(identity, memory, user_text, dynamic_traits, mood_state)
        response = _chat_fn(prompt)
        emotion  = "neutral"  # future: parse emotion from response metadata
        return response, emotion
    except Exception as e:
        log.error(f"AI response error: {e}")
        return "Something went wrong on my end.", "neutral"


def _generate_tts_audio(text: str, emotion: str = "neutral") -> np.ndarray | None:
    """
    Generate F5-TTS audio. Returns float32 numpy array or None on failure.
    Runs in a thread executor.
    """
    if not _voice_loaded:
        return None
    try:
        import io
        import soundfile as sf
        from voice import get_tts, get_voice_modulation, split_sentences, REF_AUDIO, REF_TEXT

        tts        = get_tts()
        modulation = get_voice_modulation(emotion)
        speed      = modulation["speed"]
        sentences  = split_sentences(text)
        chunks     = []
        sample_rate = 24000

        for sentence in sentences:
            wav, sr, _ = tts.infer(
                ref_file = REF_AUDIO,
                ref_text = REF_TEXT,
                gen_text = sentence,
                nfe_step = 64,
                speed    = speed,
            )
            chunks.append(wav)
            sample_rate = sr

        if not chunks:
            return None

        # Breath gaps between sentences
        breath = np.zeros(int(0.18 * sample_rate), dtype=np.float32)
        with_breaths = []
        for i, chunk in enumerate(chunks):
            with_breaths.append(chunk)
            if i < len(chunks) - 1:
                with_breaths.append(breath)

        combined = np.concatenate(with_breaths)

        if combined.dtype != np.float32:
            combined = combined.astype(np.float32)

        # Mono → stereo
        if combined.ndim == 1:
            combined = np.stack([combined, combined], axis=1)

        # Trailing silence so client playback doesn't cut off
        silence = np.zeros((int(0.6 * sample_rate), 2), dtype=np.float32)
        combined = np.vstack([combined, silence])

        return combined

    except Exception as e:
        log.error(f"F5-TTS error: {e}")
        return None


# ─────────────────────────────────────────────
# SEND HELPERS
# ─────────────────────────────────────────────

async def _send_json(ws: WebSocket, obj: dict):
    try:
        await ws.send_text(json.dumps(obj))
    except Exception:
        pass

async def _send_binary(ws: WebSocket, data: bytes):
    try:
        await ws.send_bytes(data)
    except Exception:
        pass


# ─────────────────────────────────────────────
# PIPELINE — process one utterance end to end
# ─────────────────────────────────────────────

async def _process_utterance(ws: WebSocket, user_text: str,
                               memory: list, mood_state: dict,
                               identity: dict, dynamic_traits: dict):
    """
    Full pipeline: text → AI → TTS → stream audio back.
    Called after Whisper transcription or direct text input.
    """
    async with _generation_lock:

        # 1. AI response (in thread — blocks GPU)
        await _send_json(ws, {"type": "thinking"})

        loop     = asyncio.get_event_loop()
        response, emotion = await loop.run_in_executor(
            None, _get_ai_response,
            user_text, memory, mood_state, identity, dynamic_traits
        )

        # 2. Send text response immediately so client can display it
        await _send_json(ws, {
            "type":    "response_text",
            "text":    response,
            "emotion": emotion,
        })

        # 3. Generate TTS audio (in thread — blocks GPU)
        audio = await loop.run_in_executor(
            None, _generate_tts_audio, response, emotion
        )

        if audio is not None:
            # 4. Stream audio in chunks
            chunks = _audio_to_pcm_chunks(audio.flatten() if audio.ndim > 1 else audio)
            for chunk in chunks:
                await _send_binary(ws, chunk)
                await asyncio.sleep(0)  # yield to event loop between chunks

        # 5. Signal audio stream complete
        await _send_json(ws, {"type": "audio_done"})

        # 6. Save to memory
        if _core_loaded:
            memory.append({"role": "user",  "content": user_text})
            memory.append({"role": "AI",    "content": response})
            try:
                _save_memory(memory)
                _save_json(_MOOD_FILE, mood_state)
            except Exception as e:
                log.warning(f"Memory save error: {e}")


# ─────────────────────────────────────────────
# WEBSOCKET HANDLER
# ─────────────────────────────────────────────

@app.websocket("/ws/voice")
async def voice_ws(websocket: WebSocket):
    await websocket.accept()
    client = websocket.client
    log.info(f"Client connected: {client}")

    # Load modules on first connection
    loop = asyncio.get_event_loop()
    if not _voice_loaded:
        await loop.run_in_executor(None, _load_voice_modules)
    if not _core_loaded:
        await loop.run_in_executor(None, _load_core_modules)

    # Per-connection state
    memory        = _load_memory()   if _core_loaded else []
    mood_state    = _load_mood()     if _core_loaded else {}
    identity      = _load_identity() if _core_loaded else {}
    dynamic_traits = {
        "personality_intensity": 3,
        "emotional_warmth":      8,
        "tactical_intensity":    6,
        "motivation_style":      "gently pushy",
        "teasing_level":         "high",
    }

    audio_buffer: list[bytes] = []
    receiving_audio = False

    try:
        while True:
            message = await websocket.receive()

            # ── Binary audio frame ──
            if "bytes" in message and message["bytes"] is not None:
                if receiving_audio:
                    audio_buffer.append(message["bytes"])
                continue

            # ── JSON control message ──
            if "text" in message and message["text"] is not None:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type", "")

                if msg_type == "audio_start":
                    audio_buffer    = []
                    receiving_audio = True
                    log.info("Audio stream started")

                elif msg_type == "audio_end":
                    receiving_audio = False
                    if not audio_buffer:
                        log.info("Empty audio received — skipping")
                        continue

                    log.info(f"Audio stream ended — {len(audio_buffer)} chunks received")

                    # Transcribe in thread
                    pcm_bytes = b"".join(audio_buffer)
                    audio_buffer = []

                    wav_path = _pcm_bytes_to_wav(pcm_bytes)
                    text = await loop.run_in_executor(None, _transcribe_fn, wav_path)

                    if not text or not text.strip():
                        log.info("Nothing transcribed — skipping")
                        continue

                    log.info(f"Transcribed: {text!r}")
                    await _send_json(websocket, {"type": "transcript", "text": text})

                    # Full pipeline
                    await _process_utterance(
                        websocket, text,
                        memory, mood_state, identity, dynamic_traits
                    )

                elif msg_type == "text_message":
                    # Direct text input — skip audio path entirely
                    text = data.get("text", "").strip()
                    if text:
                        log.info(f"Text message: {text!r}")
                        await _process_utterance(
                            websocket, text,
                            memory, mood_state, identity, dynamic_traits
                        )

                elif msg_type == "ping":
                    await _send_json(websocket, {"type": "pong"})

                else:
                    log.warning(f"Unknown message type: {msg_type!r}")

    except WebSocketDisconnect:
        log.info(f"Client disconnected: {client}")
    except Exception as e:
        log.error(f"WebSocket error: {e}")
        try:
            await _send_json(websocket, {"type": "error", "message": str(e)})
        except Exception:
            pass


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    log.info("─" * 52)
    log.info("  Hayeong Voice Server")
    log.info("  ws://localhost:8765/ws/voice")
    log.info("  GET http://localhost:8765/health")
    log.info("─" * 52)

    # Pre-load models on startup so first conversation isn't slow
    log.info("Pre-loading models...")
    _load_voice_modules()
    _load_core_modules()
    log.info("✅ All models loaded — server starting")

    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="warning")