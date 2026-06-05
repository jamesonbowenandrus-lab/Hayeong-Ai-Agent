"""
Brain/config.py — Hayeong's central configuration.

All paths, ports, model names, and API keys live here.
When something changes, change it here. Everything else imports from here.

Usage in any file:
    from Brain.config import REASON_URL, REASON_MODEL, ...
"""

import os
from pathlib import Path

# ── Base paths ─────────────────────────────────────────────────────────────
ROOT_DIR        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAIN_DIR       = os.path.join(ROOT_DIR, "Brain")
TOOLBOX_DIR     = os.path.join(ROOT_DIR, "Toolbox")
MEMORY_DIR      = os.path.join(ROOT_DIR, "Memory")
LOGS_DIR        = os.path.join(ROOT_DIR, "Logs")
TOOLS_DIR       = os.path.join(ROOT_DIR, "Tools")
OUTPUTS_DIR     = os.path.join(ROOT_DIR, "Logs", "outputs")
STATE_FILE      = os.path.join(ROOT_DIR, "Brain", "state", "core.json")
IDENTITY_FILE   = os.path.join(ROOT_DIR, "Brain", "identity.json")
CONV_LOG_DIR    = os.path.join(ROOT_DIR, "Logs", "conversations")

JAMES_INTENTIONS_PATH = Path(ROOT_DIR) / "Memory" / "james" / "current_intentions.md"

# ── Ollama model configuration ─────────────────────────────────────────────
PRESENCE_URL   = "http://localhost:11435/api/chat"
PRESENCE_MODEL = "qwen2.5:32b-instruct-q4_K_M"

# DeepSeek — specialist model, on-demand for code tasks (port 11436)
# Not active by default — spun up by api_caller tool when needed.
DEEPSEEK_URL   = "http://localhost:11436/api/chat"
DEEPSEEK_MODEL = "deepseek-r1:latest"

# ── Minecraft ──────────────────────────────────────────────────────────────
MINECRAFT_HOST       = "127.0.0.1"
MINECRAFT_PORT       = 25565
MINECRAFT_VERSION    = "1.21.4"
BOT_JS_PATH          = os.path.join(ROOT_DIR, "Toolbox", "minecraft", "hayeong_bot.js")
MINECRAFT_STATE_PATH   = os.path.join(ROOT_DIR, "toolbox", "minecraft", "state", "minecraft_state.json")
MINECRAFT_COMMAND_PATH = os.path.join(ROOT_DIR, "toolbox", "minecraft", "state", "minecraft_command.json")

# ── Blender ────────────────────────────────────────────────────────────────
BLENDER_PATH    = "H:/blender/blender.exe"
BLENDER_OUTPUT  = os.path.join(OUTPUTS_DIR, "blender")
BLENDER_SCRIPTS = os.path.join(TOOLBOX_DIR, "blender", "scripts")

# ── ComfyUI ────────────────────────────────────────────────────────────────
COMFYUI_URL           = "http://127.0.0.1:8188"
COMFYUI_TIMEOUT       = 120
COMFYUI_POLL_INTERVAL = 2
COMFYUI_OUTPUT_DIR    = os.path.join(OUTPUTS_DIR, "comfyui")
COMFYUI_WORKFLOW_DIR  = os.path.join(TOOLBOX_DIR, "comfyui", "workflows")

# ── FFmpeg ─────────────────────────────────────────────────────────────────
FFMPEG_PATH    = "ffmpeg"                           # assumes ffmpeg is on system PATH
# FFMPEG_PATH  = "H:/ffmpeg/bin/ffmpeg.exe"         # uncomment if not on PATH
FFMPEG_OUTPUT  = os.path.join(OUTPUTS_DIR, "video")

# ── Memory system ──────────────────────────────────────────────────────────
MEMORY_MIN_RELEVANCE    = 0.35   # below this score, memories not returned
MEMORY_MAX_PER_QUERY    = 5      # max memories injected per reasoning cycle
DECAY_RATE_MEM          = 0.05   # importance lost per 7-day idle period
PRUNE_THRESHOLD         = 0.10   # importance floor before pruning
PRUNE_MIN_AGE_DAYS      = 30     # minimum age before a memory can be pruned
MAX_COLLECTION_SIZE     = 10000  # force-prune threshold per collection
CONSOLIDATION_THRESHOLD = 0.85   # similarity needed to consolidate memories
CONSOLIDATION_MIN_SIZE  = 4      # minimum cluster size to consolidate
WORKING_MEMORY_EXPIRE   = 14     # days before working memory expires

# ── Database ───────────────────────────────────────────────────────────────
# PostgreSQL — primary database
POSTGRES_HOST     = "localhost"
POSTGRES_PORT     = 5432
POSTGRES_USER     = "postgres"
POSTGRES_PASSWORD = os.environ.get("HAYEONG_PG_PASSWORD", "")
POSTGRES_DB       = "hayeong"
POSTGRES_BIN      = "H:/Postgres/bin"

# Legacy aliases — kept for backward compatibility with older imports
DB_HOST     = POSTGRES_HOST
DB_PORT     = POSTGRES_PORT
DB_USER     = POSTGRES_USER
DB_PASSWORD = POSTGRES_PASSWORD
DB_NAME     = POSTGRES_DB

# SQLite fallback — always on H: drive
SQLITE_DIR        = "H:/Databases/sqlite"
SQLITE_DEFAULT_DB = "H:/Databases/sqlite/hayeong.db"

# Where Postgres stores its data (documentation/reference — configured in Postgres itself)
POSTGRES_DATA_DIR = "H:/Databases/postgres/data/"

# ── Self-review ────────────────────────────────────────────────────────────
SELF_REVIEW_ENABLED = True   # second LLM pass to verify response quality; set False to reduce latency

# ── Ambient presence ───────────────────────────────────────────────────────────
AMBIENT_PLUGIN_INTERVAL_SECONDS          = 2    # matches other plugin heartbeats
AMBIENT_JAMES_ABSENT_THRESHOLD_MINUTES   = 15   # minutes before James is considered absent
AMBIENT_UNPROMPTED_THRESHOLD_MINUTES     = 20   # minutes absent before unprompted initiation is possible
AMBIENT_MAX_INNER_NOTES                  = 10   # max queued thoughts before oldest drops
AMBIENT_UNPROMPTED_COOLDOWN_MINUTES      = 30   # minimum gap between unprompted messages

# ── API keys ───────────────────────────────────────────────────────────────
EMAIL_ADDRESS   = ""
EMAIL_PASSWORD  = ""

SESSION_LOG_DB                = os.path.join(BRAIN_DIR, "session_log.db")

# ── Cognitive tick configuration ────────────────────────────────────────────
INNER_AGENDA_PATH             = os.path.join(BRAIN_DIR, "inner_agenda.json")
TICK_IDLE_THRESHOLD_MINUTES   = 5
MINIMUM_TICK_INTERVAL_MINUTES = 5
TICK_SLEEP_SECONDS            = 60
TICK_MAX_HISTORY_EXCHANGES    = 5
