"""
music_generate.py
Generate a music track from a text prompt using Stable Audio Open.
Runs on AMD 7900 via ROCm or DirectML — never touches the 3090.

Prompt structure (Hayeong's LLM uses this as reference):
  [mood/energy], [tempo feel], [genre/style], [instrumentation], [vocal presence], [specific character]
  Example: "dark and tense, slow driving tempo, industrial electronic,
            heavy distorted synth bass, no vocals, cold mechanical atmosphere"

Standalone CLI:
  python scripts/music_generate.py --prompt "dark ambient electronic, heavy bass" --duration 45

Also importable:
  from scripts.music_generate import generate
  path = generate(prompt="...", duration=45)
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR   = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "outputs" / "music"


def generate(
    prompt: str,
    output_path: str = None,
    duration: float = 45.0,
    steps: int = 100,
) -> str:
    """
    Generate a music track from a text prompt.

    Args:
        prompt      : Text description of desired music.
        output_path : Where to save the .wav. Auto-named if None.
        duration    : Seconds to generate (max ~47 for Stable Audio Open).
        steps       : Diffusion steps. Higher = better quality, slower.

    Returns:
        Absolute path to saved .wav file on success.

    Raises:
        RuntimeError on generation failure.
    """
    import torch
    import torchaudio

    # Import device helper from same directory
    sys.path.insert(0, str(Path(__file__).parent))
    from _music_device import get_music_device, get_torch_device

    device_info = get_music_device()
    if device_info["verdict"] == "NOT USABLE":
        raise RuntimeError(
            "music_probe.py reported NOT USABLE. Cannot generate music. "
            "Check logs/music_probe_results.txt for details."
        )

    device = get_torch_device(device_info)
    print(f"[music_generate] Device: {device_info['confirmed_device']} ({device})")

    # ── Load model ──
    try:
        from stable_audio_tools import get_pretrained_model
        from stable_audio_tools.inference.generation import generate_diffusion_cond
    except ImportError:
        raise RuntimeError(
            "stable-audio-tools not installed. "
            "Run: pip install stable-audio-tools"
        )

    print("[music_generate] Loading stabilityai/stable-audio-open-1.0 ...")
    model, model_config = get_pretrained_model("stabilityai/stable-audio-open-1.0")
    model = model.to(device)
    model.eval()

    sample_rate = model_config["sample_rate"]
    sample_size = model_config["sample_size"]

    # Clamp duration — Stable Audio Open supports up to ~47s
    duration = min(float(duration), 47.0)

    # ── Build output path ──
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(OUTPUT_DIR / f"generated_{timestamp}.wav")

    # ── Generate ──
    print(f"[music_generate] Generating {duration}s — '{prompt[:80]}' ...")
    print(f"[music_generate] Steps: {steps} (this may take a while on first run)")

    conditioning = [{
        "prompt":        prompt,
        "seconds_start": 0,
        "seconds_total": duration,
    }]

    try:
        with torch.no_grad():
            output = generate_diffusion_cond(
                model,
                steps=steps,
                cfg_scale=7,
                conditioning=conditioning,
                sample_size=sample_size,
                sigma_min=0.3,
                sigma_max=500,
                sampler_type="dpmpp-3m-sde",
                device=device,
            )
    except Exception as e:
        raise RuntimeError(f"Generation failed: {e}") from e

    # ── Save output — 44100hz stereo, no resampling ──
    # output shape: (batch, channels, samples) — take first batch item
    audio = output[0]   # (channels, samples)

    # Ensure stereo
    if audio.shape[0] == 1:
        audio = audio.repeat(2, 1)

    # Move to CPU for saving
    audio_cpu = audio.cpu()

    torchaudio.save(output_path, audio_cpu, sample_rate)
    print(f"[music_generate] Saved: {output_path}")

    del model
    return output_path


# ─────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate music from a text prompt using Stable Audio Open."
    )
    parser.add_argument("--prompt",   required=True,  help="Text description of desired music")
    parser.add_argument("--output",   default=None,   help="Output .wav path (auto-named if omitted)")
    parser.add_argument("--duration", type=float, default=45.0, help="Seconds to generate (max 47, default 45)")
    parser.add_argument("--steps",    type=int,   default=100,  help="Diffusion steps (default 100, higher=better)")
    args = parser.parse_args()

    try:
        path = generate(
            prompt=args.prompt,
            output_path=args.output,
            duration=args.duration,
            steps=args.steps,
        )
        print(f"\nSuccess: {path}")
        sys.exit(0)
    except RuntimeError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
