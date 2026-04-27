"""
dashboard.py — Hayeong unified launch dashboard.

Bootstrap layer (this script's job):
  1. Ensure Ollama on 11434 is running
  2. Ensure Ollama on 11435 is running
  3. Start watchdog (which starts the brain)

Hayeong's layer (monitored, never started here):
  - Communication LLM (model loaded in 11434)
  - Voice server
  - Discord bridge
  - Active capability scripts
"""

import asyncio
import json
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, RichLog, Static
from textual import work

try:
    from hayeong_state import push_input, pop_output, get_status, set_interface_status
    _STATE_OK = True
except ImportError:
    _STATE_OK = False

PYTHON       = Path(r"H:\hayeong\.venv\Scripts\python.exe")
BASE_DIR     = Path(r"H:\hayeong")
SHARED_STATE = BASE_DIR / "state" / "shared_state.json"

_UP   = {"running", "up", "ok", "healthy"}
_DOWN = {"down", "error", "crashed", "offline"}


def _dot(status: str) -> str:
    if status in _UP:
        return "[green]●[/green]"
    if status in _DOWN:
        return "[red]●[/red]"
    return "[yellow]●[/yellow]"


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


async def _http_ok(url: str, timeout: float = 3.0) -> bool:
    def _req():
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.status == 200
        except Exception:
            return False
    return await asyncio.get_running_loop().run_in_executor(None, _req)


async def _comm_llm_model_loaded() -> bool:
    """Return True if a model is currently loaded in the 11434 Ollama instance."""
    def _req():
        try:
            with urllib.request.urlopen(
                "http://localhost:11434/api/ps", timeout=3
            ) as r:
                if r.status == 200:
                    return len(json.loads(r.read()).get("models", [])) > 0
        except Exception:
            pass
        return False
    return await asyncio.get_running_loop().run_in_executor(None, _req)


def _read_active_scripts() -> list[str]:
    try:
        data = json.loads(SHARED_STATE.read_text(encoding="utf-8"))
        return data.get("system", {}).get("active_scripts", [])
    except Exception:
        return []


# ─────────────────────────────────────────────
# WIDGETS
# ─────────────────────────────────────────────

class ServiceLog(Vertical):
    """Labeled, scrollable log panel for one background service."""

    DEFAULT_CSS = """
    ServiceLog {
        height: auto;
        border-bottom: solid $panel-lighten-1;
    }
    ServiceLog .svc-header {
        height: 1;
        background: $boost;
        color: $text-muted;
        padding: 0 1;
    }
    ServiceLog RichLog {
        height: 8;
    }
    """

    def __init__(self, label: str, svc_id: str) -> None:
        super().__init__()
        self._label = label
        self.svc_id = svc_id

    def compose(self) -> ComposeResult:
        yield Static(f"▸ {self._label}", classes="svc-header")
        yield RichLog(
            highlight=False, markup=True, max_lines=200,
            id=f"svclog_{self.svc_id}",
        )

    def append(self, line: str) -> None:
        try:
            self.query_one(RichLog).write(line)
        except Exception:
            pass


# ─────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────

