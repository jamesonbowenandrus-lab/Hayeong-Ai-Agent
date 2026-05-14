# Toolbox/voice

Text-to-speech (TTS) and speech-to-text (STT) for Hayeong's voice layer.
CUDA-dependent — requires the RTX 3090.

## Files

- `voice.py` — core voice logic
- `voice_io.py` — audio I/O handling
- `voice_ptt.py` — push-to-talk STT input
- `voice_server.py` — voice server process
- `voice_channels.md` — channel architecture notes

## TTS Stack

- **Primary**: Kokoro TTS — local, fast, high quality
- **Fallback**: F5-TTS — used when Kokoro is unavailable

## STT

- Whisper (local) — transcribes voice input

## Hardware

CUDA-only. Requires the RTX 3090. Voice is disabled in text mode
(`--brain` flag or when the 3090 is unavailable).

## Status

Active when CUDA is available. Text mode (`--brain`) disables voice automatically.
