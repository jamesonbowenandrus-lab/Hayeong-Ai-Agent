# Toolbox/minecraft/

Hayeong's Minecraft bot control layer.

## Architecture

Two components work together:
- **Python bridge** (`minecraft_bridge.py`) — receives task assignments from the
  presence loop, TCP-checks the server, launches the Node.js bot, returns result to state
- **Node.js bot** (`hayeong_bot.js`) — connects to the Minecraft server via mineflayer,
  executes movement, interaction, and observation in-game

## Server Requirements

### online-mode must be false

The bot connects using an offline account (`Hayeong`). If the server has
`online-mode=true` in `server.properties`, it will reject the connection
immediately with ECONNRESET.

Edit `server.properties`:
```
online-mode=false
```

Restart the server after changing this.

### Server version must match

The bot connects with the version in `Brain/config.py`:
```python
MINECRAFT_VERSION = "1.21.4"
```

If your server runs a different version, update this constant to match.
Version mismatch also causes ECONNRESET.

### Server must be running before asking Hayeong to join

The bridge does a TCP reachability check before launching the bot. If the
server is not listening on the configured host/port, Hayeong reports it as
unreachable rather than launching the bot into a guaranteed error.

## Configuration

All connection settings live in `Brain/config.py`:

```python
MINECRAFT_HOST    = "127.0.0.1"   # Use IPv4 — "localhost" resolves to IPv6 on some systems
MINECRAFT_PORT    = 25565
MINECRAFT_VERSION = "1.21.4"
BOT_JS_PATH       = ...           # auto-resolved
```

To connect to a different server, change `MINECRAFT_HOST`. Hayeong's presence
loop can also pass a custom host dynamically via task params.

## Instance Profiles

Hayeong can connect to different Minecraft servers using instance profiles.
Each profile defines:
- Server address and port
- Vanilla or modded (and which mod pack)
- Mineflayer plugins to load for that instance
- Reference to the knowledge file for that instance

Profiles live in: `minecraft/profiles/`
Active profile is set in: `Brain/config.py`

## Mod Knowledge

When connecting to a modded server, Hayeong loads the mod-specific
knowledge file from `Memory/knowledge/minecraft/[profile_name].json`

This file contains:
- Items she has encountered and what she inferred about them
- Creatures she has encountered and whether they are hostile
- Environmental mechanics she has learned (temperature, status effects, etc.)
- Things James has told her directly about the mod

This knowledge is hers — built through experience and inference.
It is not a pre-loaded database.

## What To Know

Mineflayer connects at protocol level. On modded servers, block and entity
IDs come with string registry names (e.g. rlcraft:dragon_bone_sword).
These names are readable even if not in Hayeong's vanilla reference.
She uses the name to infer category and behavior, then logs what she learns.

Unknown entities are treated as potentially hostile until classified.
Movement vectors are observable — an entity closing distance aggressively
is distinguishable from one wandering passively.
