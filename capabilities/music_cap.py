# capabilities/music_cap.py
# Music generation capability — analyze reference tracks and generate new music.
#
# Runs on AMD 7900 via scripts/music_analyze.py and scripts/music_generate.py.
# The 3090 (Hayeong's brain/LLM) is not touched by music generation.
#
# Actions:
#   music_analyze  — analyze an audio file, return plain English style description
#   music_generate — generate a .wav from a text prompt
#
# Prerequisites:
#   Run scripts/music_probe.py first. Confirm READY verdict before using.
#   Install: stable-audio-tools, transformers, librosa, soundfile

import sys
from pathlib import Path
from capability_loader import result

ACTIONS = ["music_analyze", "music_generate"]

BASE_DIR    = Path(__file__).parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
OUTPUT_DIR  = BASE_DIR / "outputs" / "music"

# Ensure scripts/ is importable
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _check_probe() -> str | None:
    """Return error string if probe has not been run or reported NOT USABLE."""
    device_json = BASE_DIR / "logs" / "music_device.json"
    if not device_json.exists():
        return (
            "music_probe.py has not been run yet. "
            "Run `python scripts/music_probe.py` first to confirm the 7900 is usable."
        )
    import json
    try:
        config = json.loads(device_json.read_text(encoding="utf-8"))
        verdict = config.get("verdict", "UNKNOWN")
        if verdict == "NOT USABLE":
            return (
                "music_probe.py reported NOT USABLE. "
                "Check hayeong_outputs/logs/music_probe_results.txt for details."
            )
        return None
    except Exception:
        return None


def handle(action: str, user_input: str, context: dict) -> dict:
    probe_error = _check_probe()
    if probe_error:
        return result(
            success=False,
            response=f"I can't run music generation right now — {probe_error}",
            data={"reason": probe_error},
        )

    if action == "music_analyze":
        return _handle_analyze(user_input, context)
    elif action == "music_generate":
        return _handle_generate(user_input, context)

    return result(success=False, response=f"Unknown action: {action}")


def _handle_analyze(user_input: str, context: dict) -> dict:
    audio_path = context.get("audio_path") or context.get("file_path")
    if not audio_path:
        return result(
            success=False,
            response="I need an audio file to analyze. Please provide a path to a .mp3, .wav, or .flac file.",
            data={"reason": "no audio_path in context"},
        )

    try:
        from music_analyze import analyze
        description = analyze(str(audio_path))
        return result(
            success=True,
            response=(
                f"Here's what I hear in that track:\n\n{description}\n\n"
                f"Want me to generate something new in this style?"
            ),
            data={"description": description, "source_file": str(audio_path)},
        )
    except FileNotFoundError as e:
        return result(success=False, response=f"Audio file not found: {audio_path}", data={"error": str(e)})
    except RuntimeError as e:
        return result(success=False, response=f"Analysis failed: {e}", data={"error": str(e)})
    except ImportError as e:
        return result(
            success=False,
            response=f"Music analysis dependencies missing: {e}. Run: pip install transformers librosa",
            data={"error": str(e)},
        )


def _handle_generate(user_input: str, context: dict) -> dict:
    # Prompt comes from context (LLM-refined) or falls back to raw user input
    prompt = context.get("music_prompt") or context.get("prompt") or user_input
    duration = float(context.get("duration", 45.0))
    steps    = int(context.get("steps", 100))

    if not prompt or len(prompt.strip()) < 5:
        return result(
            success=False,
            response="I need a description of the music to generate. What style, mood, or feeling are you going for?",
            data={"reason": "prompt too short or missing"},
        )

    try:
        from music_generate import generate
        saved_path = generate(prompt=prompt, duration=duration, steps=steps)

        rel_path = Path(saved_path).relative_to(BASE_DIR)
        return result(
            success=True,
            response=(
                f"Done! I generated a {duration:.0f}-second track based on your description.\n"
                f"Saved to: {rel_path}\n\n"
                f"Prompt used: \"{prompt[:120]}\""
            ),
            data={"output_path": saved_path, "prompt": prompt, "duration": duration},
        )
    except RuntimeError as e:
        return result(success=False, response=f"Music generation failed: {e}", data={"error": str(e)})
    except ImportError as e:
        return result(
            success=False,
            response=f"Music generation dependencies missing: {e}. Run: pip install stable-audio-tools",
            data={"error": str(e)},
        )
