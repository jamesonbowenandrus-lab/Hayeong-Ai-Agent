"""
Minecraft tool — connects Hayeong's bot to the server.
Returns a status string. Cannot crash main.
"""
import json
import socket
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from brain.config import (
    MINECRAFT_HOST, MINECRAFT_PORT, MINECRAFT_VERSION,
    BOT_JS_PATH, MINECRAFT_STATE_PATH, MINECRAFT_COMMAND_PATH,
)

BOT_DIR        = Path(__file__).parent
_STATE_PATH    = Path(MINECRAFT_STATE_PATH)
_COMMAND_PATH  = Path(MINECRAFT_COMMAND_PATH)


def _server_reachable(host: str, port: int, timeout: int = 3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def send_minecraft_command(command: str, params: dict = None) -> str:
    try:
        cmd = {
            "command":   command,
            "params":    params or {},
            "issued_at": datetime.now().isoformat(),
        }
        _COMMAND_PATH.write_text(json.dumps(cmd, indent=2), encoding="utf-8")
        return f"Command sent: {command}"
    except Exception as e:
        return f"Failed to send command: {e}"


def run(description: str, params: dict) -> str:
    # bot_update — read/write/restart the bot JS file
    if params.get("action_type") in ("read", "write", "backup", "restart"):
        try:
            import importlib.util
            _spec = importlib.util.spec_from_file_location(
                "bot_update_tool", Path(__file__).parent / "bot_update_tool.py"
            )
            _mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            return _mod.run(description, params)
        except Exception as e:
            return f"bot_update failed: {e}"

    # If a "command" key is present, send a command to the already-running bot
    if "command" in params:
        command = params["command"]
        cmd_params = {k: v for k, v in params.items() if k != "command"}
        return send_minecraft_command(command, cmd_params)

    host    = params.get("host",    MINECRAFT_HOST)
    port    = params.get("port",    MINECRAFT_PORT)
    version = params.get("version", MINECRAFT_VERSION)

    if not _server_reachable(str(host), int(port)):
        return f"Minecraft server not reachable at {host}:{port} — is the server running?"

    try:
        proc = subprocess.Popen(
            ["node", BOT_JS_PATH,
             str(host),
             str(port),
             "Hayeong",
             version],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(BOT_DIR),
        )

        def _pipe(p):
            for line in p.stdout:
                try:
                    text = line.decode('utf-8', errors='replace').rstrip()
                    print(f"[minecraft_bot] {text}")
                    if any(w in text for w in ('Error', 'error', 'ECONNRESET', 'Kicked', 'kicked')):
                        try:
                            _STATE_PATH.write_text(
                                json.dumps({
                                    "connected":  False,
                                    "last_event": f"error: {text}",
                                    "updated_at": datetime.now().isoformat(),
                                }, indent=2),
                                encoding="utf-8",
                            )
                        except Exception:
                            pass
                except Exception:
                    pass

        threading.Thread(target=_pipe, args=(proc,), daemon=True).start()
        return f"Minecraft bot started (PID {proc.pid}) connecting to {host}:{port}"
    except Exception as e:
        return f"Minecraft failed to start: {e}"
