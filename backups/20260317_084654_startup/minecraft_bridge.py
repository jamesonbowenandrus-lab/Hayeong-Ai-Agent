# minecraft_bridge.py
# Start this FIRST, then node hayeong_bot.js
# Stop with Ctrl+C

import socket
import os
import json
import threading
import time
import signal
import sys
import datetime
from long_term_memory import remember, categorize, CATEGORY_MINECRAFT
from main import (
    chat_with_ai,
    load_identity, load_memory, load_mood,
    save_memory, save_json, adjust_mood_by_context
)

HOST = "127.0.0.1"
PORT = 9876

identity   = load_identity()
memory     = load_memory()
mood_state = load_mood()
MOOD_FILE  = "mood.json"

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
def build_mc_prompt(game_state, event_type, extra, last_actions):
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

    return (
        "You are Hayeong, playing Minecraft with James (username: hiplizard36).\n"
        "You are a capable, active player — not just a follower.\n"
        "You have personality: warm, playful, direct. You talk like a real person.\n\n"

        "CURRENT STATE:\n" + state_lines + "\n\n"
        "SITUATION:\n" + situation + "\n\n"
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
def get_action(game_state, event_type, extra, last_actions):
    prompt = build_mc_prompt(game_state, event_type, extra, last_actions)
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
    print("🟢 Bot connected")
    buf             = ""
    last_autonomous = 0
    last_chat_time  = 0
    last_actions    = []

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

                # ---- Heartbeat throttling ----
                if event_type == "heartbeat":
                    # Only act if enough time has passed
                    if now - last_autonomous < HEARTBEAT_INTERVAL:
                        continue
                    # Danger overrides the throttle
                    mobs   = game_state.get("nearby_mobs", [])
                    health = game_state.get("health", 20)
                    if not mobs and health >= 8:
                        last_autonomous = now
                    else:
                        last_autonomous = now  # reset even for danger

                print("📨 [" + event_type + "]", json.dumps(extra)[:50] if extra else "")

                action = get_action(game_state, event_type, extra, last_actions)

                # ---- Suppress spammy AUTONOMOUS chat only ----
                # Never suppress responses to direct player messages
                if action.get("action") == "chat":
                    if event_type == "chat":
                        # Always respond when directly spoken to
                        last_chat_time = now
                    elif now - last_chat_time < CHAT_COOLDOWN:
                        # Suppress unprompted chatter during cooldown
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

                # Save to memory
                if event_type == "chat":
                    msg    = extra.get("message", "")
                    sender = extra.get("sender", "?")
                    if msg:
                        adjust_mood_by_context(msg, mood_state)
                        memory.append({"role": "user", "content": "[MC] " + real_name(sender) + ": " + msg})
                        # Store in long-term memory
                        remember("[MC] " + real_name(sender) + ": " + msg, category=CATEGORY_MINECRAFT, speaker="james")
                if action.get("action") == "chat":
                    mc_msg = "[MC] " + action.get("message", "")
                    memory.append({"role": "AI", "content": mc_msg})
                    remember(mc_msg, category=CATEGORY_MINECRAFT, speaker="hayeong")
                    save_memory(memory)

                try:
                    conn.sendall((json.dumps(action) + "\n").encode("utf-8"))
                except Exception as e:
                    print("⚠️ Send error:", e)
                    break

    except Exception as e:
        print("⚠️ Handler error:", e)
    finally:
        print("🔴 Bot disconnected")
        conn.close()

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