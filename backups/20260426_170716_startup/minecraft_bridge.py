# minecraft_bridge.py
# Start this FIRST, then node hayeong_bot.js
# Stop with Ctrl+C
#
# Architecture: bridge is a pure executor.
#   event → write game state to shared state → check pending action → send → loop
#   All decisions come from reasoning_loop.py (14b). Bridge never calls an LLM.

import socket
import os
import json
import threading
import queue
import time
import signal
import sys
import datetime
from pathlib import Path
from long_term_memory import remember, categorize, CATEGORY_MINECRAFT
from hayeong_core import (
    load_memory, load_mood,
    save_memory, save_json, adjust_mood_by_context,
    MOOD_FILE,
)

HOST = "127.0.0.1"
PORT = 9876

BASE_DIR          = Path(__file__).parent
MC_KNOWLEDGE_FILE = BASE_DIR / "minecraft_knowledge.json"

memory     = load_memory()
mood_state = load_mood()

# -------------------------
# USERNAME → REAL NAME MAP
# -------------------------
USERNAME_MAP = {
    "hiplizard36": "James",
    "James":       "James",
}

# -------------------------
# Action logger
# -------------------------
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

def log_interaction(event_type, game_state, extra, action, quality=None):
    entry = {
        "timestamp":  datetime.datetime.now().isoformat(),
        "event_type": event_type,
        "game_state": game_state,
        "extra":      extra,
        "action":     action,
        "quality":    quality,
    }
    date_str  = datetime.date.today().isoformat()
    log_path  = os.path.join(LOG_DIR, "minecraft_" + date_str + ".jsonl")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

def real_name(username):
    return USERNAME_MAP.get(username, username)

def is_james(username):
    return real_name(username) == "James"


# ─────────────────────────────────────────────
# SHARED STATE — writes game state to reasoning shared state on every event
# ─────────────────────────────────────────────

def _assess_urgency(game_state: dict) -> str:
    """Classify current game state urgency for the reasoning loop's adaptive interval.
    This describes reality — the LLM decides what to do about it."""
    health = game_state.get("health", 20)
    mobs   = game_state.get("nearby_mobs", [])
    tod    = game_state.get("time_of_day", 0)

    hostile_close = any(m.get("dist", 999) < 8 for m in mobs)

    if health < 6 or hostile_close:
        return "danger"
    elif health < 12 or (tod or 0) > 12000:
        return "elevated"
    else:
        return "normal"


def _write_game_state(game_state: dict, event_type: str, event_detail: dict = None):
    """Write current game state to shared state. Called on every event from the bot."""
    from state_manager import write_reasoning
    state = {
        "active":           True,
        "last_updated":     datetime.datetime.now().isoformat(),
        "event_type":       event_type,
        "health":           game_state.get("health", 20),
        "food":             game_state.get("food", 20),
        "position":         game_state.get("position", {}),
        "time_of_day":      game_state.get("time_of_day", 0),
        "dimension":        game_state.get("dimension", "overworld"),
        "nearby_mobs":      game_state.get("nearby_mobs", []),
        "nearby_players":   game_state.get("nearby_players", []),
        "inventory":        game_state.get("inventory", []),
        "inventory_layout": game_state.get("inventory_layout", []),
        "held_item":        game_state.get("held_item", ""),
    }
    updates = {
        "minecraft_state":          state,
        "minecraft_last_event":     event_type,
        "minecraft_urgency":        _assess_urgency(game_state),
        "minecraft_session_active": True,
    }
    if event_detail is not None:
        updates["minecraft_last_event_detail"] = event_detail
    write_reasoning(updates)


# ─────────────────────────────────────────────
# MINECRAFT KNOWLEDGE BASE — persists across sessions
# ─────────────────────────────────────────────

FOOD_ITEMS = [
    "bread", "cooked_beef", "cooked_porkchop", "cooked_chicken",
    "cooked_mutton", "cooked_salmon", "cooked_cod", "apple",
    "golden_apple", "carrot", "baked_potato", "cooked_rabbit",
]

