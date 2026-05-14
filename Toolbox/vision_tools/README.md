# Toolbox/vision_tools

Visual awareness layer for Hayeong. Two components: conversational vision
(asking her to look at your screen or analyze an image) and passive screen
observation with teaching mode.

## Hardware

Uses Ollama vision models on port 11434. GPU-accelerated — requires the
RTX 3090 via CUDA. Vision is degraded or unavailable if Ollama is not
running or the 3090 is unavailable.

## Files

- `vision_bridge.py` — conversational vision; `VisionBridge` class; used when
  Hayeong is asked to look at something
- `screen_observer.py` — passive screen observer with teaching mode; runs
  in background to track what James is working on

## Vision Models

| Model | Speed | Use |
|-------|-------|-----|
| moondream:latest | ~2–5s | Screen glances, quick status reads |
| llava:13b | ~15s | Detailed analysis, image files, code review |

Both run via Ollama on port 11434.

## VisionBridge

Conversational vision — used when Hayeong is explicitly asked to look.

```python
vision = VisionBridge()

# Fast screen glance (moondream)
context = vision.look_at_screen("what is James working on?")

# Deep screen analysis (llava:13b)
context = vision.look_at_screen_deep("explain what's in this code")

# Analyze an image file (llava:13b)
context = vision.look_at_image("logs/outputs/comfyui/image.png", "describe this")
```

All methods return a context string formatted for injection into the
system prompt. Vision output is context — Hayeong reasons about it,
not raw image data passed to the model.

**Triggers (intent detection):**
"look at my screen", "what's on my screen", "what is this", "look at this image"

## ScreenObserver

Passive background observer with privacy controls and teaching mode.

```python
observer = ScreenObserver()
observer.start()                           # Passive observation on (30s interval)

observer.start_teaching("build in blender")
observer.narrate("Opening Blender, new project")
observer.narrate("Adding a cube with Shift+A")
knowledge = observer.stop_teaching()       # Saves structured knowledge file

observer.private_mode_on()                 # Pause all observation
observer.block_app("my bank")              # Permanent blacklist entry
```

**Capture intervals:**
- Passive: every 30 seconds
- Teaching mode: every 10 seconds

**Privacy — default blacklist includes:** financial apps, password managers,
private browsing mode, medical apps, dating apps. Extend via `block_app()` or
`privacy_registry.json`.

**Teaching sessions** are saved to `toolbox/vision_tools/capabilities/learned/`
as structured JSON knowledge files. Each session tracks steps, narration,
app context, and questions asked.

## Dependencies

```
pip install Pillow       # screenshot capture (required)
pip install pygetwindow  # active window title (optional, improves context)
```

Screen capture falls back gracefully if Pillow is missing. Window title
detection requires pygetwindow; ScreenObserver works without it.
