# filler_system.py
# Hayeong's human-presence filler system.
#
# When there is a noticeable gap between hearing James and producing the
# first word, Hayeong fills that gap with a short contextually appropriate
# sound rather than silence — mirroring natural human floor-holding signals.
#
# Design constraints:
#   - Only fires above a delay threshold (~900ms). Below that she's fast enough
#     that a filler sounds unnatural.
#   - Not every delay gets a filler. Weighted probability by delay length.
#   - Context-sensitive: complex questions get thinking fillers, casual gets ack.
#   - Fillers are generated through the active TTS engine (Kokoro/F5-TTS)
#     so the voice matches exactly. Cached per session to avoid re-generating.
#   - Micro-variation (speed jitter, silence prefix, rotation) prevents repetition.

import threading
import time
import random
import numpy as np
import sounddevice as sd

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

DELAY_THRESHOLD_MS = 900    # below this, no filler (she's fast enough)

# Probability of firing a filler by delay bracket
# [min_ms, max_ms, probability 0.0-1.0]
DELAY_PROBABILITY = [
    (900,  1200, 0.25),
    (1200, 2000, 0.55),
    (2000, 3000, 0.85),
    (3000, None, 1.00),   # None = no upper bound
]

# Speed micro-variation — applied randomly to each filler play
SPEED_JITTER = 0.03   # ± this amount from base voice speed

# Max silence prefix before filler plays (ms) — makes timing feel less mechanical
MAX_SILENCE_PREFIX_MS = 80

# ─────────────────────────────────────────────
# FILLER CATEGORIES + CONTENT
# ─────────────────────────────────────────────

FILLERS = {
    "thinking": [
        "Hmm.",
        "Let me think.",
        "Okay…",
        "Hmm, let me think about that.",
    ],
    "acknowledgment": [
        "Yeah.",
        "Mm.",
        "Got it.",
        "Mm-hm.",
    ],
    "uncertainty": [
        "Uhh…",
        "Hm.",
        "Hmm…",
    ],
    "searching": [
        "Let me check.",
        "One sec.",
        "Give me a moment.",
    ],
}

# Map intent strings (from detect_intent) → filler category
INTENT_TO_CATEGORY = {
    "search":        "searching",
    "web_search":    "searching",
    "email_check":   "searching",
    "email_send":    "searching",
    "task_show":     "searching",
    "task_add":      "acknowledgment",
    "task":          "acknowledgment",
    "vision":        "thinking",
    "image_gen":     "thinking",
    "none":          "acknowledgment",
}

DEFAULT_CATEGORY = "thinking"

# ─────────────────────────────────────────────
# SESSION AUDIO CACHE
# Each unique filler text is generated once per session and reused.
# ─────────────────────────────────────────────

_cache: dict[str, np.ndarray] = {}   # text → float32 stereo audio array
_cache_lock = threading.Lock()


def _generate_audio(text: str, speed: float) -> np.ndarray | None:
    """
    Generate audio for a filler string via Kokoro (primary) or F5-TTS (fallback).
    Returns float32 stereo numpy array at 24000 Hz, or None on failure.
    """
    try:
        from voice import (
            get_pipeline, KOKORO_AVAILABLE, HAYEONG_VOICE,
            get_tts, F5TTS_AVAILABLE, REF_AUDIO, REF_TEXT,
        )

        chunks = []

        if KOKORO_AVAILABLE:
            pipeline = get_pipeline()
            if pipeline is not None:
                for _, _, audio in pipeline(text, voice=HAYEONG_VOICE, speed=speed):
                    chunks.append(audio)

        if not chunks and F5TTS_AVAILABLE:
            tts = get_tts()
            if tts is not None:
                wav, _, _ = tts.infer(
                    ref_file=REF_AUDIO, ref_text=REF_TEXT,
                    gen_text=text, nfe_step=64, speed=speed,
                )
                chunks.append(wav)

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
        return audio

    except Exception as e:
        print(f"   [Filler] TTS error: {e}")
        return None


def _get_cached_audio(text: str, speed: float) -> np.ndarray | None:
    """Return cached audio for text, generating it on first call."""
    with _cache_lock:
        if text not in _cache:
            audio = _generate_audio(text, speed)
            if audio is not None:
                _cache[text] = audio
        return _cache.get(text)


# ─────────────────────────────────────────────
# FILLER SELECTION
# ─────────────────────────────────────────────

# Per-category rotation state — avoids always picking the first variant
_rotation: dict[str, int] = {}


