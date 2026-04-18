# capabilities/minecraft_cap.py
# Launches Hayeong's Minecraft bot and observer on request.
# Shuts both down when Hayeong shuts down or James asks to stop.
#
# Does NOT start on startup — only launches when James asks to play.

from capability_loader import result
import threading
import subprocess
import sys
from pathlib import Path

ACTIONS = ["minecraft_start", "minecraft_stop", "minecraft_status"]

BASE_DIR       = Path(__file__).parent.parent
BOT_PATH       = BASE_DIR / "hayeong_bot.js"
_bridge_thread = None
_bot_process   = None
_mc_active     = False


def _start_bridge():
    from minecraft_bridge import start_server
    start_server()


def _start_bot():
    global _bot_process
    if not BOT_PATH.exists():
        print("⚠️  hayeong_bot.js not found")
        return False
    try:
        _bot_process = subprocess.Popen(
            ["node", str(BOT_PATH)],
            cwd=str(BASE_DIR),
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
        )
        print(f"   [Minecraft] Bot started (pid {_bot_process.pid})")
        return True
    except FileNotFoundError:
        print("⚠️  node not found — install Node.js")
        return False
    except Exception as e:
        print(f"⚠️  Bot launch error: {e}")
        return False


def _stop_all():
    global _bot_process, _mc_active
    _mc_active = False
    if _bot_process:
        try:
            _bot_process.terminate()
            _bot_process.wait(timeout=5)
        except Exception:
            pass
        _bot_process = None
    try:
        from minecraft_bridge import clear_shared_state
        clear_shared_state()
    except Exception:
        pass
    print("   [Minecraft] Bot and observer stopped")


def handle(action: str, user_input: str, context: dict) -> dict:
    global _bridge_thread, _mc_active

    if action == "minecraft_start":
        if _mc_active:
            return result(success=True,
                response="[MINECRAFT] Already running.")

        _bridge_thread = threading.Thread(target=_start_bridge, daemon=True)
        _bridge_thread.start()

        import time; time.sleep(0.5)   # let bridge bind port

        bot_ok     = _start_bot()
        _mc_active = bot_ok

        if bot_ok:
            return result(
                success=True,
                response=(
                    "[MINECRAFT STARTED]\n"
                    "Bridge listening. Bot connecting to server.\n"
                    "Tell James Minecraft is ready — meet him in-game. "
                    "Respond in text only (terminal + in-game chat). No voice."
                ),
            )
        return result(
            success=False,
            response="[MINECRAFT] Failed to start bot — check Node.js is installed.",
        )

    elif action == "minecraft_stop":
        _stop_all()
        return result(success=True,
            response="[MINECRAFT STOPPED] Bot and observer shut down.")

    elif action == "minecraft_status":
        status = "active" if _mc_active else "inactive"
        return result(success=True, response=f"[MINECRAFT STATUS] {status}")

    return result(success=False, response="Unknown minecraft action.")


def on_unload():
    """Called when Hayeong shuts down — clean up bot and observer."""
    _stop_all()
