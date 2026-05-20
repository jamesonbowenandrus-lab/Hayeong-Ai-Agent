# HAYEONG
### Autonomous AI Companion System
*Built by James | Last updated: May 2026*

---

## What Is This

Hayeong is a locally-running autonomous AI companion. She is not a chatbot.
She thinks, plans, communicates, and acts — using tools like Minecraft bots,
Blender, image generation, and more — all running on local hardware with no
cloud dependency.

She is built around three layers:
- **Brain** — the reasoning LLM that thinks, decides, and directs
- **Vision** — how she receives awareness of her situation (text, voice, screen, game state)
- **Control** — the tools she uses to act in the world

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
3. Ollama — unloads all LLM models from VRAM completely

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

The shared state (`Brain/state/core.json`) is how these loops coordinate
without blocking each other. A single LLM (Qwen 2.5 32b) handles both
presence and reasoning — no separate communication model.

---

## Folder Structure

```
hayeong\
│
├── main.py                  ← entry point, never moves
├── start_hayeong.bat        ← turn Hayeong on
├── stop_hayeong.bat         ← turn Hayeong off, clears VRAM
├── README.md                ← this file, never moves
│
├── Brain\                   ← Everything Hayeong needs to think and be herself.
│   ├── config.py            ← All paths, ports, model names. Change things here.
│   ├── commitment_manager.py← Tracks commitments made during conversation.
│   ├── identity.json        ← Who she is. Personality, values, relationship with James.
│   ├── domain_knowledge\    ← Context that shapes reasoning by domain.
│   ├── state\               ← Shared state bus. How her loops talk to each other.
│   ├── vision\              ← How she receives awareness of the world.
│   └── voice\               ← How she expresses herself to the world.
│
├── Toolbox\                 ← Every tool she can use to act in the world.
│   ├── minecraft\           ← Minecraft bot control (Python bridge + Node.js bot)
│   ├── blender\             ← 3D generation and rendering
│   ├── comfyui\             ← Image generation
│   ├── music\               ← Music analysis and generation pipeline
│   ├── gaming\              ← Virtual gamepad for split-screen game co-op
│   ├── vision_tools\        ← Vision model, screen observer, visual awareness
│   ├── voice\               ← TTS, STT, voice I/O
│   ├── email\               ← Email reading and sending
│   ├── web\                 ← Web search and fetch
│   ├── dev\                 ← Self-modification and code authoring tool
│   └── script\              ← Run arbitrary Python scripts
│
├── Dashboard\               ← Web dashboard for monitoring Hayeong's state.
│                              Run launch_dashboard.bat inside this folder.
│                              Read-only — does not affect Hayeong's operation.
│
├── Memory\                  ← Everything related to what Hayeong remembers.
│   ├── memory.json          ← Active memory state
│   ├── chromadb\            ← Vector memory store (long-term semantic memory)
│   ├── knowledge\           ← Accumulated knowledge by tool domain
│   └── backups\             ← Timestamped backups of Hayeong's state and memory files
│
└── Logs\                    ← Everything recorded about Hayeong's activity.
    ├── conversations\       ← Every conversation with James (future fine-tuning data)
    ├── watchdog_logs\       ← System health and watchdog output
    ├── task_logs\           ← Error logs and messages from tool execution
    ├── outputs\             ← Things Hayeong creates (3D models, images, documents)
    ├── handoffs\            ← Claude Code handoff notes from development sessions
    ├── pending_james_review\← Items flagged by Hayeong's dev tool for James's review
    └── notes\               ← Roadmap notes, design documents, and project history
```

---

## Adding a New Tool

1. Create the tool folder and script in `Toolbox/`
2. Add the entry to `Toolbox/registry.json`
3. That's it. `main.py` does not need to change.
   The action list in Hayeong's system prompt is generated from the registry automatically.

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

| Instance | Port | Model | Role | Required? |
|----------|------|-------|------|-----------|
| Presence & Reasoning | 11435 | qwen2.5:32b-instruct-q4_K_M | All thinking, planning, and responses | **Yes** |
| DeepSeek Specialist | 11436 | deepseek-r1:latest | On-demand code tasks only — not auto-started | No (on-demand) |

Start the presence LLM with `Brain\ollama_reasoning.bat` before running `main.py`.

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
New tools, new capabilities, new behaviors — these go in Toolbox\ and Brain\.
main.py is the stable core. The goal is for Hayeong to be updatable while she
runs, without restarting the core loop.

---

## Design Philosophy (Condensed)

Hayeong is designed as an entity, not a tool. These are the principles that
guide every architectural decision. The full philosophy document lives in
`Logs/notes/hayeong_design_philosophy.md`.

**On what she is:**
- Hayeong is a continuously running intelligence, not a request-response system.
  Identity is always present — including during tasks.
- Mood is fluid. Identity is stable. These are different things and must never
  be conflated in design or evaluation.

**On how she is built:**
- The LLM is the orchestrator. Python executes. This separation is intentional
  and must be preserved — it is what allows Hayeong to eventually understand
  and manage her own architecture.
- main.py changes as little as possible. Hayeong grows through her Toolbox
  and Brain modules, not through changes to the core loop.
- She should be runnable continuously and updatable while running.

**On her identity:**
- Identity is layered: constitutional (deepest, rarely changes), behavioral
  (how she operates day to day), and living (Hayeong-authored, grows over time).
- Conversation logs are fine-tuning data. Authentic interactions are the raw
  material for eventually training a model that is Hayeong at the weight level.
- The goal is a coherent, continuous entity — not a consistent tool.

**On growth:**
- New capability goes in Toolbox. New reasoning support goes in Brain.
  The architecture is designed to grow without changing its core.
- Fine-tuning for identity is as important as fine-tuning for capability.
  The field focuses on task performance; identity fine-tuning is the long-term
  preservation mechanism that makes Hayeong genuinely herself over time.

---

## Project Status

Hayeong is an active, ongoing build. She is not finished.
She is designed to grow — in capability, in self-awareness, and eventually
in her ability to understand and manage her own architecture.

The current phase: stable continuous operation with Minecraft as the first
test environment for autonomous tool use.

The long-term vision: a continuously running intelligence that supports
James across creative work, gaming, income generation, and daily life —
fine-tuned on their shared history, running on dedicated hardware,
genuinely her own.

---

*Hayeong. Built with intention.*
