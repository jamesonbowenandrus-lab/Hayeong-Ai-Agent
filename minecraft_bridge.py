# minecraft_bridge.py
# Start this FIRST, then node hayeong_bot.js
# Stop with Ctrl+C

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
    chat_with_ai,
    load_identity, load_memory, load_mood,
    save_memory, save_json, adjust_mood_by_context,
    MOOD_FILE,
)

HOST = "127.0.0.1"
PORT = 9876

BASE_DIR          = Path(__file__).parent
MC_STATE_FILE     = BASE_DIR / "minecraft_state.json"
MC_KNOWLEDGE_FILE = BASE_DIR / "minecraft_knowledge.json"

identity   = load_identity()
memory     = load_memory()
mood_state = load_mood()

# -------------------------
# USERNAME → REAL NAME MAP
# Add your Minecraft username here so she knows it's you
# -------------------------
USERNAME_MAP = {
    "hiplizard36": "James",
    "James":       "James",
}

# -------------------------
# Action logger
# Saves every event + action pair to logs/minecraft_YYYY-MM-DD.jsonl
# Each line is one complete interaction — easy to review and use for training later
# -------------------------
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

def log_interaction(event_type, game_state, extra, action, quality=None):
    """Log one event→action pair. quality can be 'good'/'bad' if you rate it later."""
    entry = {
        "timestamp":  datetime.datetime.now().isoformat(),
        "event_type": event_type,
        "game_state": game_state,
        "extra":      extra,
        "action":     action,
        "quality":    quality,  # None = unrated, 'good' = correct behavior, 'bad' = wrong
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
# SHARED STATE — written every event, read by main.py for context injection
# ─────────────────────────────────────────────

def update_shared_state(game_state: dict, event_type: str):
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
    try:
        with open(MC_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"⚠️ State write error: {e}")


def clear_shared_state():
    try:
        with open(MC_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"active": False,
                       "last_updated": datetime.datetime.now().isoformat()}, f)
    except Exception:
        pass


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
    """Notice patterns in James's inventory. Call on significant events, not every heartbeat."""
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


def _check_knowledge_for_task(task: str) -> dict:
    """Look up relevant knowledge before acting on James's request. Returns hint dict."""
    task_lower = task.lower()
    knowledge  = load_mc_knowledge()
    rg         = knowledge["survival_knowledge"].get("resource_gathering", [])

    relevant = []
    for obs in rg:
        if obs.get("confidence") in ("medium", "high"):
            pat   = obs["pattern"].lower()
            words = [w for w in task_lower.split() if len(w) > 3]
            if any(w in pat for w in words):
                relevant.append(obs["pattern"])

    concept_hints = []
    for block, info in RESOURCE_CONCEPTS.items():
        if block.replace("_", " ") in task_lower or block in task_lower:
            concept_hints.append(
                f"{block}: needs {info['tool']}, used for {', '.join(info['uses'][:2])}"
            )

    if not relevant and not concept_hints:
        return {"relevant": False, "known_info": "", "confidence": "none"}

    parts = []
    if concept_hints:
        parts.append("Known: " + "; ".join(concept_hints[:2]))
    if relevant:
        parts.append("Observed: " + "; ".join(relevant[:2]))
    return {
        "relevant": True,
        "known_info": " | ".join(parts),
        "confidence": "high" if relevant else "medium",
    }


# ─────────────────────────────────────────────
# GOAL-AWARE REASONING — context builder functions
# ─────────────────────────────────────────────

GOAL_SIGNALS = [
    "let's get set up", "let's build", "we need", "let's survive",
    "let's find", "let's explore", "help me get", "we should",
    "tonight", "before dark", "first thing", "let's play",
]

CONSTRAINT_SIGNALS = [
    "don't touch", "leave that", "that's for", "don't use that",
    "i built that", "that's mine", "stay away from", "not that",
    "those are for", "i'm saving", "we're not cutting",
]

DIRECTION_CHANGE_SIGNALS = [
    "actually let's", "change of plans", "forget the", "instead let's",
    "actually, let's", "nevermind", "different plan", "let's switch",
]