class HayeongDashboard(App):

    CSS = """
    Screen { layout: vertical; }

    .status-bar {
        height: 1;
        padding: 0 1;
    }

    #bootstrap-bar { background: $panel-darken-1; }
    #hayeong-bar   { background: $panel; }

    #split { height: 1fr; }

    #conv-pane {
        width: 55%;
        border-right: solid $panel-lighten-1;
    }

    #conv-header {
        height: 1;
        background: $panel-lighten-1;
        padding: 0 1;
    }

    #conv-log { height: 1fr; }

    #svc-pane {
        width: 45%;
        overflow-y: scroll;
    }

    #input-bar {
        height: 3;
        border-top: solid $panel-lighten-1;
        padding: 0 1;
        align: left middle;
    }

    #input-bar Input { width: 1fr; }
    #send-btn { width: 8; margin-left: 1; }
    """

    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self._watchdog_proc: asyncio.subprocess.Process | None = None

        # Bootstrap layer
        self._s_ollama_comm   = "unknown"   # Ollama process on 11434
        self._s_ollama_reason = "unknown"   # Ollama process on 11435
        self._s_watchdog      = "unknown"

        # Hayeong's layer (monitored, not started here)
        self._s_brain    = "unknown"   # brain_status from hayeong_state
        self._s_comm_llm = "unknown"   # model loaded in 11434
        self._s_voice    = "unknown"
        self._s_discord  = "unknown"

        self._shutting_down = False

    # ─────────────────────────────────────────
    # LAYOUT
    # ─────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static("", id="bootstrap-bar", classes="status-bar")
        yield Static("", id="hayeong-bar",   classes="status-bar")
        with Horizontal(id="split"):
            with Vertical(id="conv-pane"):
                yield Static("  HAYEONG", id="conv-header")
                yield RichLog(
                    highlight=False, markup=True, max_lines=500, id="conv-log"
                )
            with Vertical(id="svc-pane"):
                yield ServiceLog("WATCHDOG / BRAIN", "watchdog")
                yield ServiceLog("VOICE SERVER",     "voice")
                yield ServiceLog("DISCORD",          "discord")
                yield ServiceLog("ACTIVE SCRIPTS",   "scripts")
        with Horizontal(id="input-bar"):
            yield Input(placeholder="Message Hayeong...", id="msg-input")
            yield Button("Send", id="send-btn", variant="primary")

    # ─────────────────────────────────────────
    # STARTUP
    # ─────────────────────────────────────────

    def on_mount(self) -> None:
        self._startup()

    @work
    async def _startup(self) -> None:
        conv = self.query_one("#conv-log", RichLog)
        loop = asyncio.get_running_loop()

        if _STATE_OK:
            await loop.run_in_executor(
                None, lambda: set_interface_status("dashboard", "running"))
        else:
            conv.write(
                f"[{_ts()}] [red]WARNING: hayeong_state unavailable — "
                "cannot reach brain.[/red]"
            )

        self._refresh_bars()

        # 1. Ollama on port 11434
        await self._ensure_ollama(conv, loop, 11434,
                                   "ollama_communication.bat", "comm")

        # 2. Ollama on port 11435
        await self._ensure_ollama(conv, loop, 11435,
                                   "ollama_reasoning.bat", "reason")

        # 3. Start watchdog (watchdog starts brain)
        conv.write(f"[{_ts()}] Starting watchdog...")
        try:
            self._watchdog_proc = await asyncio.create_subprocess_exec(
                str(PYTHON), str(BASE_DIR / "watchdog.py"),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(BASE_DIR),
            )
            self._s_watchdog = "running"
            self._refresh_bars()
            self._pipe_watchdog(self._watchdog_proc)
            conv.write(f"[{_ts()}] [green]Watchdog started — brain launching.[/green]")
        except Exception as e:
            conv.write(f"[{_ts()}] [red]Watchdog failed: {e}[/red]")
            self._s_watchdog = "down"
            self._refresh_bars()

        conv.write(f"[{_ts()}] [dim]Dashboard ready — waiting for brain...[/dim]")

        # Start all monitoring workers
        self._poll_output()
        self._poll_hayeong_state()
        self._poll_ollama()
        self._poll_voice()
        self._poll_active_scripts()

    async def _ensure_ollama(
        self, conv: RichLog, loop, port: int, bat_name: str, which: str
    ) -> None:
        """Check if Ollama is running on port; start it via bat file if not, then wait."""
        url   = f"http://localhost:{port}/"
        attr  = f"_s_ollama_{which}"
        conv.write(f"[{_ts()}] Checking Ollama on port {port}...")

        if not await _http_ok(url):
            conv.write(f"[{_ts()}] Starting {bat_name}...")
            try:
                subprocess.Popen(
                    str(BASE_DIR / "batFiles" / bat_name),
                    shell=True,
                    cwd=str(BASE_DIR / "batFiles"),
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception as e:
                conv.write(
                    f"[{_ts()}] [yellow]Could not start {bat_name}: {e}[/yellow]")

        deadline = loop.time() + 60
        while loop.time() < deadline:
            ok = await _http_ok(url)
            setattr(self, attr, "running" if ok else "starting")
            self._refresh_bars()
            if ok:
                conv.write(f"[{_ts()}] [green]Ollama ({port}) ready.[/green]")
                return
            await asyncio.sleep(2)

        conv.write(f"[{_ts()}] [yellow]Ollama ({port}) timeout — continuing.[/yellow]")
        setattr(self, attr, "unknown")
        self._refresh_bars()

    # ─────────────────────────────────────────
    # BACKGROUND WORKERS
    # ─────────────────────────────────────────

    @work
    async def _pipe_watchdog(self, proc: asyncio.subprocess.Process) -> None:
        """Forward watchdog stdout (and inherited brain stdout) to the log panel."""
        svc_log = next(
            (w for w in self.query(ServiceLog) if w.svc_id == "watchdog"), None
        )
        if svc_log is None or proc.stdout is None:
            return
        try:
            async for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line:
                    svc_log.append(f"[{_ts()}] {line}")
        except Exception:
            pass
        self._s_watchdog = "down"
        self._refresh_bars()

    @work
    async def _poll_output(self) -> None:
        """Pop brain responses from hayeong_state output queue (every 150 ms)."""
        conv = self.query_one("#conv-log", RichLog)
        loop = asyncio.get_running_loop()
        while not self._shutting_down:
            await asyncio.sleep(0.15)
            if not _STATE_OK:
                continue
            resp = await loop.run_in_executor(None, pop_output)
            if resp:
                content = resp.get("content", "")
                conv.write(f"\n[bold cyan]Hayeong:[/bold cyan] {content}\n")

    @work
    async def _poll_hayeong_state(self) -> None:
        """Read brain + discord status from hayeong_state every 3 s."""
        loop = asyncio.get_running_loop()
        while not self._shutting_down:
            await asyncio.sleep(3)
            # Check if watchdog process exited
            if (self._watchdog_proc
                    and self._watchdog_proc.returncode is not None
                    and self._s_watchdog != "down"):
                self._s_watchdog = "down"
            if _STATE_OK:
                try:
                    s = await loop.run_in_executor(None, get_status)
                    self._s_brain   = s.get("brain", "unknown")
                    self._s_discord = s.get("interfaces", {}).get("discord", "unknown")
                except Exception:
                    pass
            self._refresh_bars()

    @work
    async def _poll_ollama(self) -> None:
        """Check Ollama health + comm LLM model load every 10 s."""
        while not self._shutting_down:
            await asyncio.sleep(10)
            comm_up   = await _http_ok("http://localhost:11434/")
            reason_up = await _http_ok("http://localhost:11435/")
            self._s_ollama_comm   = "running" if comm_up   else "down"
            self._s_ollama_reason = "running" if reason_up else "down"
            # Comm LLM (Hayeong's decision): is a model actually loaded?
            if comm_up:
                loaded = await _comm_llm_model_loaded()
                self._s_comm_llm = "running" if loaded else "starting"
            else:
                self._s_comm_llm = "down"
            self._refresh_bars()

    @work
    async def _poll_voice(self) -> None:
        """Poll voice server health every 10 s; write to voice log on change."""
        voice_log = next(
            (w for w in self.query(ServiceLog) if w.svc_id == "voice"), None
        )
        prev = "unknown"
        while not self._shutting_down:
            await asyncio.sleep(10)
            ok = await _http_ok("http://localhost:8765/health")
            new_status = "running" if ok else "down"
            if new_status != prev:
                self._s_voice = new_status
                self._refresh_bars()
                if voice_log:
                    msg = (
                        "[green]Healthy on port 8765.[/green]"
                        if ok else
                        "[red]Not responding.[/red]"
                    )
                    voice_log.append(f"[{_ts()}] {msg}")
                prev = new_status

    @work
    async def _poll_active_scripts(self) -> None:
        """Read active_scripts from shared_state.json every 5 s; write on change."""
        scripts_log = next(
            (w for w in self.query(ServiceLog) if w.svc_id == "scripts"), None
        )
        loop = asyncio.get_running_loop()
        prev: list[str] = []
        while not self._shutting_down:
            await asyncio.sleep(5)
            scripts = await loop.run_in_executor(None, _read_active_scripts)
            if scripts != prev:
                if scripts_log:
                    if scripts:
                        scripts_log.append(
                            f"[{_ts()}] Active: {', '.join(scripts)}")
                    else:
                        scripts_log.append(f"[{_ts()}] (none)")
                prev = scripts

    # ─────────────────────────────────────────
    # STATUS BARS
    # ─────────────────────────────────────────

    def _refresh_bars(self) -> None:
        """Render both status rows from cached state (non-blocking)."""
        try:
            bootstrap = self.query_one("#bootstrap-bar", Static)
            hayeong   = self.query_one("#hayeong-bar",   Static)
        except Exception:
            return

        bootstrap.update(
            f"  BOOTSTRAP:  "
            f"{_dot(self._s_ollama_comm)} Ollama(11434)   "
            f"{_dot(self._s_ollama_reason)} Ollama(11435)   "
            f"{_dot(self._s_watchdog)} Watchdog"
        )
        hayeong.update(
            f"  HAYEONG:    "
            f"{_dot(self._s_brain)} Reasoning LLM   "
            f"{_dot(self._s_comm_llm)} Comm LLM   "
            f"{_dot(self._s_voice)} Voice   "
            f"{_dot(self._s_discord)} Discord"
        )

    # ─────────────────────────────────────────
    # INPUT
    # ─────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-btn":
            self._send()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._send()

    def _send(self) -> None:
        inp  = self.query_one("#msg-input", Input)
        text = inp.value.strip()
        if not text:
            return
        inp.value = ""
        conv = self.query_one("#conv-log", RichLog)
        conv.write(f"\n[bold white]You:[/bold white] {text}\n")
        if not _STATE_OK:
            conv.write("[yellow]State unavailable — cannot reach brain.[/yellow]")
            return
        push_input(text, source="dashboard")
        conv.write("[dim]…[/dim]")

    # ─────────────────────────────────────────
    # SHUTDOWN
    # ─────────────────────────────────────────

    async def action_quit(self) -> None:
        await self._shutdown()
        self.exit()

    async def on_unmount(self) -> None:
        await self._shutdown()

    async def _shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        try:
            self.query_one("#conv-log", RichLog).write(
                f"\n[{_ts()}] Shutting down...")
        except Exception:
            pass
        if self._watchdog_proc and self._watchdog_proc.returncode is None:
            self._watchdog_proc.terminate()
        if _STATE_OK:
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: set_interface_status("dashboard", "down"))
            except Exception:
                pass


if __name__ == "__main__":
    HayeongDashboard().run()
