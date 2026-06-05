# Toolbox

The execution layer. Contains all tools Hayeong can use to act on the world.
The Brain selects tools via registry.json. Tools execute and return results.

## Architecture Rules

- Tools are registered in registry.json — Brain never hardcodes tool names
- Tool state lives in Toolbox/[tool]/state/ — never in Brain/state/
- Tools that inject context each cycle provide a plugin.py with get_context_injection()
- Tools that need proactive behavior provide a plugin.py with tick()
- A tool cannot crash main. All errors are caught and returned as results.

## Active Tools

| Tool | Purpose |
|---|---|
| blender/ | 3D modeling and rendering via headless Blender |
| comfyui/ | Image generation pipeline |
| minecraft/ | Bot control via mineflayer Node.js bridge |
| gaming/ | BO3 Zombies memory reading, virtual gamepad |
| voice/ | Kokoro TTS, F5-TTS, Whisper STT |
| web/ | Web search and fetch |
| database/ | PostgreSQL 18 interface |
| ambient/ | Ambient awareness plugin |
| calendar_manager/ | Temporal context and scheduling |
| diagnostics/ | System health and self-assessment |

## Adding a Tool

1. Create Toolbox/[toolname]/ folder
2. Add main tool Python file
3. Add state/ subfolder for runtime state
4. Add plugin.py if the tool needs context injection or proactive behavior
5. Register in registry.json
6. Do not modify Brain/ or main.py except for the minimum registry entry
