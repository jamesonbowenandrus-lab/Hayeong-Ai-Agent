"""
dashboard_server.py — Hayeong's browser dashboard.

Runs a local web server on http://localhost:8080
Serves a single HTML page — Hayeong's dashboard.
Reads from and writes to state/core.json.
Nothing touches the internet. All local.

Start with: python dashboard_server.py
Then open:  http://localhost:8080
"""

import json
import threading
import time
import requests
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

BASE_DIR  = Path(__file__).parent.parent   # H:\hayeong\
CORE_FILE = BASE_DIR / "Brain" / "state" / "core.json"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Startup log ──────────────────────────────────────────────────────

_startup_log = []


def _log(msg: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    _startup_log.append(line)
    print(line)
    if len(_startup_log) > 500:
        _startup_log.pop(0)


def _startup_sequence():
    _log("Dashboard started on http://localhost:8080")
    try:
        requests.get("http://localhost:11435/", timeout=2)
        _log("Presence LLM (port 11435) is running.")
    except Exception:
        _log("WARNING: Presence LLM not detected on port 11435.")


# ── API Endpoints ────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/state")
def get_state():
    """Return current core.json state for the dashboard to display."""
    try:
        state        = json.loads(CORE_FILE.read_text(encoding="utf-8"))
        presence_out = state.get("presence_output", {})
        last_task    = state.get("last_task", {})

        # Build a synthetic tool_status dict from last_task
        tool_status = {}
        if last_task.get("tool"):
            tool_status[last_task["tool"]] = last_task.get("status", "idle")

        voice_input  = state.get("voice_input", {})
        listen_mode  = voice_input.get("listening_mode", "vad")

        return JSONResponse({
            "llm_status":   _get_llm_status(),
            "tool_status":  tool_status,
            "hayeong_says": presence_out.get("for_james", ""),
            "sent_at":      presence_out.get("expressed_at", ""),
            "listen_mode":  listen_mode,
            "log":          _startup_log[-100:],
        })
    except Exception as e:
        return JSONResponse({"error": str(e)})


@app.post("/api/send")
async def send_message(request_data: dict):
    """Write James's message into situation.what_james_said."""
    message = request_data.get("message", "").strip()
    if not message:
        return JSONResponse({"ok": False, "error": "empty message"})
    try:
        from brain.state.core_manager import write_section
        write_section("situation", {
            "what_james_said": message,
            "said_at":         datetime.now().isoformat(),
        })
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


def _get_llm_status() -> dict:
    """Check which LLMs are loaded."""
    try:
        r = requests.get("http://localhost:11435/api/ps", timeout=2)
        models = r.json().get("models", [])
        return {"presence": "loaded" if models else "empty"}
    except Exception:
        return {"presence": "offline"}


# ── HTML Page ────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hayeong</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Consolas', 'Courier New', monospace;
    background: #0d1117;
    color: #c9d1d9;
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* Status bar */
  #status-bar {
    background: #161b22;
    border-bottom: 1px solid #30363d;
    padding: 6px 16px;
    display: flex;
    gap: 24px;
    align-items: center;
    font-size: 13px;
    flex-shrink: 0;
  }
  .llm-dot { display: flex; align-items: center; gap: 6px; }
  .dot {
    width: 10px; height: 10px;
    border-radius: 50%;
    background: #484f58;
  }
  .dot.loaded  { background: #3fb950; }
  .dot.empty   { background: #d29922; }
  .dot.offline { background: #f85149; }

  /* Main layout */
  #main {
    display: flex;
    flex: 1;
    overflow: hidden;
  }

  /* Conversation pane */
  #conversation {
    flex: 55%;
    display: flex;
    flex-direction: column;
    border-right: 1px solid #30363d;
  }
  #conv-log {
    flex: 1;
    overflow-y: auto;
    padding: 12px 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .msg { line-height: 1.5; }
  .msg.james   { color: #79c0ff; }
  .msg.james::before   { content: "You: ";    color: #58a6ff; font-weight: bold; }
  .msg.hayeong { color: #c9d1d9; }
  .msg.hayeong::before { content: "Hayeong: "; color: #3fb950; font-weight: bold; }

  /* Input bar */
  #input-bar {
    border-top: 1px solid #30363d;
    padding: 8px 12px;
    display: flex;
    gap: 8px;
    flex-shrink: 0;
  }
  #msg-input {
    flex: 1;
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    color: #c9d1d9;
    font-family: inherit;
    font-size: 14px;
    padding: 8px 12px;
    outline: none;
  }
  #msg-input:focus { border-color: #58a6ff; }
  #send-btn {
    background: #238636;
    border: none;
    border-radius: 6px;
    color: white;
    cursor: pointer;
    font-family: inherit;
    font-size: 14px;
    padding: 8px 20px;
  }
  #send-btn:hover { background: #2ea043; }

  /* Right panel */
  #right-panel {
    flex: 45%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* Tool status */
  #tool-status {
    border-bottom: 1px solid #30363d;
    padding: 10px 16px;
    flex-shrink: 0;
  }
  #tool-status h3 {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #8b949e;
    margin-bottom: 8px;
  }
  .tool-row {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    padding: 2px 0;
  }
  .tool-name { color: #8b949e; width: 80px; }
  .tool-val  { color: #3fb950; }
  .tool-val.idle    { color: #484f58; }
  .tool-val.failed  { color: #f85149; }

  /* System log */
  #system-log {
    flex: 1;
    overflow-y: auto;
    padding: 10px 16px;
  }
  #system-log h3 {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #8b949e;
    margin-bottom: 8px;
    position: sticky;
    top: 0;
    background: #0d1117;
    padding-bottom: 4px;
  }
  .log-line {
    font-size: 12px;
    color: #8b949e;
    line-height: 1.4;
    word-break: break-all;
  }
  .log-line.ok   { color: #3fb950; }
  .log-line.err  { color: #f85149; }
  .log-line.warn { color: #d29922; }

  /* Scrollbar */
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }
</style>
</head>
<body>

<div id="status-bar">
  <div class="llm-dot">
    <div class="dot" id="dot-presence"></div>
    <span>Presence (qwen2.5:32b)</span>
  </div>
  <div id="listen-mode" style="margin-left:auto;font-size:13px;color:#8b949e;">🎙 VAD</div>
</div>

<div id="main">
  <div id="conversation">
    <div id="conv-log"></div>
    <div id="input-bar">
      <input id="msg-input" type="text" placeholder="Type a message and press Enter..." autofocus>
      <button id="send-btn">Send</button>
    </div>
  </div>

  <div id="right-panel">
    <div id="tool-status">
      <h3>Active Tools</h3>
      <div id="tool-rows"><div style="color:#484f58;font-size:13px;">(none active)</div></div>
    </div>
    <div id="system-log">
      <h3>System Log</h3>
      <div id="log-lines"></div>
    </div>
  </div>
</div>

<script>
  const convLog    = document.getElementById('conv-log');
  const logLines   = document.getElementById('log-lines');
  const toolRows   = document.getElementById('tool-rows');
  const msgInput   = document.getElementById('msg-input');
  const sendBtn    = document.getElementById('send-btn');
  const listenMode = document.getElementById('listen-mode');

  let lastHayeongMsg = "";
  let lastLogCount   = 0;

  // ── Send message ──────────────────────────────────────────────────
  async function sendMessage() {
    const text = msgInput.value.trim();
    if (!text) return;

    addConvMsg('james', text);
    msgInput.value = '';

    try {
      await fetch('/api/send', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: text}),
      });
    } catch(e) {
      addLogLine('Send failed: ' + e, 'err');
    }
  }

  sendBtn.addEventListener('click', sendMessage);
  msgInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') sendMessage();
  });

  // ── Add conversation message ──────────────────────────────────────
  function addConvMsg(who, text) {
    const div = document.createElement('div');
    div.className = 'msg ' + who;
    div.textContent = text;
    convLog.appendChild(div);
    convLog.scrollTop = convLog.scrollHeight;
  }

  // ── Add log line ──────────────────────────────────────────────────
  function addLogLine(text, cls='') {
    const div = document.createElement('div');
    div.className = 'log-line ' + cls;
    div.textContent = text;
    logLines.appendChild(div);
    logLines.scrollTop = logLines.scrollHeight;
    while (logLines.children.length > 300) {
      logLines.removeChild(logLines.firstChild);
    }
  }

  // ── Update LLM status dots ────────────────────────────────────────
  function updateDots(llmStatus) {
    for (const [key, status] of Object.entries(llmStatus)) {
      const dot = document.getElementById('dot-' + key);
      if (dot) dot.className = 'dot ' + status;
    }
  }

  // ── Update tool status panel ──────────────────────────────────────
  function updateTools(toolStatus) {
    const active = Object.entries(toolStatus).filter(
      ([_, v]) => v && v !== 'idle' && v !== 'none' && v !== ''
    );

    if (active.length === 0) {
      toolRows.innerHTML = '<div style="color:#484f58;font-size:13px;">(none active)</div>';
      return;
    }

    toolRows.innerHTML = active.map(([tool, status]) => {
      const cls = status === 'failed' ? 'failed' : '';
      return `<div class="tool-row">
        <span class="tool-name">${tool}</span>
        <span class="tool-val ${cls}">${status}</span>
      </div>`;
    }).join('');
  }

  // ── Poll state from server ────────────────────────────────────────
  async function pollState() {
    try {
      const r = await fetch('/api/state');
      const data = await r.json();

      if (data.llm_status)  updateDots(data.llm_status);
      if (data.tool_status) updateTools(data.tool_status);
      if (data.listen_mode !== undefined) {
        const icons = { vad: '🎙 VAD', ptt: '⌨ PTT', muted: '🔇 MUTED' };
        listenMode.textContent = icons[data.listen_mode] || data.listen_mode;
        listenMode.style.color = data.listen_mode === 'muted' ? '#f85149'
                                : data.listen_mode === 'ptt'  ? '#d29922'
                                : '#3fb950';
      }

      if (data.hayeong_says && data.hayeong_says !== lastHayeongMsg) {
        lastHayeongMsg = data.hayeong_says;
        addConvMsg('hayeong', data.hayeong_says);
      }

      if (data.log && data.log.length > lastLogCount) {
        const newLines = data.log.slice(lastLogCount);
        for (const line of newLines) {
          const cls = line.includes('ready') || line.includes('running') ? 'ok'
                    : line.includes('ERROR') || line.includes('Error')   ? 'err'
                    : line.includes('WARNING') ? 'warn' : '';
          addLogLine(line, cls);
        }
        lastLogCount = data.log.length;
      }

    } catch(e) {
      // Server not ready yet — silent fail
    }
  }

  setInterval(pollState, 1000);
  pollState();
</script>
</body>
</html>
"""


# ── Entry Point ──────────────────────────────────────────────────────
if __name__ == "__main__":
    threading.Thread(target=_startup_sequence, daemon=True).start()

    def _open_browser():
        time.sleep(2)
        import webbrowser
        webbrowser.open("http://localhost:8080")
    threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="warning")