RESOURCE_CONCEPTS = {
    "oak_log":               {"category": "wood",      "tool": "axe",                    "uses": ["crafting", "building", "fuel"]},
    "birch_log":             {"category": "wood",      "tool": "axe",                    "uses": ["crafting", "building", "fuel"]},
    "spruce_log":            {"category": "wood",      "tool": "axe",                    "uses": ["crafting", "building", "fuel"]},
    "jungle_log":            {"category": "wood",      "tool": "axe",                    "uses": ["crafting", "building", "fuel"]},
    "acacia_log":            {"category": "wood",      "tool": "axe",                    "uses": ["crafting", "building", "fuel"]},
    "dark_oak_log":          {"category": "wood",      "tool": "axe",                    "uses": ["crafting", "building", "fuel"]},
    "coal_ore":              {"category": "fuel",      "tool": "pickaxe",                "uses": ["fuel", "torches", "smelting"]},
    "deepslate_coal_ore":    {"category": "fuel",      "tool": "pickaxe",                "uses": ["fuel", "torches", "smelting"]},
    "iron_ore":              {"category": "metal",     "tool": "pickaxe",                "uses": ["tools", "armor", "crafting"]},
    "deepslate_iron_ore":    {"category": "metal",     "tool": "pickaxe",                "uses": ["tools", "armor", "crafting"]},
    "gold_ore":              {"category": "metal",     "tool": "pickaxe",                "uses": ["golden_tools", "armor", "piglin_trade"]},
    "deepslate_gold_ore":    {"category": "metal",     "tool": "pickaxe",                "uses": ["golden_tools", "armor", "piglin_trade"]},
    "diamond_ore":           {"category": "precious",  "tool": "iron_pickaxe_or_better", "uses": ["best_tools", "best_armor", "enchanting_table"]},
    "deepslate_diamond_ore": {"category": "precious",  "tool": "iron_pickaxe_or_better", "uses": ["best_tools", "best_armor", "enchanting_table"]},
    "emerald_ore":           {"category": "trade",     "tool": "iron_pickaxe_or_better", "uses": ["trading_with_villagers"]},
    "lapis_ore":             {"category": "enchanting","tool": "pickaxe",                "uses": ["enchanting", "dye"]},
    "deepslate_lapis_ore":   {"category": "enchanting","tool": "pickaxe",                "uses": ["enchanting", "dye"]},
    "redstone_ore":          {"category": "redstone",  "tool": "iron_pickaxe_or_better", "uses": ["circuits", "mechanisms", "comparators"]},
    "ancient_debris":        {"category": "nether",    "tool": "diamond_pickaxe",        "uses": ["netherite_ingot", "best_gear"]},
    "cobblestone":           {"category": "building",  "tool": "pickaxe",                "uses": ["building", "tools", "furnace"]},
    "stone":                 {"category": "building",  "tool": "pickaxe",                "uses": ["building", "tools", "furnace"]},
    "gravel":                {"category": "building",  "tool": "shovel",                 "uses": ["paths", "flint"]},
}


def load_mc_knowledge() -> dict:
    if MC_KNOWLEDGE_FILE.exists():
        try:
            with open(MC_KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "version": 1,
        "inventory_philosophy": {"observations": [], "rules_inferred": []},
        "survival_knowledge": {
            "combat": [], "food_management": [],
            "exploration": [], "building": [], "resource_gathering": [],
        },
        "james_preferences": {"playstyle": "", "noted_behaviors": []},
        "session_history": [],
        "james_constraints": {
            "protected_resources": [],
            "protected_areas": [],
            "behavior_rules": [],
        },
    }


