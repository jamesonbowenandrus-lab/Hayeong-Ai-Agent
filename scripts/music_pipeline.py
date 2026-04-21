"""
music_pipeline.py
Optional orchestrator — chains analyze → generate in a single call.

Fast path for when James drops a reference track and wants something similar.
Intentionally bypasses Hayeong's LLM reasoning. When Hayeong is refining
prompts or responding to James's feedback, she calls music_analyze and
music_generate separately through her own reasoning loop instead.

Standalone CLI:
  python scripts/music_pipeline.py --reference "path/to/song.mp3"
  python scripts/music_pipeline.py --reference "song.mp3" --duration 30 --output "out.wav"
"""

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

# Ensure scripts dir is importable
sys.path.insert(0, str(Path(__file__).parent))


def run_pipeline(
    reference_path: str,
    output_path: str = None,
    duration: float = 45.0,
    steps: int = 100,
) -> dict:
    """
    Analyze reference_path then generate a new track in the same style.

    Returns:
        dict with keys:
          description  — plain English style description from analysis
          output_path  — path to saved .wav
    """
    from music_analyze import analyze
    from music_generate import generate

    # Step 1 — Analyze
    print(f"\n[pipeline] Step 1/2 — Analyzing reference track: {reference_path}")
    description = analyze(reference_path)

    print("\n── What Hayeong hears in the reference track ──")
    print(description)
    print("─────────────────────────────────────────────\n")

    # Step 2 — Generate
    print(f"[pipeline] Step 2/2 — Generating new track ({duration}s)...")
    saved_path = generate(
        prompt=description,
        output_path=output_path,
        duration=duration,
        steps=steps,
    )

    return {
        "description": description,
        "output_path":  saved_path,
    }


# ─────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Analyze a reference track and generate new music in the same style."
    )
    parser.add_argument("--reference", required=True,     help="Path to reference audio file (.mp3, .wav, .flac)")
    parser.add_argument("--output",    default=None,      help="Output .wav path (auto-named if omitted)")
    parser.add_argument("--duration",  type=float, default=45.0, help="Generation length in seconds (max 47)")
    parser.add_argument("--steps",     type=int,   default=100,  help="Diffusion steps (default 100)")
    args = parser.parse_args()

    try:
        result = run_pipeline(
            reference_path=args.reference,
            output_path=args.output,
            duration=args.duration,
            steps=args.steps,
        )
        print(f"\nSuccess: {result['output_path']}")
        sys.exit(0)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