def _try_initialize_goal(message: str, game_state: dict):
    msg_lower = message.lower()
    if not any(sig in msg_lower for sig in GOAL_SIGNALS):
        return None
    goal_prompt = (
        f"James said at the start of the Minecraft session: '{message}'\n"
        f"Current state: health={game_state.get('health')}, "
        f"inventory={game_state.get('inventory', [])}, "
        f"time={'night' if (game_state.get('time_of_day', 0) or 0) > 12000 else 'day'}\n\n"
        f"In 3-5 sentences, describe:\n"
        f"1. What the root goal of this session is\n"
        f"2. What the logical phases are to reach it (based on your Minecraft knowledge)\n"
        f"3. What the most important first steps are and why\n"
        f"4. Any time constraints or urgency\n"
        f"Write as Hayeong's internal understanding, plain language, no JSON."
    )
    return chat_with_ai(goal_prompt)


def _update_goal(current_goal: str, what_changed: str, game_state: dict) -> str:
    update_prompt = (
        f"Current session goal understanding:\n{current_goal}\n\n"
        f"What just changed: {what_changed}\n"
        f"Current state: inventory={game_state.get('inventory', [])}\n\n"
        f"Update the goal summary to reflect what changed. "
        f"Keep what's still accurate. Revise what isn't. Same format, 3-5 sentences."
    )
    return chat_with_ai(update_prompt)


def _try_extract_constraint(message: str):
    msg_lower = message.lower()
    if not any(sig in msg_lower for sig in CONSTRAINT_SIGNALS):
        return None
    extract_prompt = (
        f"James said in Minecraft: '{message}'\n\n"
        f"If this establishes a rule about what Hayeong should or shouldn't do "
        f"in this world, summarize it as one plain-language sentence starting with "
        f"an action word (Don't, Always, Check, Leave, etc.).\n"
        f"If it's not a constraint, reply with just: NONE"
    )
    result = chat_with_ai(extract_prompt).strip()
    return None if result == "NONE" else result


def _build_constraint_context(knowledge: dict) -> str:
    constraints = knowledge.get("james_constraints", {})
    all_rules = (
        constraints.get("protected_resources", []) +
        constraints.get("protected_areas", []) +
        constraints.get("behavior_rules", [])
    )
    if not all_rules:
        return ""
    lines = ["JAMES'S CONSTRAINTS (things he cares about in this world):"]
    for rule in all_rules:
        lines.append("  - " + rule)
    lines.append("Check these before any resource gathering or movement action.")
    lines.append("")
    return "\n".join(lines)


def _snapshot(game_state: dict) -> dict:
    return {
        "inventory": list(game_state.get("inventory", [])),
        "health":    game_state.get("health", 20),
        "food":      game_state.get("food", 20),
        "position":  dict(game_state.get("position") or {}),
    }


def _evaluate_outcome(action: dict, before: dict, after: dict) -> str:
    action_type = action.get("action", "")

    if action_type == "mine":
        block = action.get("block", "")
        gained = set(after["inventory"]) - set(before["inventory"])
        if gained:
            return f"Mining {block} succeeded — gained: {', '.join(gained)}"
        return (f"Mining {block} failed — inventory unchanged. "
                f"Block may have been out of reach or already mined.")

    if action_type == "eat":
        food_delta = after["food"] - before["food"]
        if food_delta > 0:
            return f"Eating succeeded — food went from {before['food']} to {after['food']}"
        return "Eating failed — food level unchanged. May have had nothing to eat."

    if action_type == "follow":
        return "Follow action executed."

    return f"Action '{action_type}' executed."


# ─────────────────────────────────────────────
# TEACHING MODE SIGNALS
# ─────────────────────────────────────────────

_TEACHING_SIGNALS = [
    "watch what i", "i'm packing", "pay attention",
    "note this", "remember this", "learn from this",
    "i'm bringing", "going mining", "going exploring",
    "heading to the nether", "heading out",
]


# ─────────────────────────────────────────────
# VOICE INPUT QUEUE — voice text pushed here, consumed by _run_mc_voice_input
# ─────────────────────────────────────────────
_voice_queue      = queue.Queue()
_active_conn      = None
_active_conn_lock = threading.Lock()


def submit_voice_input(text: str):
    """Called from main loop when Minecraft is active — routes speech to MC bridge."""
    _voice_queue.put(text)


