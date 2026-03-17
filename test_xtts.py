"""
HAYEONG VOICE TEST
Tests XTTS v2 cloning using your prepared voice samples.

Usage:
    python test_xtts.py
    python test_xtts.py --all   (generates all test lines)

Output:
    hayeong_test_output.wav
"""

import torch
from TTS.api import TTS
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

SAMPLES_DIR = Path("voice_prep/samples")
OUTPUT_FILE = "hayeong_test_output.wav"
LANGUAGE    = "en"

TEST_LINES = [
    "Yeah, I'm here. What do you need? I was just wondering what you were feeling?"
]
TEST_INDEX = 0

def find_samples(d):
    if not d.exists():
        print(f"❌ Not found: {d.resolve()}\n   Update SAMPLES_DIR in this script.")
        return []
    s = sorted(d.glob("*.wav"))
    if not s:
        print(f"❌ No WAV files in: {d.resolve()}")
        return []
    return [str(x) for x in s]

def load_tts():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\n🎙️  Loading XTTS v2 on {device}...")
    if device == "cpu":
        print("    CPU mode — ~10-20s per sentence. Normal for AMD on Windows.\n")
    return TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

def generate(tts, text, samples, out):
    print(f"📝 \"{text}\"")
    print(f"🔊 {len(samples)} reference samples... please wait\n")
    tts.tts_to_file(text=text, speaker_wav=samples, language=LANGUAGE, file_path=out, temperature=0.75, length_penalty=1.0, repetition_penalty=5.0, top_k=50, top_p=0.85)
    print(f"✅ Saved: {out}\n   Open it and listen.")

if __name__ == "__main__":
    import sys
    samples = find_samples(SAMPLES_DIR)
    if not samples:
        exit(1)
    print(f"✅ {len(samples)} samples found")
    tts = load_tts()
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        for i, line in enumerate(TEST_LINES):
            out = f"hayeong_test_{i:02d}.wav"
            print(f"\n[{i+1}/{len(TEST_LINES)}]")
            generate(tts, line, samples, out)
    else:
        generate(tts, TEST_LINES[TEST_INDEX], samples, OUTPUT_FILE)