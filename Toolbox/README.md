# Toolbox\

Every tool Hayeong can use to act in the world.

## What Lives Here

Each subfolder is one tool domain. Each tool:
- Takes a task as input
- Executes it
- Returns a result string (success or error)
- Never crashes main — exceptions are caught inside the tool

## Tools

- `minecraft\` — Minecraft bot control. Python bridge + Node.js bot.
  See minecraft\README.md for bot architecture and instance profiles.

- `blender\` — 3D generation and rendering via Blender scripting.

- `comfyui\` — Image generation pipeline via ComfyUI.

- `music\` — Music generation (Stable Audio Open) and analysis (LP-MusicCaps).
  Currently pending 3090 installation before deployment.

- `vision_tools\` — Vision model, screen observation, visual awareness.
  Currently CUDA-dependent (3090 required for full function).

- `voice\` — TTS (Kokoro) and STT (Whisper). Currently text_mode=True
  in main.py while awaiting 3090. These will reactivate automatically.

- `email\` — Email reading and sending.

- `web\` — Web search and text retrieval.

## Adding A New Tool

1. Create a new subfolder with the tool name
2. Write the tool script — it must return a result string
3. Add a README.md to the subfolder explaining what it does
4. Register the tool in Brain\config.py so reasoning knows it exists
5. Add tool knowledge to Memory\knowledge\toolknowledge\

Hayeong can add and update tools in this folder independently.
