"""
toolbox/music/music_tool.py

Hayeong's music control layer.
Registry entry point — called by main.py task loop via toolbox/registry.json.

Routes to the correct music script based on mode:
    generate  — create music from a text prompt (Stable Audio Open)
    analyze   — analyze a reference audio file (LP-MusicCaps)
    pipeline  — analyze a reference track then generate something similar

Called via registry:
    module:   toolbox.music.music_tool
    function: run

Params the reasoning LLM should provide:
    mode            (str)   — "generate", "analyze", or "pipeline"

    For mode="generate":
        prompt          (str)   — music description prompt
        output_filename (str)   — desired filename, e.g. "ambient_track.wav" (optional)
        duration        (float) — seconds to generate, max 47, default 45
        steps           (int)   — diffusion steps, default 100

    For mode="analyze":
        reference_path  (str)   — path to audio file (.mp3, .wav, .flac)

    For mode="pipeline":
        reference_path  (str)   — path to reference audio file
        output_filename (str)   — desired output filename (optional)
        duration        (float) — generation length in seconds, default 45
        steps           (int)   — diffusion steps, default 100

Returns:
    str — success message with output path or analysis text
    raises on failure (caught by _execute_tool in main.py)
"""

import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR   = Path(__file__).parent.parent.parent
OUTPUT_DIR = ROOT_DIR / "logs" / "outputs" / "music"
MUSIC_DIR  = Path(__file__).parent

if str(MUSIC_DIR) not in sys.path:
    sys.path.insert(0, str(MUSIC_DIR))


def run(description: str, params: dict) -> str:
    """Entry point called by main.py task loop via registry. Raises on error."""
    mode = params.get("mode", "generate").strip().lower()

    if mode == "generate":
        return _generate(params)
    elif mode == "analyze":
        return _analyze(params)
    elif mode == "pipeline":
        return _pipeline(params)
    else:
        raise ValueError(f"Unknown music mode: '{mode}'. Use 'generate', 'analyze', or 'pipeline'.")


def _generate(params: dict) -> str:
    prompt = params.get("prompt", "").strip()
    if not prompt:
        raise ValueError("No prompt provided for music generation. Set prompt in task_params.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_filename = params.get("output_filename")
    if output_filename:
        output_path = str(OUTPUT_DIR / Path(output_filename).name)
    else:
        output_path = str(OUTPUT_DIR / f"generated_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav")

    from music_generate import generate
    saved_path = generate(
        prompt=prompt,
        output_path=output_path,
        duration=float(params.get("duration", 45.0)),
        steps=int(params.get("steps", 100)),
    )
    return f"Music generated successfully. Output: {saved_path}"


def _analyze(params: dict) -> str:
    reference_path = params.get("reference_path", "").strip()
    if not reference_path:
        raise ValueError("No reference_path provided for music analysis. Set reference_path in task_params.")

    ref = Path(reference_path)
    if not ref.is_absolute():
        ref = ROOT_DIR / reference_path
    if not ref.exists():
        raise FileNotFoundError(f"Reference audio file not found: {ref}")

    from music_analyze import analyze
    description = analyze(str(ref))
    return f"Music analysis complete:\n{description}"


def _pipeline(params: dict) -> str:
    reference_path = params.get("reference_path", "").strip()
    if not reference_path:
        raise ValueError("No reference_path provided for music pipeline. Set reference_path in task_params.")

    ref = Path(reference_path)
    if not ref.is_absolute():
        ref = ROOT_DIR / reference_path
    if not ref.exists():
        raise FileNotFoundError(f"Reference audio file not found: {ref}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_filename = params.get("output_filename")
    if output_filename:
        output_path = str(OUTPUT_DIR / Path(output_filename).name)
    else:
        output_path = str(OUTPUT_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav")

    from music_pipeline import run_pipeline
    result = run_pipeline(
        reference_path=str(ref),
        output_path=output_path,
        duration=float(params.get("duration", 45.0)),
        steps=int(params.get("steps", 100)),
    )
    return (
        f"Music pipeline complete.\n"
        f"Style description: {result['description']}\n"
        f"Output: {result['output_path']}"
    )