def save_mc_knowledge(knowledge: dict):
    knowledge["last_updated"] = datetime.datetime.now().isoformat()
    with open(MC_KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
        json.dump(knowledge, f, indent=2, ensure_ascii=False)


def _update_observation(observations: list, pattern: str):
    for obs in observations:
        if obs["pattern"] == pattern:
            obs["observed_count"] += 1
            obs["last_seen"]  = datetime.date.today().isoformat()
            obs["confidence"] = (
                "high"   if obs["observed_count"] >= 5 else
                "medium" if obs["observed_count"] >= 2 else "low"
            )
            return
    observations.append({
        "pattern":        pattern,
        "confidence":     "low",
        "observed_count": 1,
        "last_seen":      datetime.date.today().isoformat(),
    })


def observe_inventory(game_state: dict, event_context: str = ""):
    """Notice patterns in James's inventory. Called on significant events."""
    knowledge = load_mc_knowledge()
    layout    = game_state.get("inventory_layout", [])
    if not layout:
        return

    observations   = knowledge["inventory_philosophy"]["observations"]
    hotbar_items   = [s["item"] for s in layout if s.get("zone") == "hotbar"]
    food_in_hotbar = [i for i in hotbar_items if any(f in i for f in FOOD_ITEMS)]
    total_food     = sum(s["count"] for s in layout
                        if any(f in s.get("item", "") for f in FOOD_ITEMS))

    if food_in_hotbar:
        _update_observation(observations,
            f"James keeps food ({', '.join(set(food_in_hotbar))}) in hotbar")

    if total_food > 0 and event_context:
        _update_observation(observations,
            f"Carries {total_food} food items when: {event_context}")

    knowledge["inventory_philosophy"]["observations"] = observations[:50]
    save_mc_knowledge(knowledge)


def _write_session_summary(session_memory: list, knowledge: dict):
    mc_events = [m for m in session_memory
                 if m.get("content", "").startswith("[MC]")]
    if not mc_events:
        return
    knowledge.setdefault("session_history", []).append({
        "date":  datetime.date.today().isoformat(),
        "turns": len(mc_events),
    })
    knowledge["session_history"] = knowledge["session_history"][-20:]
    save_mc_knowledge(knowledge)
    remember(
        f"Minecraft session {datetime.date.today().isoformat()}. "
        f"{len(mc_events)} exchanges with James. Inventory patterns logged.",
        category=CATEGORY_MINECRAFT,
        speaker="hayeong",
    )


def _record_james_action(action_type: str, target: str, game_state: dict):
    """Learn from what James is doing — store in resource_gathering knowledge."""
    knowledge = load_mc_knowledge()
    rg        = knowledge["survival_knowledge"].setdefault("resource_gathering", [])
    concept   = RESOURCE_CONCEPTS.get(target, {})
    pos       = game_state.get("position", {})
    y_level   = pos.get("y") if pos else None

    if concept:
        pattern = (
            f"James {action_type}s {target} (category={concept['category']}) "
            f"using {concept['tool']}"
        )
    else:
        pattern = f"James {action_type}s {target}"
    if y_level is not None:
        pattern += f" at y={y_level}"

    _update_observation(rg, pattern)
    knowledge["survival_knowledge"]["resource_gathering"] = rg[:60]
    save_mc_knowledge(knowledge)


# ─────────────────────────────────────────────
# VOICE INPUT QUEUE — voice text pushed here, written to shared state for reasoning loop
# ─────────────────────────────────────────────
_voice_queue      = queue.Queue()
_active_conn      = None
_active_conn_lock = threading.Lock()


def submit_voice_input(text: str):
    """Called from main loop when Minecraft is active — routes speech to MC bridge."""
    _voice_queue.put(text)


def _run_mc_voice_input():
    """Consumer: writes voice transcriptions to shared state for the reasoning loop."""
    print("🎤 [Minecraft] Voice input thread started")
    while True:
        try:
            text = _voice_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        with _active_conn_lock:
            conn = _active_conn
        if conn is None:
            continue

        from state_manager import write_reasoning
        write_reasoning({
            "minecraft_last_event":  "voice_chat",
            "minecraft_voice_input": text,
        })
        print(f"🎤 [Voice→MC] {text!r} → queued for reasoning loop")


# -------------------------
# Shutdown handler
# -------------------------
server_socket  = None
shutdown_flag  = False

def handle_shutdown(sig, frame):
    global shutdown_flag
    print("\n🛑 Shutting down...")
    shutdown_flag = True
    save_memory(memory)
    save_json(MOOD_FILE, mood_state)
    if server_socket:
        try:
            server_socket.close()
        except Exception:
            pass
    print("✅ Saved. Goodbye.")
    sys.exit(0)

signal.signal(signal.SIGINT,  handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


# -------------------------
# Handle bot connection
# -------------------------
def handle_client(conn, addr):
    global _active_conn
    with _active_conn_lock:
        _active_conn = conn
    print("🟢 Bot connected")

    from state_manager import write_reasoning, pop_minecraft_pending_action
    write_reasoning({"minecraft_session_active": True, "minecraft_last_event": "connected"})

    buf = ""

    try:
        while True:
            try:
                data = conn.recv(8192).decode("utf-8", errors="replace")
            except Exception:
                break
            if not data:
                break
            buf += data

            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type", "")
                game_state = event.get("state", {})
                extra      = {k: v for k, v in event.items() if k not in ("type", "state")}

                # Build event detail for types that carry meaningful extra data
                event_detail = None
                if event_type == "chat":
                    event_detail = {
                        "sender":   real_name(extra.get("sender", "?")),
                        "message":  extra.get("message", ""),
                        "is_james": is_james(extra.get("sender", "")),
                    }
                elif event_type in ("needs_report", "discovery", "danger"):
                    event_detail = {
                        "description": extra.get("description", extra.get("reason", "")),
                    }

                # ---- Write live game state to shared state ----
                _write_game_state(game_state, event_type, event_detail)

                # ---- Passive observations — no action needed ----
                if event_type == "james_mined":
                    block_name = extra.get("block", "")
                    if block_name:
                        _record_james_action("mine", block_name, game_state)
                    continue

                # ---- Log incoming chat to memory ----
                if event_type == "chat":
                    msg    = extra.get("message", "")
                    sender = extra.get("sender", "?")
                    if msg:
                        adjust_mood_by_context(msg, mood_state)
                        memory.append({"role": "user", "content": "[MC] " + real_name(sender) + ": " + msg})
                        remember("[MC] " + real_name(sender) + ": " + msg,
                                 category=CATEGORY_MINECRAFT, speaker="james")

                print("📨 [" + event_type + "]", json.dumps(extra)[:50] if extra else "")

                # ---- Check for pending action from reasoning loop ----
                action = pop_minecraft_pending_action()
                if not action or action.get("action") == "idle":
                    continue

                print("🤖 →", action)

                # ---- Log bot's chat responses to memory ----
                if action.get("action") == "chat":
                    mc_msg = "[MC] " + action.get("message", "")
                    print(f"\nHayeong [MC]: {action.get('message', '')}")
                    memory.append({"role": "AI", "content": mc_msg})
                    remember(mc_msg, category=CATEGORY_MINECRAFT, speaker="hayeong")
                    save_memory(memory)

                log_interaction(event_type, game_state, extra, action)

                # ---- Send to bot ----
                try:
                    conn.sendall((json.dumps(action) + "\n").encode("utf-8"))
                except Exception as e:
                    print("⚠️ Send error:", e)
                    break

    except Exception as e:
        print("⚠️ Handler error:", e)
    finally:
        with _active_conn_lock:
            _active_conn = None
        print("🔴 Bot disconnected")
        conn.close()
        from state_manager import write_reasoning
        write_reasoning({
            "minecraft_session_active": False,
            "minecraft_last_event":     "disconnected",
            "minecraft_state": {
                "active":       False,
                "last_updated": datetime.datetime.now().isoformat(),
            },
        })
        _write_session_summary(memory, load_mc_knowledge())


# -------------------------
# Server loop
# -------------------------
def start_server():
    global server_socket
    print("🎮 Hayeong Minecraft Bridge — " + HOST + ":" + str(PORT))
    print("   Ctrl+C to stop\n")

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.settimeout(1.0)
    server_socket.bind((HOST, PORT))
    server_socket.listen(1)

    while not shutdown_flag:
        try:
            conn, addr = server_socket.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
        except socket.timeout:
            continue
        except OSError:
            break

if __name__ == "__main__":
    start_server()
