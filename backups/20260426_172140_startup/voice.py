# voice.py
# Hayeong's local voice system.
# Handles: wake word detection, speech-to-text, text-to-speech.
#
# TTS Engine: Kokoro-82M (primary) — fast synthesis on RTX 3090 via CUDA.
#             F5-TTS retained as fallback until Kokoro is confirmed stable.
#
# Dependencies:
#   pip install sounddevice scipy numpy soundfile openai-whisper
#   pip install kokoro>=0.9.2
#   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
#   Also required: espeak-ng installed on Windows (system-level, not pip)
#
# GPU: NVIDIA RTX 3090 — full CUDA, no DirectML workarounds needed.
#
# Devices:
#   INPUT_DEVICE  3  → HyperX QuadCast S (MME)
#   OUTPUT_DEVICE 6  → SteelSeries Sonar - Gaming (MME)
#   Run: python voice.py devices  to list all available device indices.

import sounddevice as sd
from scipy.io.wavfile import write as wav_write
import tempfile
import os
import re
import time
import numpy as np
import soundfile as sf
import torch
import whisper

# ── Live2D lip sync amplitude feed ──
# Import at module level so the check happens once, not on every speak() call
try:
    from live2d_controller import update_audio_amplitude as _update_live2d_amplitude
    _LIVE2D_LIP_SYNC = True
except ImportError:
    _update_live2d_amplitude = None
    _LIVE2D_LIP_SYNC = False
from pathlib import Path

# ── Primary TTS: Kokoro-82M ──
try:
    from kokoro import KPipeline
    KOKORO_AVAILABLE = True
except ImportError:
    KOKORO_AVAILABLE = False
    KPipeline = None
    print("⚠️  kokoro not installed — run: pip install kokoro>=0.9.2")

# ── Fallback TTS: F5-TTS (kept until Kokoro confirmed stable) ──
try:
    from f5_tts.api import F5TTS
    F5TTS_AVAILABLE = True
except ImportError:
    F5TTS_AVAILABLE = False
    F5TTS = None

# ─────────────────────────────────────────────
# DEVICE CONFIGURATION
# ─────────────────────────────────────────────

SAMPLE_RATE   = 16000
INPUT_DEVICE  = 3    # HyperX QuadCast S
OUTPUT_DEVICE = 6    # SteelSeries Sonar - Gaming

sd.default.device     = (INPUT_DEVICE, OUTPUT_DEVICE)
sd.default.samplerate = SAMPLE_RATE
sd.default.channels   = (1, 2)

# ─────────────────────────────────────────────
# GPU DEVICE
# RTX 3090 — CUDA native. No DirectML workarounds.
# ─────────────────────────────────────────────

if torch.cuda.is_available():
    TORCH_DEVICE = "cuda"
    print(f"🖥️  Torch device: cuda ({torch.cuda.get_device_name(0)})")
else:
    TORCH_DEVICE = "cpu"
    print("🖥️  Torch device: cpu — no CUDA GPU found, expect slow TTS")

# ─────────────────────────────────────────────
# WAKE WORDS
# ─────────────────────────────────────────────

WAKE_WORDS = [
    "hayeong", "hey young", "hay young", "hi young",
    "hey yong", "hae young", "hay yong", "hey on",
    "heyong", "heong", "a young", "ayoung", "hyong",
    "haeon", "haeyoung", "young", "hey"
]
WAKEWORD_COOLDOWN = 2

# ─────────────────────────────────────────────
# WHISPER MODEL
# Runs on CUDA (3090). Full GPU — no CPU fallback.
# Kokoro and Whisper share the 3090 fine at ~1GB each.
# ─────────────────────────────────────────────

WHISPER_DEVICE = TORCH_DEVICE   # "cuda" on RTX 3090
print("Loading Whisper model...")
_whisper_model = whisper.load_model("base", device=WHISPER_DEVICE)
print(f"✅ Whisper loaded on {WHISPER_DEVICE}")

