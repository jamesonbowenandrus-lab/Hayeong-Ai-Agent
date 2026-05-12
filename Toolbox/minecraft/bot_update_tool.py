"""
bot_update_tool.py
Hayeong's ability to read, modify, and restart her own Minecraft bot code.

Tool contract:  run(description, params) -> str
Cannot crash main. Returns result or error string.

Params:
  action:   "read" | "write" | "restart" | "backup"
  content:  (write) full new file content as string
  section:  (read) "hunger" | "pathfinding" | "combat" | "behavior" | "food_score" | "all"
"""

import subprocess
import shutil
from pathlib import Path
from datetime import datetime

BOT_FILE   = Path(__file__).parent / "hayeong_bot.js"
BACKUP_DIR = Path(__file__).parent.parent.parent / "backups" / "bot_versions"


def run(description: str, params: dict) -> str:
    action = params.get("action", "read")

    if action == "read":
        return _read_bot(params.get("section", "all"))
    elif action == "write":
        content = params.get("content", "")
        if not content:
            return "ERROR: No content provided for write"
        return _write_bot(content, description)
    elif action == "backup":
        return _backup_bot()
    elif action == "restart":
        return _restart_bot()
    else:
        return f"ERROR: Unknown action '{action}'. Use: read, write, backup, restart"


def _read_bot(section: str) -> str:
    try:
        content = BOT_FILE.read_text(encoding="utf-8")
        if section == "all":
            return content

        section_markers = {
            "hunger":      ("startHungerLoop", "// -------------------------\n// Safety"),
            "pathfinding": ("movements.canDig",  "bot.pathfinder.setMovements"),
            "combat":      ("startBehaviorLoop", "// -------------------------\n// Hunger"),
            "behavior":    ("currentBehavior",   "// -------------------------\n// Mob"),
            "food_score":  ("foodScore",         "function autoEquipBestArmor"),
        }

        if section in section_markers:
            start_kw, end_kw = section_markers[section]
            start_idx = content.find(start_kw)
            end_idx   = content.find(end_kw, start_idx + 1) if start_idx >= 0 else -1
            if start_idx >= 0:
                return content[start_idx : end_idx if end_idx > start_idx else start_idx + 3000]
            return f"Section '{section}' not found in bot file"

        return content[:5000]
    except Exception as e:
        return f"ERROR reading bot file: {e}"


def _backup_bot() -> str:
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = BACKUP_DIR / f"hayeong_bot_{ts}.js"
        shutil.copy2(BOT_FILE, dest)
        return f"Backup created: {dest.name}"
    except Exception as e:
        return f"ERROR creating backup: {e}"


def _write_bot(content: str, description: str) -> str:
    # Safety check — must contain identifiers that prove it's a valid bot file
    required = ["mineflayer", "pathfinder", "executeCommand", "writeState", "startBehaviorLoop"]
    missing  = [r for r in required if r not in content]
    if missing:
        return (
            f"ERROR: Content is missing required bot identifiers: {missing}. "
            "Write refused to protect bot integrity."
        )

    backup_result = _backup_bot()
    if "ERROR" in backup_result:
        return f"Write aborted — backup failed: {backup_result}"

    try:
        BOT_FILE.write_text(content, encoding="utf-8")
        return f"Bot file updated. {backup_result}. Restart the bot to apply changes."
    except Exception as e:
        return f"ERROR writing bot file: {e}"


def _restart_bot() -> str:
    try:
        # Kill any node.exe process running hayeong_bot.js
        subprocess.run(
            ["taskkill", "/F", "/FI", "WINDOWTITLE eq node*hayeong_bot*"],
            capture_output=True, text=True,
        )
        subprocess.run(
            ["taskkill", "/F", "/IM", "node.exe"],
            capture_output=True, text=True,
        )
        return "Bot process stopped. The Minecraft bridge will restart it automatically."
    except Exception as e:
        return f"ERROR restarting bot: {e}"
