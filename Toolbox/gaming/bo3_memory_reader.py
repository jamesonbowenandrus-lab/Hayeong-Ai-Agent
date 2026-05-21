"""
Toolbox/gaming/bo3_memory_reader.py

Reads Black Ops 3 (Steam) process memory and writes structured game state
to Brain/state/gaming_state.json for Hayeong's vision layer.

Run this before starting a Zombies session:
    python Toolbox/gaming/bo3_memory_reader.py

Requires: pip install pymem
Requires: Run as Administrator (Windows process memory access)

Poll rate: 50ms (POLL_INTERVAL constant below)
Offsets sourced from: github.com/marcoigorr/Bo3-igorr — Offset.h
"""

import json
import time
import struct
from pathlib import Path
from datetime import datetime

try:
    import pymem
    import pymem.process
except ImportError:
    raise ImportError("pymem not installed. Run: pip install pymem")

# ── Configuration ─────────────────────────────────────────────────────
PROCESS_NAME  = "BlackOps3.exe"
POLL_INTERVAL = 0.05   # seconds (50ms)
MAX_ZOMBIES   = 24

STATE_PATH = Path(__file__).parent.parent.parent / "Brain" / "state" / "gaming_state.json"

# ── Base-relative offsets (relative to BlackOps3.exe module base) ─────
OFFSETS = {
    "round":        0x0A55DDEC,   # direct int read
    "player_base":  0x0A54BDE0,   # pointer → player struct
    "player_ped":   0x0A54BDE8,   # pointer → ped struct (health, ammo)
    "zombie_count": 0x0A54BE40,   # pointer → active zombie count int
    "zombie_list":  0x0A5701B8,   # pointer → zombie entity pointer array
}

# ── Player field offsets (from pointed-to structs) ────────────────────
# Confirmed from Offset.h (marcoigorr/Bo3-igorr)
PLAYER_HEALTH_OFF = 0x2C8    # int, from player_ped pointer
PLAYER_POINTS_OFF = 0x16E84  # int, from player_base pointer
PLAYER_AMMO_OFF   = 0x684    # int (clip ammo), from player_ped pointer

# TODO: player position offsets not found in Offset.h — confirm via Cheat Engine
# Scan for your known X coordinate as a 4-byte float in BlackOps3.exe,
# compute offset from player_ped base, and fill in below.
PLAYER_POS_X_OFF  = None   # float, from player_ped pointer — needs validation
PLAYER_POS_Y_OFF  = None   # float, from player_ped pointer — needs validation
PLAYER_POS_Z_OFF  = None   # float, from player_ped pointer — needs validation

# ── Zombie entity field offsets ───────────────────────────────────────
ZOMBIE_HEALTH_OFF = 0x1A8   # int, from entity pointer
ZOMBIE_POS_OFF    = 0x134   # 3x float (x, z, y order), from entity pointer
ZOMBIE_STRIDE     = 0x8C    # bytes between entries in zombie pointer array
ZOMBIE_VALID_OFF  = 0x228   # int, skip entity if value is 9999 or 666


# ── Helpers ───────────────────────────────────────────────────────────

def follow_pointer(pm: pymem.Pymem, address: int, offsets: list) -> int:
    """
    Follow a pointer chain. Returns the final resolved address.
    offsets: list of ints — each dereferences through the previous result.
    """
    addr = pm.read_longlong(address)
    for offset in offsets[:-1]:
        addr = pm.read_longlong(addr + offset)
    return addr + offsets[-1]


def _read_float_safe(pm: pymem.Pymem, addr: int) -> float:
    """Read a float, returning 0.0 on failure."""
    try:
        return pm.read_float(addr)
    except Exception:
        return 0.0


def _read_int_safe(pm: pymem.Pymem, addr: int) -> int:
    """Read an int, returning 0 on failure."""
    try:
        return pm.read_int(addr)
    except Exception:
        return 0


# ── Core read ─────────────────────────────────────────────────────────