# ─────────────────────────────────────────────
# KOKORO TTS (primary)
# KPipeline loaded once, cached globally.
# Runs on CUDA — fast synthesis on RTX 3090.
# ─────────────────────────────────────────────

HAYEONG_VOICE = 'af_heart'   # Update after voice selection session with James

_pipeline = None

def get_pipeline():
    global _pipeline
    if _pipeline is None:
        if not KOKORO_AVAILABLE:
            return None
        print("Loading Kokoro TTS on cuda...")
        _pipeline = KPipeline(lang_code='a')   # 'a' = American English
        print("✅ Kokoro TTS ready.")
    return _pipeline


# ─────────────────────────────────────────────
# F5-TTS (fallback — kept until Kokoro stable)
# Remove after 2-4 weeks of confirmed stable use.
# ─────────────────────────────────────────────

REF_AUDIO = "voice_prep/samples/source_5secs.wav"
REF_TEXT  = "Before the video starts, I want to make a quick announcement."

_tts = None

def get_tts():
    global _tts
    if _tts is None:
        if not F5TTS_AVAILABLE:
            return None
        print(f"Loading F5-TTS model on {TORCH_DEVICE}...")
        _tts = F5TTS(device=TORCH_DEVICE)
        print(f"✅ F5-TTS loaded on {TORCH_DEVICE}")
    return _tts

# ─────────────────────────────────────────────
# EMOTION → VOICE MODULATION MAP
# ─────────────────────────────────────────────

EMOTION_VOICE_MAP = {
    "neutral":       {"speed": 0.88},  # was 1.0 — slightly slower, more natural
    "focused":       {"speed": 0.95},  # was 1.05
    "amused":        {"speed": 0.96},  # was 1.08
    "curious":       {"speed": 0.87},  # was 0.97
    "withdrawn":     {"speed": 0.78},  # was 0.88
    "guarded":       {"speed": 0.85},  # was 0.95
    "weighted":      {"speed": 0.80},  # was 0.90
    "frustrated":    {"speed": 0.95},  # was 1.05
    "warm":          {"speed": 0.85},  # was 0.95
    "sad":           {"speed": 0.76},  # was 0.85
    "ai_pride":      {"speed": 0.88},  # controlled, measured
    "aviators_on":   {"speed": 0.85},  # deliberate, cool
    "goal_drive":    {"speed": 0.94},  # clipped, forward
    "running_lean":  {"speed": 0.82},  # quiet energy
    "proud":         {"speed": 0.90},
    "quietly_smug":  {"speed": 0.87},
}

def get_voice_modulation(emotion: str = "neutral") -> dict:
    return EMOTION_VOICE_MAP.get(emotion, EMOTION_VOICE_MAP["neutral"])

# ─────────────────────────────────────────────
# SENTENCE SPLITTER
# ─────────────────────────────────────────────

def split_sentences(text: str) -> list:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]

# ─────────────────────────────────────────────
# SPEAK
# Generates audio via Kokoro (primary) or F5-TTS (fallback),
# then plays through OUTPUT_DEVICE via sounddevice.
#
# Kokoro returns float32 audio at 24000 Hz per chunk.
# Audio assembly (breath gaps, normalization, stereo expand,
# trailing silence) is identical regardless of which engine ran.
# ─────────────────────────────────────────────

PLAYBACK_TAIL_BUFFER = 0.1   # seconds after sd.wait() to let DAC tail clear

