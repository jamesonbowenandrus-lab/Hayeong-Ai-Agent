"""
Minecraft tool — connects Hayeong's bot to the server.
Returns a status string. Cannot crash main.
"""
import subprocess
import threading
from pathlib import Path

BOT_DIR = Path(__file__).parent


def run(description: str, params: dict) -> str:
    host    = params.get("host",    "localhost")
    port    = params.get("port",    25565)
    version = params.get("version", "1.21.4")

    try:
        proc = subprocess.Popen(
            ["node", str(BOT_DIR / "hayeong_bot.js"),
             "--host", str(host),
             "--port", str(port),
             "--version", version],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(BOT_DIR),
        )

        def _pipe(p):
            for line in p.stdout:
                try:
                    print(f"[minecraft_bot] {line.decode('utf-8', errors='replace').rstrip()}")
                except Exception:
                    pass

        threading.Thread(target=_pipe, args=(proc,), daemon=True).start()
        return f"Minecraft bot started (PID {proc.pid}) connecting to {host}:{port}"
    except Exception as e:
        return f"Minecraft failed to start: {e}"
