"""
music_analyze.py
Analyze an audio file and return a plain English description of its musical style,
mood, instrumentation, tempo feel, and energy using LP-MusicCaps.
Runs on AMD 7900 — never touches the 3090.

LP-MusicCaps HuggingFace model: seungheondoh/LP-music-caps
Verify at: https://huggingface.co/seungheondoh/LP-music-caps

Standalone CLI:
  python scripts/music_analyze.py --input "path/to/song.mp3"

Also importable:
  from scripts.music_analyze import analyze
  description = analyze("path/to/song.mp3")
"""

import argparse
import sys
from pathlib import Path

# LP-MusicCaps model identifier — verify on HuggingFace if this errors
LP_MUSICCAPS_MODEL = "seungheondoh/LP-music-caps"

BASE_DIR = Path(__file__).parent.parent

# Target sample rate LP-MusicCaps expects
LP_SAMPLE_RATE = 22050


def analyze(audio_path: str) -> str:
    """
    Analyze an audio file and return a plain English style description.

    Args:
        audio_path : Path to .mp3, .wav, or .flac file.

    Returns:
        Plain English description string.

    Raises:
        FileNotFoundError if audio_path does not exist.
        RuntimeError on model load or inference failure.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # ── Device setup ──
    sys.path.insert(0, str(Path(__file__).parent))
    from _music_device import get_music_device

    device_info = get_music_device()
    if device_info["verdict"] == "NOT USABLE":
        raise RuntimeError(
            "music_probe.py reported NOT USABLE. Cannot run LP-MusicCaps. "
            "Check logs/music_probe_results.txt for details."
        )

    print(f"[music_analyze] Device: {device_info['confirmed_device']}")

    # ── Load audio at 22050hz mono ──
    try:
        import librosa
        import numpy as np
    except ImportError:
        raise RuntimeError(
            "librosa not installed. Run: pip install librosa"
        )

    print(f"[music_analyze] Loading audio: {audio_path}")
    try:
        audio, sr = librosa.load(str(audio_path), sr=LP_SAMPLE_RATE, mono=True)
    except Exception as e:
        raise RuntimeError(f"Failed to load audio file: {e}") from e

    print(f"[music_analyze] Audio loaded — {len(audio)/LP_SAMPLE_RATE:.1f}s at {LP_SAMPLE_RATE}hz")

    # ── Load LP-MusicCaps ──
    try:
        from transformers import pipeline as hf_pipeline
    except ImportError:
        raise RuntimeError(
            "transformers not installed. Run: pip install transformers"
        )

    # HuggingFace pipeline device: 0 for first GPU (ROCm), -1 for CPU
    hf_device = 0 if device_info["confirmed_device"] in ("rocm",) else -1

    print(f"[music_analyze] Loading {LP_MUSICCAPS_MODEL} ...")
    try:
        captioner = hf_pipeline(
            "text-generation",
            model=LP_MUSICCAPS_MODEL,
            device=hf_device,
        )
    except Exception as e:
        raise RuntimeError(
            f"Failed to load LP-MusicCaps ({LP_MUSICCAPS_MODEL}): {e}\n"
            f"Verify model name at: https://huggingface.co/seungheondoh/LP-music-caps"
        ) from e

    # ── Run inference ──
    print("[music_analyze] Running captioning inference ...")
    try:
        import numpy as np
        result = captioner(
            {"array": audio, "sampling_rate": LP_SAMPLE_RATE},
            max_new_tokens=200,
        )
    except Exception as e:
        raise RuntimeError(f"LP-MusicCaps inference failed: {e}") from e

    del captioner

    # Extract generated text from pipeline output
    if isinstance(result, list) and result:
        description = result[0].get("generated_text", "")
    elif isinstance(result, dict):
        description = result.get("generated_text", "")
    else:
        description = str(result)

    description = description.strip()

    if not description:
        raise RuntimeError("LP-MusicCaps returned an empty description.")

    return description


# ─────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Analyze an audio file and return a style description using LP-MusicCaps."
    )
    parser.add_argument("--input", required=True, help="Path to .mp3, .wav, or .flac file")
    args = parser.parse_args()

    try:
        description = analyze(args.input)
        print("\n── Style Description ──")
        print(description)
        print("──────────────────────")
        sys.exit(0)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