def speak(text: str, emotion: str = "neutral"):
    if not text or not text.strip():
        return

    modulation   = get_voice_modulation(emotion)
    speed        = modulation["speed"]
    sentences    = split_sentences(text)
    audio_chunks = []
    sample_rate  = 24000

    # ── Primary: Kokoro TTS ──
    if KOKORO_AVAILABLE:
        pipeline = get_pipeline()
        if pipeline is not None:
            for sentence in sentences:
                try:
                    generator = pipeline(sentence, voice=HAYEONG_VOICE, speed=speed)
                    for _, _, audio in generator:
                        audio_chunks.append(audio)
                except Exception as e:
                    print(f"⚠️ Kokoro error on sentence: {e}")
                    continue

    # ── Fallback: F5-TTS (if Kokoro unavailable or produced nothing) ──
    if not audio_chunks and F5TTS_AVAILABLE:
        tts = get_tts()
        if tts is not None:
            print("   [TTS] Kokoro unavailable — using F5-TTS fallback")
            for sentence in sentences:
                try:
                    wav, sr, _ = tts.infer(
                        ref_file = REF_AUDIO,
                        ref_text = REF_TEXT,
                        gen_text = sentence,
                        nfe_step = 64,
                        speed    = speed,
                    )
                    audio_chunks.append(wav)
                    sample_rate = sr
                except Exception as e:
                    print(f"⚠️ F5-TTS error on sentence: {e}")
                    continue

    if not audio_chunks:
        print("⚠️ No TTS engine produced audio — cannot speak")
        return

    # Insert a short breath-gap between sentences
    BREATH_GAP_SECONDS = 0.18
    breath = np.zeros(int(BREATH_GAP_SECONDS * sample_rate), dtype=np.float32)
    with_breaths = []
    for i, chunk in enumerate(audio_chunks):
        with_breaths.append(chunk)
        if i < len(audio_chunks) - 1:
            with_breaths.append(breath)
    combined = np.concatenate(with_breaths)

    # Always float32
    if combined.dtype != np.float32:
        combined = combined.astype(np.float32)

    # Safe normalization
    peak = np.abs(combined).max()
    if peak > 1.0:
        combined = combined / peak

    # Stereo expand if mono
    if combined.ndim == 1:
        combined = np.stack([combined, combined], axis=1)

    # Trailing silence — prevents last phoneme clipping on playback
    silence_samples = int(0.6 * sample_rate)
    silence = np.zeros((silence_samples, combined.shape[1]), dtype=np.float32)
    combined = np.vstack([combined, silence])

    try:
        if _LIVE2D_LIP_SYNC:
            # Chunked playback — each chunk updates the lip-sync amplitude
            # before playing, so Live2D mouth moves in sync at ~30fps.
            chunk_size = int(sample_rate * 0.033)   # ~33ms per chunk ≈ 30fps
            for i in range(0, len(combined), chunk_size):
                chunk = combined[i:i + chunk_size]
                _update_live2d_amplitude(float(np.abs(chunk).mean()))
                sd.play(chunk, samplerate=sample_rate, device=OUTPUT_DEVICE)
                sd.wait()
            _update_live2d_amplitude(0.0)   # reset mouth to closed after speech
        else:
            sd.play(combined, samplerate=sample_rate, device=OUTPUT_DEVICE)
            sd.wait()
        time.sleep(PLAYBACK_TAIL_BUFFER)
    except Exception as e:
        print(f"⚠️ Playback error: {e}")

# ─────────────────────────────────────────────
# THINKING INDICATOR
# ─────────────────────────────────────────────

def thinking_sound():
    pass  # Placeholder — enable when you have a breath clip

def show_thinking():
    print("💭 Hayeong is thinking...", end="\r")

# ─────────────────────────────────────────────
# RECORDING
# ─────────────────────────────────────────────

