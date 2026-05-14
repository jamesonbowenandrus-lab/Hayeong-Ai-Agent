"""
toolbox/voice/voice_output.py

Streamed sentence-by-sentence TTS output for Hayeong's presence loop.
Called by main.py after every for_james response is printed.

This module handles the auto-speak path. It is separate from voice_tool.py
(which handles explicit voice tasks assigned by the reasoning LLM).

Design:
- Splits the response into sentences
- Synthesizes and plays each sentence immediately — no waiting for full assembly
- Kokoro TTS primary, F5-TTS fallback
- Runs in a daemon thread — does not block the presence loop
- New response arriving while previous is still playing: old one stops cleanly

Usage:
    from toolbox.voice.voice_output import speak_streamed
    speak_streamed(text, emotion="neutral")
"""

import sys
import threading
import time
import numpy as np
from pathlib import Path

VOICE_DIR = Path(__file__).parent
if str(VOICE_DIR) not in sys.path:
    sys.path.insert(0, str(VOICE_DIR))

# ── State ──────────────────────────────────────────────────────────────
_stop_event   = threading.Event()
_speak_thread = None


# ── Public API ─────────────────────────────────────────────────────────

def speak_streamed(text: str, emotion: str = "neutral"):
    """
    Speak text streamed sentence-by-sentence in a background daemon thread.
    Interrupts any currently playing speech before starting.
    Returns immediately — does not block the caller.
    """
    if not text or not text.strip():
        return

    _interrupt()

    global _speak_thread
    _speak_thread = threading.Thread(
        target=_stream_speak,
        args=(text, emotion, _stop_event),
        daemon=True,
        name="hayeong_tts",
    )
    _speak_thread.start()


def interrupt():
    """Stop any currently playing TTS immediately."""
    _interrupt()


# ── Internal ───────────────────────────────────────────────────────────

def _interrupt():
    global _stop_event, _speak_thread
    _stop_event.set()
    if _speak_thread and _speak_thread.is_alive():
        _speak_thread.join(timeout=0.5)
    _stop_event = threading.Event()


def _stream_speak(text: str, emotion: str, stop: threading.Event):
    """
    Core streaming TTS. Runs in a daemon thread.
    Synthesizes and plays each sentence in sequence.
    Checks stop between sentences for clean interruption.
    """
    try:
        from voice import (
            split_sentences, get_voice_modulation,
            get_pipeline, KOKORO_AVAILABLE, HAYEONG_VOICE,
            get_tts, F5TTS_AVAILABLE, REF_AUDIO, REF_TEXT,
            OUTPUT_DEVICE,
        )
        import sounddevice as sd
    except ImportError as e:
        print(f"[voice_output] Import error: {e}")
        return

    sentences   = split_sentences(text)
    speed       = get_voice_modulation(emotion)["speed"]
    sample_rate = 24000

    for i, sentence in enumerate(sentences):
        if stop.is_set():
            break
        if not sentence.strip():
            continue

        audio = _synthesize_sentence(
            sentence, speed, sample_rate,
            KOKORO_AVAILABLE, HAYEONG_VOICE,
            get_pipeline,
            F5TTS_AVAILABLE, REF_AUDIO, REF_TEXT,
            get_tts,
        )

        if audio is None or stop.is_set():
            break

        peak = np.abs(audio).max()
        if peak > 1.0:
            audio = audio / peak

        if audio.ndim == 1:
            audio = np.stack([audio, audio], axis=1)

        if i == len(sentences) - 1:
            silence = np.zeros((int(0.6 * sample_rate), 2), dtype=np.float32)
            audio = np.vstack([audio, silence])

        try:
            sd.play(audio, samplerate=sample_rate, device=OUTPUT_DEVICE)
            sd.wait()
        except Exception as e:
            print(f"[voice_output] Playback error: {e}")
            break

        if i < len(sentences) - 1 and not stop.is_set():
            time.sleep(0.18)


def _synthesize_sentence(
    sentence: str,
    speed: float,
    sample_rate: int,
    kokoro_available: bool,
    hayeong_voice: str,
    get_pipeline,
    f5tts_available: bool,
    ref_audio: str,
    ref_text: str,
    get_tts,
) -> "np.ndarray | None":
    """Synthesize one sentence. Returns float32 numpy array or None."""

    if kokoro_available:
        try:
            pipeline = get_pipeline()
            if pipeline is not None:
                chunks = []
                for _, _, audio in pipeline(sentence, voice=hayeong_voice, speed=speed):
                    chunks.append(audio)
                if chunks:
                    return np.concatenate(chunks)
        except Exception as e:
            print(f"[voice_output] Kokoro error: {e}")

    if f5tts_available:
        try:
            tts = get_tts()
            if tts is not None:
                wav, _sr, _ = tts.infer(
                    ref_file=ref_audio,
                    ref_text=ref_text,
                    gen_text=sentence,
                    nfe_step=64,
                    speed=speed,
                )
                return wav
        except Exception as e:
            print(f"[voice_output] F5-TTS error: {e}")

    return None
