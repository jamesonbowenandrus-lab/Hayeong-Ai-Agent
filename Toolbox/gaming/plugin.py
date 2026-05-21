"""
Toolbox/gaming/plugin.py

Gaming vision plugin. Reads Brain/state/gaming_state.json and injects
structured game context into Hayeong's presence loop during active sessions.

Auto-discovered by plugin_registry — no manual registration needed.
No changes to main.py required.

When bo3_memory_reader.py is running and a Zombies match is active,
Hayeong will know the round, zombie count, health, and points in real time.
"""

import json
import math
from pathlib import Path
from datetime import datetime

STATE_PATH           = Path(__file__).parent.parent.parent / "Brain" / "state" / "gaming_state.json"
STALE_THRESHOLD_SECS = 5.0


def tick():
    """Called periodically by plugin loop. No action needed — this plugin is passive."""
    pass


def get_context_injection(state: dict = None) -> list:
    """
    Returns context strings injected into Hayeong's presence loop.
    Returns empty list when no game session is active or state file is missing.
    """
    if not STATE_PATH.exists():
        return []

    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not data.get("game_active"):
        return []

    # Staleness check — if reader crashed, warn rather than inject stale data
    try:
        ts      = datetime.fromisoformat(data.get("timestamp", ""))
        age_sec = (datetime.now() - ts).total_seconds()
        if age_sec > STALE_THRESHOLD_SECS:
            return ["[Gaming] Warning: game state data is stale — memory reader may not be running"]
    except Exception:
        return ["[Gaming] Warning: could not parse game state timestamp"]

    gs = data.get("game_state", {})
    if not gs:
        return []

    return _format_game_context(gs)


def _format_game_context(gs: dict) -> list:
    """Format game state dict into readable context strings for the presence loop."""
    lines = ["[Gaming — BO3 Zombies]"]

    round_num = gs.get("round", 0)
    if round_num > 0:
        lines.append(f"  Round: {round_num}")

    zombies_remaining = gs.get("zombies_remaining", 0)
    lines.append(f"  Zombies remaining: {zombies_remaining}")

    health = gs.get("player_health", 0)
    lines.append(f"  Health: {health}")

    points = gs.get("player_points", 0)
    lines.append(f"  Points: {points}")

    px = gs.get("player_x")
    py = gs.get("player_y")
    pz = gs.get("player_z")
    if px is not None and py is not None and pz is not None:
        lines.append(f"  Position: ({px}, {py}, {pz})")

    ammo = gs.get("player_ammo", 0)
    lines.append(f"  Ammo: {ammo}")

    # Nearest zombie — 2D distance ignoring Z/height
    zombies = gs.get("zombies", [])
    if zombies and px is not None and py is not None:
        nearest = _nearest_zombie_distance(px, py, zombies)
        if nearest is not None:
            lines.append(f"  Nearest zombie: {nearest:.1f} units away")

    return lines


def _nearest_zombie_distance(px: float, py: float, zombies: list) -> float | None:
    """Return 2D distance to the nearest zombie. Returns None if list is empty."""
    min_dist = None
    for z in zombies:
        try:
            dx   = z.get("x", 0.0) - px
            dy   = z.get("y", 0.0) - py
            dist = math.sqrt(dx * dx + dy * dy)
            if min_dist is None or dist < min_dist:
                min_dist = dist
        except Exception:
            continue
    return min_dist