def record_seconds(seconds: int = 6) -> str:
    recording = sd.rec(
        int(seconds * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        device=INPUT_DEVICE
    )
    sd.wait()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    wav_write(tmp.name, SAMPLE_RATE, recording)
    return tmp.name

def get_volume(audio: np.ndarray) -> float:
    return float(np.abs(audio).mean())

# ─────────────────────────────────────────────
# TRANSCRIBE (openai-whisper, GPU via ROCm)
# ─────────────────────────────────────────────

def transcribe(audio_file: str) -> str:
    try:
        result = _whisper_model.transcribe(
            audio_file,
            language="en",
            fp16=(WHISPER_DEVICE == "cuda"),
        )
        text = result["text"].strip()
    except Exception as e:
        print(f"⚠️ Transcription error: {e}")
        text = ""
    finally:
        if os.path.exists(audio_file):
            try:
                os.remove(audio_file)
            except Exception:
                pass
    return text

# ─────────────────────────────────────────────
# VOLUME THRESHOLD
# ─────────────────────────────────────────────

VOLUME_THRESHOLD = 0.008

# ─────────────────────────────────────────────
# WAKE WORD LISTENER
# ─────────────────────────────────────────────

def listen_for_wake_word() -> bool:
    print(f"🎧 Waiting for 'Hayeong'... (device {INPUT_DEVICE} | threshold {VOLUME_THRESHOLD})")

    try:
        while True:
            recording = sd.rec(
                int(2 * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                device=INPUT_DEVICE
            )
            sd.wait()
            vol = get_volume(recording)

            if vol < VOLUME_THRESHOLD:
                print(f"   [quiet {vol:.5f}]", end="\r")
                continue

            print(f"   [heard {vol:.5f}] checking...", end="\r")

            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            wav_write(tmp.name, SAMPLE_RATE, recording)
            tmp.close()

            text = transcribe(tmp.name).lower()
            print(f"   heard: {text!r}                    ", end="\r")

            if any(word in text for word in WAKE_WORDS):
                print(f"\n✨ Wake word detected: {text!r}")
                speak("Yeah?", emotion="neutral")
                time.sleep(WAKEWORD_COOLDOWN)
                return True

    except KeyboardInterrupt:
        print("\n🛑 Listener stopped.")
        raise

# ─────────────────────────────────────────────
# PASSIVE LISTENER
# ─────────────────────────────────────────────

def listen_once(seconds: int = 6, volume_gate: bool = True) -> str:
    recording = sd.rec(
        int(seconds * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        device=INPUT_DEVICE
    )
    sd.wait()

    if volume_gate and get_volume(recording) < VOLUME_THRESHOLD:
        return ""

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    wav_write(tmp.name, SAMPLE_RATE, recording)
    tmp.close()

    return transcribe(tmp.name)

# ─────────────────────────────────────────────
# DEVICE DEBUG / TEST (run directly)
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "devices":
        print("\n📋 Audio devices:")
        print(sd.query_devices())
        print(f"\nCurrent input:  device {INPUT_DEVICE}")
        print(f"Current output: device {OUTPUT_DEVICE}")

    elif len(sys.argv) > 1 and sys.argv[1] == "test":
        emotion = sys.argv[2] if len(sys.argv) > 2 else "neutral"
        print(f"🔊 Testing voice with emotion: {emotion}")
        speak(
            "Hey. If this sounds right, the setup is good. Full sentence, no cutoff.",
            emotion=emotion
        )

    elif len(sys.argv) > 1 and sys.argv[1] == "test_long":
        # Tests multi-sentence to confirm no cutoff between chunks
        print("🔊 Testing multi-sentence output...")
        speak(
            "Okay so I just wanted to say, umm,  i love you. "
            "And I I was wondering if you'd be up for some thing later? Maybe?",
            emotion="neutral"
        )

    elif len(sys.argv) > 1 and sys.argv[1] == "emotions":
        print("🎭 Testing all emotion states...")
        for emo in EMOTION_VOICE_MAP:
            print(f"  Testing: {emo}")
            speak(f"This is what {emo} sounds like.", emotion=emo)
            time.sleep(0.5)

    elif len(sys.argv) > 1 and sys.argv[1] == "listen":
        print("🎙️ Listening for wake word...")
        detected = listen_for_wake_word()
        if detected:
            print("✅ Wake word test passed.")

    else:
        print("Usage:")
        print("  python voice.py devices      — list audio devices")
        print("  python voice.py test         — test voice output (single sentence)")
        print("  python voice.py test_long    — test multi-sentence output")
        print("  python voice.py test focused — test a specific emotion")
        print("  python voice.py emotions     — test all emotion states")
        print("  python voice.py listen       — test wake word detection")