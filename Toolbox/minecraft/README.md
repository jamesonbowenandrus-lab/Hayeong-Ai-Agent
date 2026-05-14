# Toolbox/minecraft/

Hayeong's Minecraft bot control layer.

## Architecture

Two components work together:
- **Python bridge** (`minecraft_bridge.py`) — receives task assignments from the
  presence loop, TCP-checks the server, launches the Node.js bot, returns result to state
- **Node.js bot** (`hayeong_bot.js`) — connects to the Minecraft server via mineflayer,
  executes movement, interaction, and observation in-game

## Files

- `minecraft_bridge.py` — main tool, `run()` function, registered in `registry.json`;
  also exposes `send_minecraft_command()` for plugin use
- `hayeong_bot.js` — Node.js bot; mineflayer-based; writes live state to
  `minecraft_state.json`
- `plugin.py` — presence plugin; injects bot state into context; runs proactive
  behavior (auto-eat, flee, follow); discovered by `toolbox/plugin_registry.py`
- `bot_update_tool.py` — lets Hayeong read, modify, and restart her own bot code;
  called via `minecraft_bridge.run()` with `action_type=read/write/backup/restart`
- `minecraft_context.md` — Hayeong's in-Minecraft identity and behavioral guide;
  injected into the presence prompt when the bot is connected
- `minecraft_prompt.txt` — additional domain prompt context for the reasoning LLM

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

The bot connects with the version in `brain/config.py`:
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

All connection settings live in `brain/config.py`:

```python
MINECRAFT_HOST    = "127.0.0.1"   # Use IPv4 — "localhost" resolves to IPv6 on some systems
MINECRAFT_PORT    = 25565
MINECRAFT_VERSION = "1.21.4"
BOT_JS_PATH       = ...           # auto-resolved
```

To connect to a different server, change `MINECRAFT_HOST`. Hayeong's presence
loop can also pass a custom host dynamically via task params.

## Bot Commands

Commands are written to `minecraft_command.json` and picked up by the bot.
The bridge dispatches commands directly; the plugin also fires them proactively.

| Command | Params | What it does |
|---------|--------|--------------|
| `follow` | `{ "username": "hiplizard36" }` | Walk with James |
| `stop` | `{}` | Cancel current movement |
| `goto` | `{ "x": 0, "y": 64, "z": 0 }` | Go to coordinates |
| `mine` | `{ "block": "oak_log" }` | Find and mine nearest block (within 48 blocks) |
| `attack` | `{}` | Fight nearest hostile mob |
| `flee` | `{}` | Run from nearest threat |
| `equip` | `{ "item": "sword" }` | Hold an item |
| `eat` | `{}` | Eat food from inventory |
| `jump` | `{}` | Jump once |
| `look_at_player` | `{}` | Face nearest player |
| `idle` | `{}` | Cancel current action |

## Bot Behavior States

The bot is always in one of these states (defined in `minecraft_context.md`):

1. **Following & Nearby** — default state; stays within range of James (hiplizard36)
2. **Mining** — most common active state; seeks nearby ores and wood
3. **Managing Inventory** — deposits excess items, keeps tools/food/armor
4. **Staying Alive** — eats when food < 14, flees when health < 6 with mobs nearby
5. **Water Safety** — actively swims to avoid drowning

**Proactive triggers (from `plugin.py`):**
- Food < 14 and idle → auto-eat
- Health < 6 and mobs nearby → flee
- James (hiplizard36) not in nearby_players and idle → follow

## Bot Self-Modification

`bot_update_tool.py` lets Hayeong read and modify her own bot code:

```
action: minecraft
params: action_type=read, section=behavior

action: minecraft
params: action_type=write, content=[full new bot.js content]

action: minecraft
params: action_type=restart
```

**Safety check on write:** content must contain `mineflayer`, `pathfinder`,
`executeCommand`, `writeState`, and `startBehaviorLoop` — write is refused if
any are missing. A timestamped backup is created before every write.

## What To Know

Mineflayer connects at protocol level. On modded servers, block and entity
IDs come with string registry names (e.g. rlcraft:dragon_bone_sword).
These names are readable even if not in Hayeong's vanilla reference.
She uses the name to infer category and behavior, then logs what she learns.

Unknown entities are treated as potentially hostile until classified.
Movement vectors are observable — an entity closing distance aggressively
is distinguishable from one wandering passively.
