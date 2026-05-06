"""
Brain/config.py — Hayeong's central configuration.

All paths, ports, model names, and API keys live here.
When something changes, change it here. Everything else imports from here.

Usage in any file:
    from Brain.config import REASON_URL, REASON_MODEL, ...
"""

import os

# ── Base paths ─────────────────────────────────────────────────────────────
ROOT_DIR        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAIN_DIR       = os.path.join(ROOT_DIR, "Brain")
TOOLBOX_DIR     = os.path.join(ROOT_DIR, "Toolbox")
MEMORY_DIR      = os.path.join(ROOT_DIR, "Memory")
LOGS_DIR        = os.path.join(ROOT_DIR, "Logs")
OUTPUTS_DIR     = os.path.join(ROOT_DIR, "Logs", "outputs")
STATE_FILE      = os.path.join(ROOT_DIR, "Brain", "state", "core.json")
IDENTITY_FILE   = os.path.join(ROOT_DIR, "Brain", "identity.json")
CONV_LOG_DIR    = os.path.join(ROOT_DIR, "Logs", "conversations")

# ── Ollama model configuration ─────────────────────────────────────────────
COMM_URL        = "http://localhost:11434/api/chat"
COMM_MODEL      = "llama3.2:latest"

REASON_URL      = "http://localhost:11435/api/chat"
REASON_MODEL    = "qwen2.5:14b"

# ── Minecraft ──────────────────────────────────────────────────────────────
MINECRAFT_HOST    = "localhost"
MINECRAFT_PORT    = 25565
MINECRAFT_VERSION = "1.21.4"
BOT_JS_PATH       = os.path.join(ROOT_DIR, "Toolbox", "minecraft", "hayeong_bot.js")

# ── Blender ────────────────────────────────────────────────────────────────
BLENDER_PATH    = "H:/blender/blender.exe"
BLENDER_OUTPUT  = os.path.join(OUTPUTS_DIR, "blender")
BLENDER_SCRIPTS = os.path.join(TOOLBOX_DIR, "blender", "scripts")

# ── API keys ───────────────────────────────────────────────────────────────
DISCORD_TOKEN   = ""
EMAIL_ADDRESS   = ""
EMAIL_PASSWORD  = ""