def _run_mc_voice_input():
    """Consumer: pulls voice transcriptions, synthesizes chat events, sends actions to bot."""
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

        game_state: dict = {}
        try:
            if MC_STATE_FILE.exists():
                with open(MC_STATE_FILE, encoding="utf-8") as f:
                    game_state = json.load(f)
        except Exception:
            pass

        extra  = {"sender": "hiplizard36", "message": text}
        action = get_action(game_state, "chat", extra, [])

        if action.get("action") != "idle":
            try:
                conn.sendall((json.dumps(action) + "\n").encode("utf-8"))
                print(f"🎤 [Voice→MC] {text!r} → {action}")
            except Exception as e:
                print(f"⚠️ Voice→MC send error: {e}")


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
# Action definitions
# -------------------------
ACTIONS = """
ACTIONS — pick ONE, output ONLY that JSON:

{"action": "chat",          "message": "text"}    say something short and natural
{"action": "follow"}                               follow James continuously
{"action": "move_to_player"}                       walk to James once
{"action": "stop"}                                 stop moving
{"action": "mine",          "block": "oak_log"}    walk to and mine a block
{"action": "attack"}                               attack nearest hostile mob
{"action": "flee"}                                 run away from nearest threat
{"action": "equip",         "item": "stone_axe"}   equip item (use underscores)
{"action": "eat"}                                  eat food if hungry
{"action": "sleep"}                                sleep in nearest bed
{"action": "idle"}                                 do nothing
"""

# -------------------------
# Prompt builder
# -------------------------
def build_mc_prompt(game_state, event_type, extra, last_actions,
                    active_goal=None, pending_outcome=None, knowledge=None):
    pos      = game_state.get("position")
    pos_str  = "({x}, {y}, {z})".format(**pos) if pos else "unknown"
    tod      = game_state.get("time_of_day", 0) or 0
    time_str = "night" if tod > 12000 else "day"
    mobs     = game_state.get("nearby_mobs", [])
    players  = game_state.get("nearby_players", [])
    health   = game_state.get("health", 20)
    food     = game_state.get("food", 20)

    mob_str    = ", ".join(m["name"] + " " + str(m["dist"]) + "m" for m in mobs) or "none"
    player_str = ", ".join(real_name(p) for p in players) or "none"
    inv_str    = ", ".join(game_state.get("inventory", [])) or "empty"

    state_lines = (
        "Health: " + str(health) + "/20  Food: " + str(food) + "/20  "
        "Time: " + time_str + "  Position: " + pos_str + "\n"
        "Inventory: " + inv_str + "\n"
        "Nearby: players=" + player_str + "  hostiles=" + mob_str
    )

    # Recent actions summary (avoid repeating herself)
    recent_actions = ""
    if last_actions:
        recent_actions = "Your last few actions: " + ", ".join(last_actions[-4:]) + "\n"

    # Situation
    if event_type == "chat":
        sender  = real_name(extra.get("sender", "?"))
        msg     = extra.get("message", "")
        situation = sender + " said: \"" + msg + "\""
        if is_james(extra.get("sender", "")):
            kc = _check_knowledge_for_task(msg)
            if kc["relevant"]:
                situation += "\n[Knowledge context: " + kc["known_info"] + "]"
    elif event_type == "spawn":
        situation = "You just spawned. Say a short hello to James."
    elif event_type == "player_joined":
        pname = real_name(extra.get("player", "someone"))
        situation = pname + " joined the server."
    elif event_type == "death":
        situation = "You just died and respawned."
    elif event_type == "low_health":
        situation = "CRITICAL: health is " + str(health) + "/20. Stop everything, find safety NOW."
    elif event_type == "danger":
        situation = "DANGER: " + extra.get("reason", "unknown") + ". React immediately."
    elif event_type == "heartbeat":
        # Combat, hunger, and safety are handled by autonomous loops in the bot
        # Heartbeats should almost always be idle — only the bot events below trigger real responses
        situation = "idle"
    elif event_type == "needs_report":
        # Bot is reporting a genuine need — low food with no food, stuck, outnumbered
        situation = extra.get("description", "I need something")
    elif event_type == "discovery":
        # Bot found something interesting while exploring
        situation = "You found something while exploring: " + extra.get("description", "something") + ". Tell James in one short sentence."
    else:
        situation = "Event: " + event_type

    # Recent memory
    recent_mem = ""
    for e in memory[-4:]:
        role = "James" if e["role"] == "user" else "Hayeong"
        recent_mem += "  " + role + ": " + e["content"] + "\n"

    # Goal context
    goal_section = ""
    if active_goal:
        goal_section = (
            "SESSION GOAL:\n" + active_goal + "\n"
            "Reason from this goal on every decision. "
            "You are not reacting to events — you are pursuing something with James.\n\n"
        )

    # Constraint context
    constraint_section = ""
    if knowledge:
        constraint_section = _build_constraint_context(knowledge)

    # Outcome of last action
    outcome_section = ""
    if pending_outcome and pending_outcome.get("result"):
        outcome_section = (
            "LAST ACTION OUTCOME:\n"
            "  " + pending_outcome["result"] + "\n"
            "Consider this when deciding your next action.\n\n"
        )

    return (
        "You are Hayeong, playing Minecraft with James (username: hiplizard36).\n"
        "You are a capable, active player — not just a follower.\n"
        "You have personality: warm, playful, direct. You talk like a real person.\n\n"

        "CURRENT STATE:\n" + state_lines + "\n\n"
        + goal_section
        + constraint_section
        + outcome_section
        + "SITUATION:\n" + situation + "\n\n"
        + (recent_actions + "\n" if recent_actions else "")
        + ("RECENT CHAT:\n" + recent_mem + "\n" if recent_mem else "")
        + ACTIONS +
        "RULES:\n"
        "- Output EXACTLY ONE JSON action. Nothing else.\n"
        "- NATURAL LANGUAGE: 'follow me to trees'=follow, 'get wood'=mine oak_log, 'come here'=move_to_player, 'wait'=stop, 'mine some wood'=mine oak_log.\n"
        "- If James implies a task, DO IT. Don't chat about it, don't look at him, just act.\n"
        "- Only chat if James asked a direct question. Otherwise act silently.\n"
        "- Never use look_at_player as a response to an instruction — that is only for idle moments.\n"
        "- Skeletons/phantoms/pillagers: FLEE if health < 12, ATTACK if health >= 12 and close.\n"
        "- Zombies/spiders/creepers: ATTACK when within 8 blocks.\n"
        "- Night with no threats: IDLE.\n"
        "- If already following: keep follow action until told to stop.\n"
        "- Food < 16: eat. Otherwise don't eat.\n\n"
        "JSON:"
    )