def read_game_state(pm: pymem.Pymem, base: int) -> dict:
    """
    Read all game state from process memory.
    Returns a dict matching the gaming_state.json game_state schema.
    Every field is wrapped in try/except — a bad read skips that field.
    """
    state = {
        "round":             0,
        "zombies_remaining": 0,
        "player_health":     0,
        "player_points":     0,
        "player_x":          0.0,
        "player_y":          0.0,
        "player_z":          0.0,
        "player_ammo":       0,
        "zombies":           [],
    }

    # ── Round (direct read) ───────────────────────────────────────────
    try:
        state["round"] = pm.read_int(base + OFFSETS["round"])
    except Exception as e:
        pass

    # ── Player health ─────────────────────────────────────────────────
    try:
        health_addr = follow_pointer(pm, base + OFFSETS["player_ped"], [PLAYER_HEALTH_OFF])
        state["player_health"] = pm.read_int(health_addr)
    except Exception:
        pass

    # ── Player points ─────────────────────────────────────────────────
    try:
        points_addr = follow_pointer(pm, base + OFFSETS["player_base"], [PLAYER_POINTS_OFF])
        state["player_points"] = pm.read_int(points_addr)
    except Exception:
        pass

    # ── Player ammo (clip) ────────────────────────────────────────────
    try:
        ammo_addr = follow_pointer(pm, base + OFFSETS["player_ped"], [PLAYER_AMMO_OFF])
        state["player_ammo"] = pm.read_int(ammo_addr)
    except Exception:
        pass

    # ── Player position ───────────────────────────────────────────────
    # Position offsets marked None until confirmed via Cheat Engine (see TODO above)
    if PLAYER_POS_X_OFF is not None:
        try:
            ped_ptr = pm.read_longlong(base + OFFSETS["player_ped"])
            state["player_x"] = round(pm.read_float(ped_ptr + PLAYER_POS_X_OFF), 2)
            state["player_y"] = round(pm.read_float(ped_ptr + PLAYER_POS_Y_OFF), 2)
            state["player_z"] = round(pm.read_float(ped_ptr + PLAYER_POS_Z_OFF), 2)
        except Exception:
            pass

    # ── Zombie count ──────────────────────────────────────────────────
    try:
        count_ptr = pm.read_longlong(base + OFFSETS["zombie_count"])
        state["zombies_remaining"] = pm.read_int(count_ptr)
    except Exception:
        pass

    # ── Zombie list ───────────────────────────────────────────────────
    try:
        list_ptr = pm.read_longlong(base + OFFSETS["zombie_list"])
        zombies = []
        for i in range(MAX_ZOMBIES):
            try:
                entity_ptr = pm.read_longlong(list_ptr + i * ZOMBIE_STRIDE)
                if not entity_ptr or entity_ptr < 0x10000:
                    continue

                valid_val = _read_int_safe(pm, entity_ptr + ZOMBIE_VALID_OFF)
                if valid_val in (9999, 666):
                    continue

                health = _read_int_safe(pm, entity_ptr + ZOMBIE_HEALTH_OFF)
                if health <= 0:
                    continue

                # Position: x, z, y order per handoff spec
                x = _read_float_safe(pm, entity_ptr + ZOMBIE_POS_OFF)
                z = _read_float_safe(pm, entity_ptr + ZOMBIE_POS_OFF + 4)
                y = _read_float_safe(pm, entity_ptr + ZOMBIE_POS_OFF + 8)
                zombies.append({
                    "x":      round(x, 1),
                    "y":      round(y, 1),
                    "z":      round(z, 1),
                    "health": health,
                })
            except Exception:
                continue
        state["zombies"] = zombies
    except Exception:
        pass

    return state


# ── State writer ──────────────────────────────────────────────────────

def write_state(game_active: bool, game_state: dict):
    """Write current game state to gaming_state.json."""
    payload = {
        "timestamp":  datetime.now().isoformat(),
        "game_active": game_active,
        "game_state":  game_state,
    }
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_inactive():
    """Write game_active: false — used on detach or shutdown."""
    write_state(False, {})


# ── Main loop ─────────────────────────────────────────────────────────

def run():
    """
    Attach to BlackOps3.exe and read game state in a tight loop.
    Retries every 2 seconds if the game isn't running.
    Runs until Ctrl+C.
    """
    pm   = None
    base = None
    last_round = -1

    print(f"[bo3_reader] Waiting for {PROCESS_NAME}...")
    print(f"[bo3_reader] Poll interval: {int(POLL_INTERVAL * 1000)}ms | Max zombies: {MAX_ZOMBIES}")
    print(f"[bo3_reader] Writing to: {STATE_PATH}")
    print(f"[bo3_reader] Press Ctrl+C to stop.\n")

    try:
        while True:
            # ── Attach phase ──────────────────────────────────────────
            if pm is None:
                try:
                    pm   = pymem.Pymem(PROCESS_NAME)
                    base = pymem.process.module_from_name(pm.process_handle, PROCESS_NAME).lpBaseOfDll
                    print(f"[bo3_reader] Attached to {PROCESS_NAME} (PID: {pm.process_id}, base: {hex(base)})")
                except Exception:
                    write_inactive()
                    time.sleep(2)
                    continue

            # ── Read phase ────────────────────────────────────────────
            try:
                gs = read_game_state(pm, base)
                write_state(True, gs)

                if gs["round"] != last_round and gs["round"] > 0:
                    print(f"[bo3_reader] Round {gs['round']} | Zombies: {gs['zombies_remaining']} | HP: {gs['player_health']} | Pts: {gs['player_points']}")
                    last_round = gs["round"]

            except Exception as e:
                print(f"[bo3_reader] Read error: {e} — attempting reattach")
                write_inactive()
                pm   = None
                base = None
                time.sleep(2)
                continue

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n[bo3_reader] Stopping — writing inactive state.")
        write_inactive()
        print("[bo3_reader] Done.")


if __name__ == "__main__":
    run()
