# Voice Channels — Toolbox

These are the tools Hayeong uses to express her voice.
The brain decides which channel to use. These tools implement the channel.

---

## Available Channels

### Kokoro TTS — Spoken Voice
- **Tool file:** `toolbox/voice/voice_server.py`
- **Status:** Implemented — requires CUDA (3090). Inactive until 3090 is mounted.
- **When used:** James is present and Hayeong has chosen spoken output
- **Fallback:** Text to terminal if unavailable

### Text Output — Terminal Voice
- **Tool file:** Built into communication loop in main.py
- **Status:** Active (current default — text_mode=True)
- **When used:** Voice is inactive, or text mode explicitly selected
- **Fallback:** None needed — this is the baseline channel

### Discord — Remote Voice
- **Tool file:** `toolbox/voice/discord_tool.py`
- **Status:** Implemented (discord_hayeong.py exists)
- **When used:** James is not at the machine, something needs his attention
- **Fallback:** Email if Discord unavailable

### Email — Written Voice
- **Tool file:** `tools/email_bridge.py`
- **Status:** Implemented
- **When used:** Formal or documented communication, James is away
- **Fallback:** Discord or text log

---

## Channel Priority (when Hayeong's brain selects a channel)

```
1. Kokoro TTS        — if active and James is present
2. Text to terminal  — if text_mode or Kokoro unavailable
3. Discord           — if James is away and something is urgent
4. Email             — if formal communication warranted
```

---

## Adding New Channels

Future channels (phone calls, voice memos, stream chat) follow the same
pattern:
1. Add a tool file to `toolbox/voice/`
2. Register it in this document with status and fallback
3. The brain layer's channel decision logic can then reference it

The brain does not need to change when new channels are added.
