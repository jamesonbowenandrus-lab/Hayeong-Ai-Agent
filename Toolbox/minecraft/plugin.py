"""
plugin.py — Minecraft presence plugin.

Self-contained Minecraft proactive behavior and context injection.
Discovered automatically by toolbox/plugin_registry.py.

Interface:
    tick()                          — dispatch pending actions, run proactive behavior
    get_context_injection(state)    — return lines to inject into presence context
    on_server_connect(world_id)     — load world model on connect
    on_server_disconnect()          — save session and world state on disconnect
    on_player_join(username)        — handle player join events
    update_world_knowledge(type, data) — Hayeong updates her own world model
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from brain.config import MINECRAFT_STATE_PATH, MINECRAFT_COMMAND_PATH

_STATE_PATH   = Path(MINECRAFT_STATE_PATH)
_COMMAND_PATH = Path(MINECRAFT_COMMAND_PATH)
_WORLDS_DIR   = _STATE_PATH.parent.parent / "worlds"

_MINECRAFT_KEYWORDS = {
    "minecraft", "bot", "follow", "mine", "craft", "server",
    "jump", "attack", "mob", "creeper", "zombie", "inventory",
    "goto", "flee", "equip", "eat", "idle", "stop", "look",
}

_PROACTIVE_INTERVAL = 10  # seconds between proactive checks
_last_proactive_at  = 0.0

# ── World model state (per session) ──────────────────────────────────
_world_id           = ""
_world_context      = {}
_map_data           = {}
_projects           = {}
_session_log        = {}
_james_was_present  = False
_session_start      = ""
_current_task       = ""
_current_coordinates = {}
_session_events     = []


# ── State file helpers ────────────────────────────────────────────────

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


def _load_json(path: Path, default) -> dict | list:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _world_dir(wid: str) -> Path:
    return _WORLDS_DIR / wid


# ── World model load/save ─────────────────────────────────────────────

def _load_world_context(wid: str) -> dict:
    return _load_json(_world_dir(wid) / "world_context.json", {})

def _load_map(wid: str) -> dict:
    return _load_json(_world_dir(wid) / "map.json", {})

def _load_projects(wid: str) -> dict:
    return _load_json(_world_dir(wid) / "projects.json", {})

def _load_session_log(wid: str) -> dict:
    return _load_json(_world_dir(wid) / "session_log.json", {"world_id": wid, "sessions": []})

def _save_world_context() -> None:
    if _world_id:
        _save_json(_world_dir(_world_id) / "world_context.json", _world_context)

def _save_map() -> None:
    if _world_id:
        _save_json(_world_dir(_world_id) / "map.json", _map_data)

def _save_projects() -> None:
    if _world_id:
        _save_json(_world_dir(_world_id) / "projects.json", _projects)


# ── Session helpers ───────────────────────────────────────────────────

def _calculate_absence(ctx: dict) -> float:
    """Return hours since the last James session ended."""
    last_end = ctx.get("absence_context", {}).get("last_james_session_end", "")
    if not last_end:
        return 0.0
    try:
        then = datetime.fromisoformat(last_end)
        return (datetime.now() - then).total_seconds() / 3600
    except Exception:
        return 0.0


def _push_world_context_to_shared_state() -> None:
    """Write summary of world context into the shared state bus."""
    try:
        from brain.state.core_manager import write_section
        write_section("minecraft_world_context", {
            "world_id":       _world_id,
            "return_mode":    _world_context.get("absence_context", {}).get("return_mode", "resume"),
            "active_project": _projects.get("active_project"),
            "world_phase":    _world_context.get("world_status", {}).get("game_phase", "unknown"),
        })
    except Exception:
        pass


def _push_to_shared_state(payload: dict) -> None:
    """Push a generic event payload to the shared state bus."""
    try:
        from brain.state.core_manager import write_section
        write_section("minecraft_event", payload)
    except Exception:
        pass


def _save_session(james_present: bool, what_happened: str,
                  left_unfinished: str, hayeong_intended_next: str) -> None:
    """Append a new session entry to session_log.json."""
    if not _world_id:
        return
    log = _load_session_log(_world_id)
    duration = 0
    if _session_start:
        try:
            started = datetime.fromisoformat(_session_start)
            duration = round((datetime.now() - started).total_seconds() / 60)
        except Exception:
            pass
    log.setdefault("sessions", []).append({
        "session_id":              _session_start or datetime.now().isoformat(),
        "james_present":           james_present,
        "duration_minutes":        duration,
        "what_happened":           what_happened,
        "left_unfinished":         left_unfinished,
        "hayeong_intended_next":   hayeong_intended_next,
        "mood_at_end":             "",
    })
    _save_json(_world_dir(_world_id) / "session_log.json", log)


# ── Project helpers ───────────────────────────────────────────────────

def _update_project(data: dict) -> None:
    if not _world_id:
        return
    proj_id = data.get("id")
    active  = _projects.get("active_project")
    if isinstance(active, dict) and active.get("id") == proj_id:
        active.update(data)
        active["last_worked"] = datetime.now().isoformat()
    for p in _projects.get("queued_projects", []):
        if p.get("id") == proj_id:
            p.update(data)
    _save_projects()


def _complete_project(proj_id: str) -> None:
    if not _world_id:
        return
    active = _projects.get("active_project")
    if isinstance(active, dict) and active.get("id") == proj_id:
        active["status"] = "complete"
        _projects.setdefault("completed_projects", []).append(active)
        _projects["active_project"] = None
    _save_projects()


# ── World model events ────────────────────────────────────────────────

def on_server_connect(world_id: str) -> None:
    """Called when bot connects to a server. Loads world model."""
    global _world_id, _world_context, _map_data, _projects, _session_log
    global _session_start, _james_was_present, _session_events

    _world_id          = world_id
    _world_context     = _load_world_context(world_id)
    _map_data          = _load_map(world_id)
    _projects          = _load_projects(world_id)
    _session_log       = _load_session_log(world_id)
    _session_start     = datetime.now().isoformat()
    _james_was_present = False
    _session_events    = []

    absence_hours = _calculate_absence(_world_context)
    mode = "assess" if absence_hours > 48 else "resume"
    _world_context.setdefault("absence_context", {})["return_mode"] = mode

    _push_world_context_to_shared_state()
    print(f"[minecraft/plugin] Connected to world '{world_id}' — return_mode: {mode}")


def on_server_disconnect() -> None:
    """Called when bot disconnects. Saves session and world state."""
    active_project = _projects.get("active_project")
    next_step      = active_project.get("next_step", "") if isinstance(active_project, dict) else ""

    _save_session(
        james_present=_james_was_present,
        what_happened="; ".join(_session_events[-5:]) if _session_events else "",
        left_unfinished=next_step,
        hayeong_intended_next="",
    )
    if _world_context:
        _world_context.setdefault("absence_context", {})["last_james_session_end"] = (
            datetime.now().isoformat() if _james_was_present else
            _world_context["absence_context"].get("last_james_session_end", "")
        )
        _world_context["last_played"] = datetime.now().isoformat()
        _world_context["total_sessions"] = _world_context.get("total_sessions", 0) + 1
        _save_world_context()
    _save_projects()
    print(f"[minecraft/plugin] Disconnected from world '{_world_id}' — session saved")


def on_player_join(username: str) -> None:
    """Called when any player joins the server."""
    global _james_was_present
    if username.lower() in ("james", "hiplizard36"):
        _james_was_present = True
        _handle_james_joined()
    else:
        _handle_other_joined(username)


def _handle_james_joined() -> None:
    """
    James joined while Hayeong is playing solo.
    Push the join event to shared state — reasoning loop decides how to respond.
    Never hardcodes a response here.
    """
    mc = _read_state()
    _push_to_shared_state({
        "event":                 "james_joined",
        "hayeong_current_task":  _current_task,
        "current_project":       _projects.get("active_project"),
        "hayeong_location":      mc.get("position", {}),
    })
    _session_events.append(f"James joined at {datetime.now().strftime('%H:%M')}")


def _handle_other_joined(username: str) -> None:
    _push_to_shared_state({
        "event":    "other_player_joined",
        "username": username,
    })


def update_world_knowledge(update_type: str, data: dict) -> None:
    """
    Hayeong updates her own world model when she learns something.
    Called when reasoning loop decides to record new world knowledge.
    """
    if update_type == "add_location":
        _map_data.setdefault("named_locations", []).append(data)
        _save_map()
    elif update_type == "add_resource_note":
        _map_data.setdefault("resource_notes", []).append(data)
        _save_map()
    elif update_type == "add_nav_note":
        _map_data.setdefault("navigation_notes", []).append(data)
        _save_map()
    elif update_type == "update_project":
        _update_project(data)
    elif update_type == "complete_project":
        _complete_project(data.get("id", ""))


# ── Context injection (presence loop) ────────────────────────────────

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
        lines = [
            "",
            "MINECRAFT BOT STATE (live):",
            f"- Position: {mc.get('position')}",
            f"- Health: {mc.get('health')}/20  Food: {mc.get('food')}/20",
            f"- Nearby players: {mc.get('nearby_players', [])}",
            f"- Nearby mobs: {mc.get('nearby_mobs', [])}",
            f"- Last event: {mc.get('last_event')}",
        ]
        if _world_id and _projects.get("active_project"):
            proj = _projects["active_project"]
            lines.append(f"- Active project: {proj.get('label', '')} — {proj.get('next_step', '')}")
        return lines
    else:
        return [
            "",
            f"MINECRAFT BOT STATE: not connected — {mc.get('last_event', 'unknown')}",
        ]


# ── Proactive behavior ────────────────────────────────────────────────

def _run_proactive() -> None:
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


# ── Main tick ─────────────────────────────────────────────────────────

def tick() -> None:
    """Called every ~2 seconds by the generic plugin loop in main."""
    try:
        from brain.state_manager import pop_minecraft_pending_action
        from toolbox.minecraft.minecraft_bridge import send_minecraft_command
        action = pop_minecraft_pending_action()
        if action and action.get("action") not in (None, "idle"):
            cmd = action.pop("action")
            send_minecraft_command(cmd, action)
    except Exception:
        pass

    _run_proactive()
