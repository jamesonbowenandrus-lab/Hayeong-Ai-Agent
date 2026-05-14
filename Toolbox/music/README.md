# Toolbox/music

Music generation and analysis. Hayeong can create original audio from text prompts
and analyze reference tracks to understand their style.

## Hardware

Targets the AMD RX 7900 XTX via ROCm or DirectML. Never touches the RTX 3090.
Run `music_probe.py` once to confirm the 7900 XTX is usable before deploying.

## Files

- `music_tool.py` — registry entry point, `run()` function
- `music_generate.py` — generates audio from a text prompt (Stable Audio Open)
- `music_analyze.py` — analyzes a reference audio file (LP-MusicCaps)
- `music_pipeline.py` — chains analyze → generate in one call
- `music_probe.py` — hardware probe, run once to confirm GPU usability
- `_music_device.py` — device selection helper (imported by other scripts)
- `prompt.py` — domain prompt for the reasoning LLM
- `music_prompt.txt` — additional prompt context

## Modes

**generate** — Create music from a text prompt.
**analyze** — Analyze a reference audio file and return a style description.
**pipeline** — Analyze a reference track then generate something in the same style.

## Calling This Tool

    action: music
    params: mode=generate, prompt=dark ambient electronic, slow tempo, deep drones

    action: music
    params: mode=analyze, reference_path=logs/outputs/music/reference.mp3

    action: music
    params: mode=pipeline, reference_path=logs/outputs/music/reference.mp3

## Output

Generated audio is saved to `Logs/outputs/music/` as `.wav` files.

## Status

Built and registered. Pending full deployment confirmation (run `music_probe.py`
first to verify 7900 XTX usability on this system).

## Prompt Structure for Generation

    [mood/energy], [tempo feel], [genre/style], [instrumentation], [vocal presence], [character]

    Example: "dark and tense, slow driving tempo, industrial electronic,
              heavy distorted synth bass, no vocals, cold mechanical atmosphere"
