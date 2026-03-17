"""
HAYEONG VOICE TEST — EXPRESSIVE MODE
Fixes the flat/robotic delivery by tuning XTTS inference parameters.

The default XTTS settings produce Siri-like flat speech.
These settings push it toward natural, expressive delivery.

Usage:
    python test_xtts.py              — single test line
    python test_xtts.py --all        — all test lines
    python test_xtts.py --tune       — generates same line at different settings
                                       so you can compare and find what sounds best

Put your anchor_*.wav files in voice_prep/anchor/ or update SAMPLES_DIR below.
"""

import torch
import warnings
warnings.filterwarnings("ignore")
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

SAMPLES_DIR = Path("voice_final2/samples")   # folder with your anchor_*.wav files
LANGUAGE    = "en"

# ── EXPRESSIVENESS SETTINGS ──
# These are the knobs that control how human vs robotic she sounds.
# Defaults are conservative — these are tuned for Hayeong's character.
#
# temperature:       Higher = more expressive/varied, lower = flatter/safer
#                    Range: 0.1 – 1.0  |  Default: 0.65  |  Hayeong: 0.75
#
# length_penalty:    Controls pacing. Lower = slightly faster, more natural
#                    Range: 0.5 – 2.0  |  Default: 1.0   |  Hayeong: 0.9
#
# repetition_penalty: Prevents the model looping or droning. Higher = more varied
#                    Range: 1.0 – 10.0 |  Default: 2.0   |  Hayeong: 2.5
#
# top_k:             Sampling diversity. Lower = safer, higher = more expressive
#                    Range: 1 – 100    |  Default: 50    |  Hayeong: 60
#
# top_p:             Nucleus sampling. Higher = more natural variation
#                    Range: 0.0 – 1.0  |  Default: 0.85  |  Hayeong: 0.88

EXPRESSIVENESS = {
    "temperature":        0.75,
    "length_penalty":     0.9,
    "repetition_penalty": 2.5,
    "top_k":              60,
    "top_p":              0.88,
}

# Test sentences — written to draw out natural delivery
# Short punchy lines reveal voice character; longer lines reveal cadence
TEST_LINES = [
    "Yeah, I'm here. What do you need?",
    "I mean, I didn't say it was a bad idea. I just said it was your idea.",
    "Okay that's actually pretty good. Don't make it weird.",
    "I've got it. Just give me a second.",
    "Wait, seriously? That actually worked?",
    "I wasn't worried. I just wanted to make sure you were okay.",
]
TEST_INDEX = 0


# ─────────────────────────────────────────────
# TUNING PRESETS
# Run --tune to hear the same line at different expressiveness levels
# so you can find the sweet spot for Hayeong's voice
# ─────────────────────────────────────────────

TUNE_PRESETS = [
    {"name": "flat",       "temperature": 0.50, "length_penalty": 1.0, "repetition_penalty": 2.0, "top_k": 50, "top_p": 0.85},
    {"name": "default",    "temperature": 0.65, "length_penalty": 1.0, "repetition_penalty": 2.0, "top_k": 50, "top_p": 0.85},
    {"name": "hayeong",    "temperature": 0.75, "length_penalty": 0.9, "repetition_penalty": 2.5, "top_k": 60, "top_p": 0.88},
    {"name": "expressive", "temperature": 0.85, "length_penalty": 0.85,"repetition_penalty": 3.0, "top_k": 70, "top_p": 0.92},
    {"name": "max",        "temperature": 0.95, "length_penalty": 0.8, "repetition_penalty": 3.5, "top_k": 80, "top_p": 0.95},
]


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def find_samples(d: Path) -> list:
    if not d.exists():
        print(f"❌ Samples folder not found: {d.resolve()}")
        print("   Update SAMPLES_DIR at the top of this script.")
        return []
    samples = sorted(d.glob("*.wav"))
    if not samples:
        print(f"❌ No WAV files in: {d.resolve()}")
        return []
    return [str(s) for s in samples]


def load_model():
    from TTS.api import TTS
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\n🎙️  Loading XTTS v2 ({device})...")
    if device == "cpu":
        print("    CPU mode — ~15-25s per sentence on your system.\n")
    return TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device), device


def generate(model, text: str, samples: list, out: str, settings: dict):
    """Generates one audio file with the given expressiveness settings."""
    print(f"📝 \"{text}\"")
    print(f"   temp={settings['temperature']} | rep_penalty={settings['repetition_penalty']} | top_k={settings['top_k']}")
    print("   Generating... ", end="", flush=True)

    model.tts_to_file(
        text=text,
        speaker_wav=samples,
        language=LANGUAGE,
        file_path=out,
        temperature=settings["temperature"],
        length_penalty=settings["length_penalty"],
        repetition_penalty=settings["repetition_penalty"],
        top_k=settings["top_k"],
        top_p=settings["top_p"],
    )
    print(f"✅  saved: {out}")


# ─────────────────────────────────────────────
# MODES
# ─────────────────────────────────────────────

def run_single(model, samples):
    """Generates one sentence with Hayeong settings."""
    text = TEST_LINES[TEST_INDEX]
    generate(model, text, samples, "hayeong_test_output.wav", EXPRESSIVENESS)
    print("\nOpen hayeong_test_output.wav and listen.")
    print("If it still sounds flat, run: python test_xtts.py --tune")


def run_all(model, samples):
    """Generates all test lines."""
    print(f"\n🎭 Generating {len(TEST_LINES)} lines...\n")
    for i, line in enumerate(TEST_LINES):
        out = f"hayeong_test_{i:02d}.wav"
        generate(model, line, samples, out, EXPRESSIVENESS)
    print(f"\n✅ Done. Listen to hayeong_test_00 through hayeong_test_{len(TEST_LINES)-1:02d}.wav")


def run_tune(model, samples):
    """
    Generates the same sentence at 5 different expressiveness levels.
    Listen to all five and pick the one that sounds most like her.
    Then update EXPRESSIVENESS at the top of this file to match.
    """
    text = TEST_LINES[TEST_INDEX]
    print(f"\n🎛️  Tuning mode — generating \"{text}\" at 5 expressiveness levels\n")

    for preset in TUNE_PRESETS:
        out = f"tune_{preset['name']}.wav"
        generate(model, text, samples, out, preset)

    print("\n✅ Done. Listen to these files in order:")
    for p in TUNE_PRESETS:
        print(f"   tune_{p['name']}.wav  (temperature {p['temperature']})")
    print("\nFind the one that sounds most natural and like her.")
    print("Then copy those settings into EXPRESSIVENESS at the top of this script.")
    print("That becomes her permanent voice setting.")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    samples = find_samples(SAMPLES_DIR)
    if not samples:
        exit(1)

    print(f"✅ {len(samples)} reference samples loaded from {SAMPLES_DIR}")

    model, device = load_model()

    mode = sys.argv[1] if len(sys.argv) > 1 else ""

    if mode == "--all":
        run_all(model, samples)
    elif mode == "--tune":
        run_tune(model, samples)
    else:
        run_single(model, samples)
