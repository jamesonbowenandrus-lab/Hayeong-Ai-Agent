"""
plugin.py — Minecraft presence plugin.

Self-contained Minecraft proactive behavior and context injection.
Discovered automatically by toolbox/plugin_registry.py.

Interface:
    tick()                          — dispatch pending actions, run proactive behavior
    get_context_injection(state)    — return lines to inject into presence context
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from brain.config import MINECRAFT_STATE_PATH

_STATE_PATH = Path(MINECRAFT_STATE_PATH)

_MINECRAFT_KEYWORDS = {
    "minecraft", "bot", "follow", "mine", "craft", "server",
    "jump", "attack", "mob", "creeper", "zombie", "inventory",
    "goto", "flee", "equip", "eat", "idle", "stop", "look",
}

_PROACTIVE_INTERVAL = 10  # seconds between proactive checks
_last_proactive_at  = 0.0


def _read_state() -> dict:
    """Read minecraft_state.json. Returns {} if missing, disconnected, or stale (>10s)."""
    try:
        if not _STATE_PATH.exists():
            return {}
        state = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        if not state.get("connected"):
            return state
        updated_str = state.get("updated_at", "")
        if not updated_str:
            return {}
        updated = datetime.fromisoformat(updated_str).replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - updated).total_seconds() > 10:
            return {}
        return state
    except Exception:
        return {}


def _context_relevant(situation: dict, last_task: dict) -> bool:
    if (last_task.get("tool") or "").lower() == "minecraft":
        return True
    msg = (situation.get("what_james_said") or "").lower()
    return any(kw in msg for kw in _MINECRAFT_KEYWORDS)


def get_context_injection(state: dict = None) -> list:
    """
    Return a list of strings to append to the presence context.
    Returns [] when Minecraft is not relevant or bot is not connected.
    """
    if state is None:
        from brain.state.core_manager import read as _read
        state = _read()

    if not _context_relevant(state.get("situation", {}), state.get("last_task", {})):
        return []

    mc = _read_state()
    if not mc:
        return []

    if mc.get("connected"):
        return [
            "",
            "MINECRAFT BOT STATE (live):",
            f"- Position: {mc.get('position')}",
            f"- Health: {mc.get('health')}/20  Food: {mc.get('food')}/20",
            f"- Nearby players: {mc.get('nearby_players', [])}",
            f"- Nearby mobs: {mc.get('nearby_mobs', [])}",
            f"- Last event: {mc.get('last_event')}",
        ]
    else:
        return [
            "",
            f"MINECRAFT BOT STATE: not connected — {mc.get('last_event', 'unknown')}",
        ]


def _run_proactive():
    """Fire occasional autonomous actions when the bot is idle and connected."""
    global _last_proactive_at
    now = time.time()
    if now - _last_proactive_at < _PROACTIVE_INTERVAL:
        return
    _last_proactive_at = now

    mc = _read_state()
    if not mc.get("connected"):
        return

    current_action = mc.get("current_action", "idle")
    health         = mc.get("health", 20)
    food           = mc.get("food",   20)
    nearby_players = mc.get("nearby_players", [])
    nearby_mobs    = mc.get("nearby_mobs",    [])

    from toolbox.minecraft.minecraft_bridge import send_minecraft_command

    if food < 14 and current_action == "idle":
        send_minecraft_command("eat")
        return

    if health < 6 and nearby_mobs and current_action != "flee":
        send_minecraft_command("flee")
        return

    if "hiplizard36" not in nearby_players and current_action == "idle":
        send_minecraft_command("follow", {"username": "hiplizard36"})
        return


def tick():
    """Called every ~2 seconds by the generic plugin loop in main."""
    # 1. Dispatch any pending action written by the reasoning loop
    try:
        from brain.state_manager import pop_minecraft_pending_action
        from toolbox.minecraft.minecraft_bridge import send_minecraft_command
        action = pop_minecraft_pending_action()
        if action and action.get("action") not in (None, "idle"):
            cmd = action.pop("action")
            send_minecraft_command(cmd, action)
    except Exception:
        pass

    # 2. Run proactive behavior
    _run_proactive()