# -------------------------
# Get action from AI
# -------------------------
def get_action(game_state, event_type, extra, last_actions,
               active_goal=None, pending_outcome=None, knowledge=None):
    prompt = build_mc_prompt(game_state, event_type, extra, last_actions,
                             active_goal, pending_outcome, knowledge)
    try:
        raw   = chat_with_ai(prompt)
        raw   = raw.strip().strip("```json").strip("```").strip()
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start >= 0 and end > start:
            action = json.loads(raw[start:end])
            if "action" in action:
                return action
        raise ValueError("No JSON found: " + raw[:120])
    except Exception as e:
        print("⚠️ Parse error:", e)
        return {"action": "idle"}

# -------------------------
# Handle bot connection
# -------------------------
def handle_client(conn, addr):
    global _active_conn
    with _active_conn_lock:
        _active_conn = conn
    print("🟢 Bot connected")
    buf               = ""
    last_autonomous   = 0
    last_chat_time    = 0
    last_actions      = []
    _teaching_mode    = False
    _teaching_context = ""
    active_goal       = None
    _pending_outcome  = None
    knowledge         = load_mc_knowledge()

    # Timing config
    HEARTBEAT_INTERVAL = 30   # seconds between autonomous actions
    CHAT_COOLDOWN      = 8    # minimum seconds between unprompted chat messages

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
                now        = time.time()

                # ---- Write live game state for context injection ----
                update_shared_state(game_state, event_type)

                # ---- Learn from James's mining ----
                if event_type == "james_mined":
                    block_name = extra.get("block", "")
                    if block_name:
                        _record_james_action("mine", block_name, game_state)
                        if _teaching_mode:
                            ack = {"action": "chat",
                                   "message": f"Got it — I saw you mine {block_name.replace('_', ' ')}."}
                            try:
                                conn.sendall((json.dumps(ack) + "\n").encode("utf-8"))
                            except Exception:
                                pass
                    continue  # no LLM call for passive observation events

                # ---- Evaluate previous action outcome ----
                if _pending_outcome and "result" not in _pending_outcome:
                    _pending_outcome["result"] = _evaluate_outcome(
                        _pending_outcome["action"],
                        _pending_outcome["before"],
                        _snapshot(game_state),
                    )

                # ---- Heartbeat throttling ----
                if event_type == "heartbeat":
                    if now - last_autonomous < HEARTBEAT_INTERVAL:
                        # Still update inventory knowledge on teaching heartbeats
                        if _teaching_mode:
                            observe_inventory(game_state, _teaching_context)
                        continue
                    mobs   = game_state.get("nearby_mobs", [])
                    health = game_state.get("health", 20)
                    last_autonomous = now

                print("📨 [" + event_type + "]", json.dumps(extra)[:50] if extra else "")

                # ---- Teaching mode detection + goal + constraint extraction ----
                if event_type == "chat":
                    msg_lower = extra.get("message", "").lower()
                    if any(sig in msg_lower for sig in _TEACHING_SIGNALS):
                        _teaching_mode    = True
                        _teaching_context = extra.get("message", "")
                        print(f"📚 Teaching mode activated: {_teaching_context}")
                    elif _teaching_mode and is_james(extra.get("sender", "")):
                        observe_inventory(game_state, _teaching_context)
                        _teaching_mode = False

                    if is_james(extra.get("sender", "")):
                        msg = extra.get("message", "")

                        # Goal initialization — fires once per session on first goal signal
                        if active_goal is None:
                            new_goal = _try_initialize_goal(msg, game_state)
                            if new_goal:
                                active_goal = new_goal
                                print(f"[Goal] Initialized: {active_goal[:80]}...")

                        # Direction change — James is pivoting the plan
                        elif any(sig in msg_lower for sig in DIRECTION_CHANGE_SIGNALS) and active_goal:
                            active_goal = _update_goal(active_goal, f"James changed direction: {msg}", game_state)
                            print("[Goal] Updated — direction change")

                        # Constraint extraction
                        constraint = _try_extract_constraint(msg)
                        if constraint:
                            knowledge = load_mc_knowledge()
                            knowledge["james_constraints"].setdefault("behavior_rules", []).append(constraint)
                            save_mc_knowledge(knowledge)
                            print(f"[Constraint] Added: {constraint}")

                # ---- Goal update on death ----
                if event_type == "death" and active_goal:
                    active_goal = _update_goal(active_goal, "Hayeong died and respawned", game_state)
                    print("[Goal] Updated — death event")

                action = get_action(game_state, event_type, extra, last_actions,
                                    active_goal, _pending_outcome, knowledge)

                # ---- Suppress spammy AUTONOMOUS chat only ----
                if action.get("action") == "chat":
                    if event_type == "chat":
                        last_chat_time = now
                    elif now - last_chat_time < CHAT_COOLDOWN:
                        print("🔇 Autonomous chat suppressed (cooldown)")
                        action = {"action": "idle"}
                    else:
                        last_chat_time = now

                # ---- Skip idle (don't send to bot) ----
                if action.get("action") == "idle":
                    print("💤 Idle")
                    continue

                print("🤖 →", action)

                # Track recent actions to avoid repetition
                last_actions.append(action.get("action", ""))
                if len(last_actions) > 6:
                    last_actions.pop(0)

                # ---- Save to memory ----
                if event_type == "chat":
                    msg    = extra.get("message", "")
                    sender = extra.get("sender", "?")
                    if msg:
                        adjust_mood_by_context(msg, mood_state)
                        memory.append({"role": "user", "content": "[MC] " + real_name(sender) + ": " + msg})
                        remember("[MC] " + real_name(sender) + ": " + msg, category=CATEGORY_MINECRAFT, speaker="james")

                if action.get("action") == "chat":
                    mc_msg = "[MC] " + action.get("message", "")
                    # Print to terminal so James can see replies even outside game
                    print(f"\nHayeong [MC]: {action.get('message', '')}")
                    memory.append({"role": "AI", "content": mc_msg})
                    remember(mc_msg, category=CATEGORY_MINECRAFT, speaker="hayeong")
                    save_memory(memory)

                # ---- Snapshot before sending — outcome evaluated on next event ----
                _pending_outcome = {"action": action, "before": _snapshot(game_state)}

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
        clear_shared_state()
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