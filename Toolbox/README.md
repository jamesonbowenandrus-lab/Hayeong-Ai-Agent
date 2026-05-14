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
  See `minecraft\README.md` for bot architecture and command reference.

- `blender\` — 3D generation and rendering via Blender scripting.
  See `blender\README.md`.

- `comfyui\` — Image generation via ComfyUI HTTP API.
  Targets the AMD RX 7900 XTX. ComfyUI must be running separately.
  See `comfyui\README.md`.

- `voice\` — TTS (Kokoro primary, F5-TTS fallback) and STT (Whisper).
  CUDA-dependent (RTX 3090).
  See `voice\README.md`.

- `email\` — Email reading and sending.
  See `email\README.md`.

- `web\` — Web search and text retrieval.
  See `web\README.md`.

- `music\` — Music generation (Stable Audio Open) and analysis (LP-MusicCaps).
  Targets the AMD RX 7900 XTX. Currently pending full activation.
  See `music\README.md`.

- `vision_tools\` — Vision model, screen observation, visual awareness.
  CUDA-dependent (RTX 3090 required for full function).
  See `vision_tools\README.md`.

- `script\` — General Python script execution. Runs arbitrary scripts and
  returns stdout as result string. Used for one-off automation.

- `dev\` — Hayeong's self-modification tool. Allows the reasoning layer to
  edit tool scripts, update domain prompts, or generate handoff notes for
  structural changes requiring Claude Code. Enforces scope constraints —
  cannot touch main.py or constitutional identity files without James review.
  See `dev\README.md`.

## Tool Registry

Tools are registered in `Toolbox/registry.json`. Each entry maps a tool name
to its module path and function:

    "toolname": { "module": "toolbox.toolname.script", "function": "run" }

The reasoning layer dispatches tasks by tool name. New tools must be registered
here to be callable.

## Plugins

Some tools also include a `plugin.py` that runs on a heartbeat and injects status
into Hayeong's presence context. Plugins are auto-discovered by `plugin_registry.py`
— no manual registration needed, just add `plugin.py` to the folder.

## Adding A New Tool

1. Create a new subfolder with the tool name
2. Write the main script with a `run(description, params) -> str` function
3. Catch all exceptions inside the tool — never let them propagate to main
4. Add a `README.md` to the subfolder
5. Register the tool in `Toolbox/registry.json`
6. Optionally add a `plugin.py` for presence context injection
7. Add tool knowledge to `Memory/knowledge/toolknowledge/`

Hayeong can add and update tools in this folder independently.