def _pick_filler(category: str) -> str:
    variants = FILLERS.get(category, FILLERS[DEFAULT_CATEGORY])
    idx = _rotation.get(category, 0)
    text = variants[idx % len(variants)]
    _rotation[category] = (idx + 1) % len(variants)
    return text


def _should_fire(delay_ms: float) -> bool:
    """Returns True if a filler should play at this delay, based on probability table."""
    if delay_ms < DELAY_THRESHOLD_MS:
        return False
    for min_ms, max_ms, prob in DELAY_PROBABILITY:
        in_range = delay_ms >= min_ms and (max_ms is None or delay_ms < max_ms)
        if in_range:
            return random.random() < prob
    return False


def _category_for_intent(intent: str) -> str:
    return INTENT_TO_CATEGORY.get(intent, DEFAULT_CATEGORY)


# ─────────────────────────────────────────────
# FILLER TIMER — main public interface
# ─────────────────────────────────────────────

class FillerTimer:
    """
    Start this when transcription completes.
    Cancel it when the LLM produces its first token.

    If the LLM doesn't beat the threshold, the filler fires automatically
    on a background thread — non-blocking to the main pipeline.

    Usage:
        filler = FillerTimer(intent="search", base_speed=0.88)
        filler.start()
        # ... LLM generating ...
        filler.cancel()   # call this the moment first token arrives
    """

    def __init__(self, intent: str = "none", base_speed: float = 0.88,
                 output_device: int | None = None):
        self._intent        = intent
        self._base_speed    = base_speed
        self._output_device = output_device
        self._timer: threading.Timer | None = None
        self._fired         = False
        self._cancelled     = False

    def start(self):
        """Start the filler timer. Call immediately after transcription completes."""
        # Warm the cache for likely fillers in the background
        threading.Thread(target=self._warm_cache, daemon=True).start()

        # Fire after threshold — but we don't know actual delay yet,
        # so we use a single timer at the minimum threshold. The probability
        # gate inside _on_timer handles the rest.
        self._timer = threading.Timer(
            DELAY_THRESHOLD_MS / 1000.0,
            self._on_timer,
            args=[time.monotonic()],
        )
        self._timer.daemon = True
        self._timer.start()

    def cancel(self):
        """Cancel the filler. Call the moment the LLM produces its first token."""
        self._cancelled = True
        if self._timer:
            self._timer.cancel()

    def _warm_cache(self):
        """Pre-generate audio for the likely filler so it's ready when needed."""
        category = _category_for_intent(self._intent)
        text     = _pick_filler(category)
        _get_cached_audio(text, self._base_speed)

    def _on_timer(self, start_time: float):
        if self._cancelled or self._fired:
            return

        elapsed_ms = (time.monotonic() - start_time) * 1000 + DELAY_THRESHOLD_MS

        if not _should_fire(elapsed_ms):
            return

        self._fired = True
        category    = _category_for_intent(self._intent)
        text        = _pick_filler(category)

        # Micro-variation: speed jitter + silence prefix
        speed   = self._base_speed + random.uniform(-SPEED_JITTER, SPEED_JITTER)
        prefix_ms = random.randint(0, MAX_SILENCE_PREFIX_MS)

        audio = _get_cached_audio(text, self._base_speed)   # use base speed for cache hit
        if audio is None:
            return

        try:
            from voice import OUTPUT_DEVICE
            device = self._output_device if self._output_device is not None else OUTPUT_DEVICE

            if prefix_ms > 0:
                prefix_samples = int(prefix_ms / 1000.0 * 24000)
                prefix = np.zeros((prefix_samples, 2), dtype=np.float32)
                time.sleep(prefix_ms / 1000.0)

            sd.play(audio, samplerate=24000, device=device)
            sd.wait()
            print(f"   [Filler] '{text}' ({category}, {elapsed_ms:.0f}ms delay)")
        except Exception as e:
            print(f"   [Filler] playback error: {e}")


# ─────────────────────────────────────────────
# DEBUG / TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    print("Filler system test — generating and playing each category...")

    from voice import get_voice_modulation
    speed = get_voice_modulation("neutral")["speed"]

    for category, variants in FILLERS.items():
        for text in variants:
            print(f"  [{category}] '{text}'")
            audio = _generate_audio(text, speed)
            if audio is not None:
                sd.play(audio, samplerate=24000)
                sd.wait()
                time.sleep(0.4)
            else:
                print("    ⚠️  No audio generated")

    print("Done.")
