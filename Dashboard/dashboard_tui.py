"""
dashboard.py — Hayeong's launch window.
Simple. One window. Three loops visible. Tools visible. Input box works.

Starts: Ollama 11435, 11436, then watchdog.
Monitors: LLM status, tool status from state/core.json
Shows: conversation, system log, tool status
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, RichLog, Static

BASE_DIR  = Path(__file__).parent          # H:\hayeong\
PYTHON    = BASE_DIR / ".venv" / "Scripts" / "python.exe"
CORE_FILE = BASE_DIR / "state" / "core.json"

# Ensure state package is importable from this process
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ── Model config ─────────────────────────────────────────────────────
MODELS = {
    "reasoning": {"port": 11435, "label": "Qwen 2.5 32b"},
}

# ── Shared queues — background threads write, Textual reads ──────────
_log_queue  = queue.Queue()   # system log lines
_conv_queue = queue.Queue()   # conversation updates (Hayeong responses)

# ── Status state (written by background threads, read by UI) ─────────
_llm_status  = {"reasoning": "🟡"}
_tool_status = {}

# ── Subprocess tracking ──────────────────────────────────────────────
_watchdog_proc = None


# ── Background: Ollama health polling ────────────────────────────────
def _poll_ollama():
    """Check all three Ollama ports every 15s. Never blocks the UI."""
    while True:
        for key, cfg in MODELS.items():
            port = cfg["port"]
            try:
                r = requests.get(f"http://localhost:{port}/api/ps", timeout=3)
                models = r.json().get("models", [])
                _llm_status[key] = "🟢" if models else "🟡"
            except Exception:
                _llm_status[key] = "🔴"
        time.sleep(15)


# ── Background: Core state polling ───────────────────────────────────
def _poll_core_state():
    """Read core.json every 2s for tool status and new Hayeong responses."""
    last_output = ""
    while True:
        try:
            if CORE_FILE.exists():
                state = json.loads(CORE_FILE.read_text(encoding="utf-8"))

                tool_st = state.get("what_happened", {}).get("tool_status", {})
                for tool, status in tool_st.items():
                    _tool_status[tool] = status

                output = state.get("hayeong_output", {}).get("message", "")
                if output and output != last_output:
                    last_output = output
                    _conv_queue.put(f"Hayeong: {output}")

        except Exception:
            pass
        time.sleep(2)


# ── Background: Subprocess pipe reader ───────────────────────────────
def _pipe_reader(proc, prefix=""):
    """Read subprocess stdout in a dedicated thread. Puts lines in log queue."""
    try:
        for line in proc.stdout:
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                _log_queue.put(f"{prefix}{text}")
    except Exception:
        pass


# ── Startup: Launch Ollama instances ─────────────────────────────────
def _ensure_ollama(port: int, bat_name: str) -> bool:
    """Start Ollama on port if not already running."""
    try:
        requests.get(f"http://localhost:{port}/", timeout=2)
        _log_queue.put(f"[startup] Ollama :{port} already running")
        return True
    except Exception:
        pass

    bat_path = BASE_DIR / "batFiles" / bat_name
    if not bat_path.exists():
        _log_queue.put(f"[startup] ⚠️ Bat file not found: {bat_path}")
        return False

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["OLLAMA_KEEP_ALIVE"] = "-1"

    subprocess.Popen(
        [str(bat_path)],
        shell=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        env=env,
    )

    _log_queue.put(f"[startup] Starting Ollama :{port}...")
    for _ in range(30):
        time.sleep(2)
        try:
            requests.get(f"http://localhost:{port}/", timeout=2)
            _log_queue.put(f"[startup] ✅ Ollama :{port} ready")
            return True
        except Exception:
            pass

    _log_queue.put(f"[startup] ❌ Ollama :{port} failed to start")
    return False


def _start_watchdog():
    global _watchdog_proc
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    watchdog_path = BASE_DIR / "watchdog.py"
    _watchdog_proc = subprocess.Popen(
        [str(PYTHON), str(watchdog_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(BASE_DIR),
        env=env,
    )
    threading.Thread(
        target=_pipe_reader, args=(_watchdog_proc,), daemon=True
    ).start()
    _log_queue.put("[startup] Watchdog started.")


def _startup_sequence():
    """Run in a background thread — starts Ollama (if bat configured) then watchdog."""
    _log_queue.put("[startup] Starting Hayeong...")
    for key, cfg in MODELS.items():
        if "bat" in cfg:
            _ensure_ollama(cfg["port"], cfg["bat"])
        else:
            _log_queue.put(f"[startup] Skipping Ollama startup for :{cfg['port']} — use bat file to start manually")
    _start_watchdog()
    _log_queue.put("[startup] ✅ Hayeong is ready.")


# ── Textual App ───────────────────────────────────────────────────────
class HayeongDashboard(App):
    CSS = """
    #status_bar {
        height: 1;
        background: $panel;
        padding: 0 1;
    }
    #conversation {
        width: 55%;
        border: solid $primary;
    }
    #right_panel {
        width: 45%;
    }
    #tool_status {
        height: 9;
        border: solid $primary;
        padding: 0 1;
    }
    #system_log {
        border: solid $primary;
    }
    #help_bar {
        height: 1;
        background: $panel;
        padding: 0 1;
        color: $text-muted;
    }
    #input_bar {
        height: 3;
        padding: 0 1;
    }
    #msg_input {
        width: 85%;
    }
    #send_btn {
        width: 15%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="status_bar")
        with Horizontal():
            yield RichLog(id="conversation", highlight=True, markup=True)
            with Vertical(id="right_panel"):
                yield Static(
                    "▸ ACTIVE TOOLS\n"
                    "  ⚪ Minecraft    idle\n"
                    "  ⚪ Voice        idle\n"
                    "  ⚪ Email        idle\n"
                    "  ⚪ Vision       idle",
                    id="tool_status",
                )
                yield RichLog(id="system_log", highlight=True, markup=True)
        yield Static("[L] Copy log   [Q] Quit", id="help_bar")
        with Horizontal(id="input_bar"):
            yield Input(placeholder="Type a message...", id="msg_input")
            yield Button("Send", id="send_btn")

    def on_mount(self):
        self._last_log_lines = []

        # Background threads — all blocking work happens here, not in the event loop
        threading.Thread(target=_poll_ollama,      daemon=True).start()
        threading.Thread(target=_poll_core_state,  daemon=True).start()
        threading.Thread(target=_startup_sequence, daemon=True).start()

        # Textual timers only drain queues and refresh labels — never block
        self.set_interval(1.0, self._drain_queues)
        self.set_interval(5.0, self._update_status_bar)
        self.set_interval(5.0, self._update_tool_panel)

    def _drain_queues(self):
        """Drain log and conversation queues into UI. Called every 0.1s."""
        log_widget  = self.query_one("#system_log",  RichLog)
        conv_widget = self.query_one("#conversation", RichLog)

        for _ in range(20):
            try:
                line = _log_queue.get_nowait()
                log_widget.write(line)
                self._last_log_lines.append(line)
                if len(self._last_log_lines) > 200:
                    self._last_log_lines.pop(0)
            except queue.Empty:
                break

        for _ in range(5):
            try:
                msg = _conv_queue.get_nowait()
                conv_widget.write(msg)
            except queue.Empty:
                break

    def _update_status_bar(self):
        """Update LLM status dot. Called every 5s."""
        bar = self.query_one("#status_bar", Static)
        def dot(key):
            s = _llm_status.get(key, "..")
            return {"🟢": "[OK]", "🟡": "[..]", "🔴": "[!!]"}.get(s, "[..]")
        bar.update(f"{dot('reasoning')} Presence LLM (Qwen 2.5 32b — port 11435)")

    def _update_tool_panel(self):
        """Update tool status panel. Called every 5s."""
        panel = self.query_one("#tool_status", Static)
        if not _tool_status:
            panel.update("▸ ACTIVE TOOLS\n  (none)")
            return
        lines = ["▸ ACTIVE TOOLS"]
        for tool, status in _tool_status.items():
            if status not in ("idle", ""):
                tag = "[ON]" if status in ("connected", "active") else "[!!]"
                lines.append(f"  {tag} {tool.capitalize():<12}{status}")
        if len(lines) == 1:
            lines.append("  (none active)")
        panel.update("\n".join(lines))

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "send_btn":
            self._send_message()

    def on_input_submitted(self, event: Input.Submitted):
        self._send_message()

    def _send_message(self):
        """Write James's message directly to core.json james_input section."""
        input_widget = self.query_one("#msg_input", Input)
        conv_widget  = self.query_one("#conversation", RichLog)

        text = input_widget.value.strip()
        if not text:
            return

        conv_widget.write(f"You: {text}")
        input_widget.value = ""

        try:
            from state.core_manager import write_section
            write_section("james_input", {
                "message":     text,
                "received_at": datetime.now().isoformat(),
            })
        except Exception as e:
            _log_queue.put(f"[input] Failed to write message: {e}")

    def on_key(self, event):
        if event.key == "q":
            self.exit()
        elif event.key == "l":
            self._copy_log()

    def _copy_log(self):
        try:
            import pyperclip
            pyperclip.copy("\n".join(self._last_log_lines[-50:]))
            self.notify("Log copied to clipboard.", severity="information")
        except Exception as e:
            self.notify(f"Copy failed: {e}", severity="warning")

    def on_unmount(self):
        if _watchdog_proc:
            _watchdog_proc.terminate()


# ── Entry Point ───────────────────────────────────────────────────────
if __name__ == "__main__":
    app = HayeongDashboard()
    app.run()
