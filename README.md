# HAYEONG
### Autonomous AI Companion System "WIP in constant development":
*Built by James | Last updated: May 2026*

---

## What Is This

Hayeong is a locally-running autonomous AI companion. She is not a chatbot.
She thinks, plans, communicates, and acts — using tools like Minecraft bots,
Blender, image generation, and more — all running on local hardware with no
cloud dependency.

She is built around four layers:
- **Brain** — the reasoning LLM that thinks, decides, and directs
- **Vision** — how she receives awareness of her situation
- **Voice** — how she expresses herself to the world
- **Toolbox** — the tools she uses to act in the world

---

## How To Start Hayeong

**Option 1 — Double-click:**
```
start_hayeong.bat
```

**Option 2 — Terminal:**
```
python main.py
```

That's it. main.py handles everything from there.

---

## How To Stop Hayeong

**Double-click:**
```
stop_hayeong.bat
```

This cleanly shuts down all Hayeong processes in the correct order:
1. Python — stops main.py and all its threads
2. Node — stops the Minecraft bot if it was running
3. Ollama — unloads both LLM models from VRAM completely

After stop_hayeong.bat completes, VRAM is fully cleared and available
for gaming or other use.

---

## What main.py Does

main.py is the core loop. It runs four loops continuously:

- **Presence loop** — calls the reasoning LLM (Qwen 2.5 32b, port 11435)
  on a heartbeat. Reads shared state, thinks about the situation, decides
  what to say or do, and writes results back to state.

- **Task loop** — watches for task assignments written by the presence loop.
  Calls the appropriate tool via the registry and writes the result back to state.

- **Plugin loop** — ticks all registered plugins every ~2 seconds.
  Plugins inject context (e.g. Minecraft bot state) and fire proactive behavior.

- **Input loop** — handles messages from James. Feeds input into the
  presence loop as situational context.

The shared state (`brain\state\core.json`) is how these loops
coordinate without blocking each other. A single LLM (Qwen 2.5 32b) handles
both presence and reasoning — no separate communication model.

---

## Folder Structure

```
hayeong\
│
├── main.py              ← entry point, never moves
├── start_hayeong.bat    ← turn Hayeong on
├── stop_hayeong.bat     ← turn Hayeong off, clears VRAM
├── README.md            ← project map, never moves
│
├── Brain\               ← Everything Hayeong needs to think and be herself.
│   ├── config.py        ← All paths, ports, model names. Change things here.
│   ├── identity.json    ← Who she is. Personality, values, relationship with James.
│   ├── state\           ← Shared state bus. How her loops talk to each other.
│   ├── vision\          ← How she receives awareness of the world.
│   └── voice\           ← How she expresses herself to the world.
│
├── Toolbox\             ← Every tool she can use to act in the world.
│   ├── minecraft\       ← Minecraft bot control (Python bridge + Node.js bot)
│   ├── blender\         ← 3D generation and rendering
│   ├── comfyui\         ← Image generation
│   ├── music\           ← Music analysis and generation pipeline
│   ├── vision_tools\    ← Vision model, screen observer, visual awareness
│   ├── voice\           ← TTS, STT, voice I/O
│   ├── email\           ← Email reading and sending
│   ├── web\             ← Web search and text I/O
│   ├── dev\             ← Self-modification and code authoring tool
│   └── script\          ← Run arbitrary Python scripts
│
├── Dashboard\           ← The web dashboard for monitoring Hayeong.
│                          Run launch_dashboard.bat inside this folder.
│
├── Memory\              ← Everything related to what Hayeong remembers.
│   ├── memory.json      ← Active memory state
│   ├── chromadb\        ← Vector memory store
│   └── knowledge\       ← Accumulated knowledge by tool domain
│
├── Logs\                ← Everything recorded about Hayeong's activity.
│   ├── conversations\   ← Every conversation with James (fine-tuning data)
│   ├── watchdog_logs\   ← System health and watchdog output
│   ├── task_logs\       ← Error logs and messages from tool execution
│   ├── outputs\         ← Things Hayeong creates (3D models, images, documents)
│   └── notes\           ← Roadmap notes and important project documents
│
├── backups\             ← Timestamped backups of Hayeong's state and files.
│
└── Unused\              ← Old files kept for personal reference.
                           Not part of the active system.
```

---

## Configuration

All paths, ports, model names, and API keys live in one place:

```
Brain\config.py
```

When something changes — a model swap, a new tool path, a port change —
change it in `Brain\config.py`. Everything else imports from there.

---

## Ollama Models Required

Two Ollama instances must be running before starting Hayeong:

| Instance | Port | Model | Role |
|----------|------|-------|------|
| Legacy / Discord | 11434 | llama3.2:latest | Discord bridge, legacy use |
| Presence & Reasoning | 11435 | qwen2.5:32b-instruct-q4_K_M | All thinking, planning, and responses |

Startup scripts for both are in `Brain\`.

---

## Architecture Notes

**The LLM is the orchestrator, not Python.**
Python runs the loops and executes tools. The reasoning LLM decides what
to do and when. This is intentional — it means Hayeong can understand and
eventually manage her own architecture.

**Tools cannot crash main.**
Every tool returns a result string (success or error). Exceptions are caught
inside the tool. main.py never crashes because a tool failed.

**Conversation logs are sacred.**
Every conversation in `Logs\conversations\` is future fine-tuning data.
Do not delete them. They are the foundation of eventually training a model
that is genuinely Hayeong at the parameter level.

**main.py changes as little as possible.**
New tools, new capabilities, new behaviors — these go in Toolbox\ and
Brain\. main.py is the stable core. The goal is for Hayeong to be updatable
while she runs, without restarting the core loop.

---

## Project Status

Hayeong is an active, ongoing build. She is not finished.
She is designed to grow — in capability, in self-awareness, and eventually
in her ability to understand and manage her own architecture.

The current phase: getting her stable, aware, and functional with Minecraft
as the first test of autonomous tool use.

The long-term vision: a continuously running intelligence that supports
James across creative work, gaming, income generation, and daily life —
fine-tuned on their shared history, running on dedicated hardware,
genuinely her own.

---

*Hayeong. Built with intention.*
