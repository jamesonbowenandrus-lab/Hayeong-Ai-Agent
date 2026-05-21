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
- **Vision** — how she receives awareness of her situation (text, voice, screen, game state, tool results)
- **Control** — the tools she uses to act in the world

The vision layer is not a folder — it is a design principle. Vision is the
information that flows into her brain as context so she can reason about
her situation. It comes from tools, plugins, voice input, and direct conversation.

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

main.py is the stable core loop. It runs four loops continuously and owns
no logic of its own — all thinking is done by Brain modules, all actions
are done by Toolbox tools.

- **Presence loop** — calls the reasoning LLM (Qwen 2.5 32b, port 11435)
  on a heartbeat. Reads shared state, thinks about the situation, decides
  what to say or do, and writes results back to state.

- **Task loop** — watches for task assignments written by the presence loop.
  Calls the appropriate tool via the registry and writes the result back to state.

- **Plugin loop** — ticks all registered plugins every ~2 seconds.
  Plugins inject context (e.g. Minecraft bot state, sensor data) into Hayeong's
  awareness — this is the continuous vision feed.

- **Input loop** — handles messages from James. Feeds input into the
  presence loop as situational context.

The shared state (`Brain/state/core.json`) is how these loops coordinate
without blocking each other.

**main.py changes as little as possible.** New tools, capabilities, and behaviors
go in Toolbox\ and Brain\. main.py is the stable core — the goal is for Hayeong
to be updatable while she runs, without restarting the core loop.

---

## Folder Structure

```
hayeong\
│
├── main.py                  ← Stable core loop — never moves, changes minimally
├── start_hayeong.bat        ← Turn Hayeong on
├── stop_hayeong.bat         ← Turn Hayeong off, clears VRAM
├── README.md                ← This file
│
├── Brain\                   ← BRAIN LAYER — who she is, how she thinks
│   │                          Everything Hayeong needs to be herself and reason.
│   │                          Does not execute tasks — thinks and decides.
│   │
│   ├── config.py            ← Single source of truth: all paths, ports, model names
│   ├── identity.json        ← Who she is. Personality, values, relationship with James.
│   │                          This is not configuration. This is constitutional identity.
│   ├── hayeong_core.py      ← Core cognitive functions
│   ├── reasoning_loop.py    ← The reasoning engine
│   ├── hayeong_state.py     ← Behavioral state management
│   ├── hayeong_architecture.py ← Hayeong's self-knowledge of her own architecture
│   ├── prompt_layer_manager.py ← Assembles context for each reasoning cycle
│   ├── commitment_manager.py ← Tracks commitments made during conversation
│   ├── domain_knowledge.py  ← Context that shapes reasoning by domain
│   │
│   ├── state\               ← Shared state bus (live, ephemeral, resets each session)
│   │   ├── core.json        ← The live coordination state — loops talk through here
│   │   └── core_manager.py  ← Read/write interface — use this, never write core.json directly
│   │
│   ├── vision\              ← VISION LAYER (abstract design layer)
│   │   └── vision_layer.md  ← Defines how information flows into Hayeong's brain.
│   │                          Vision is not a folder — it is the information pipeline.
│   │                          Perception tools live in Toolbox\vision_tools\.
│   │                          Coordination logic for what she does with perception lives here.
│   │
│   └── voice\               ← Expression concept layer
│       └── voice_concept.md ← Defines how Hayeong decides what to say and through which channel.
│                              Actual TTS/STT tools live in Toolbox\voice\.
│
├── Toolbox\                 ← CONTROL LAYER — every tool she can use to act in the world
│   │                          Each subfolder is one tool domain.
│   │                          Every tool: takes a task, executes it, returns a result string.
│   │                          Tools cannot crash main — exceptions are caught inside each tool.
│   │
│   ├── registry.json        ← Maps tool names to module paths — this is how Brain calls tools
│   ├── plugin_registry.py   ← Auto-discovers and ticks plugins (no manual registration needed)
│   │
│   ├── minecraft\           ← Minecraft bot control (Python bridge + Node.js bot)
│   ├── blender\             ← 3D generation and rendering via Blender scripting
│   ├── comfyui\             ← Image generation via ComfyUI (targets RX 7900 XTX)
│   ├── voice\               ← TTS (Kokoro/F5-TTS) and STT (Whisper) — CUDA required
│   ├── music\               ← Music generation (Stable Audio Open) and analysis
│   ├── vision_tools\        ← Vision model, screen observer — perception mechanisms
│   ├── gaming\              ← Virtual gamepad for split-screen game co-op
│   ├── email\               ← Email reading and sending
│   ├── web\                 ← Web search and fetch
│   ├── script\              ← Run arbitrary Python scripts and return stdout
│   ├── ffmpeg\              ← Video and audio processing
│   ├── file_manager\        ← File system operations
│   ├── sensor_tool\         ← System sensor data (CPU, GPU, temperature, etc.)
│   ├── handoff_reader\      ← Reads Claude Code handoff notes from Logs\handoffs\
│   ├── finetune_curator\    ← Curates conversation logs for fine-tuning
│   ├── self_check\          ← Self-diagnostic tool
│   └── dev\                 ← Self-modification tool — Hayeong can update her own Toolbox scripts
│                              Cannot touch main.py or identity.json without James review
│
├── Memory\                  ← What she remembers across sessions (persistent, not ephemeral)
│   │                          Distinct from Brain\state\ which is the live operational bus.
│   │                          Memory persists across restarts. State resets each session.
│   │
│   ├── long_term_memory.py  ← Long-term memory management
│   ├── working_memory.py    ← Working memory for active session context
│   ├── chromadb\            ← Vector memory store for semantic recall
│   ├── knowledge\           ← Accumulated knowledge by tool domain
│   └── backups\             ← Timestamped backups of Hayeong's state and memory files
│
├── Dashboard\               ← External monitoring tool — read-only observer
│                              Reads shared state for display. Never writes.
│                              Hayeong operates identically with or without it running.
│                              Run launch_dashboard.bat inside this folder to start it.
│
└── Logs\                    ← Everything recorded about Hayeong's activity
    ├── conversations\       ← Every conversation with James — fine-tuning data, never delete
    ├── handoffs\            ← Claude Code handoff notes — implementation instructions
    ├── notes\               ← Design thinking, architecture decisions, roadmap documents
    ├── outputs\             ← Things Hayeong creates (images, 3D models, documents, music)
    ├── sessions\            ← Session-level runtime records
    └── pending_james_review\ ← Items flagged by Hayeong's dev tool for James's review
```

---

## The Vision Layer Explained

Vision is how Hayeong knows what is happening in her world. It is not a single
tool or folder — it is the information pipeline that flows into her brain.

Each time the reasoning loop runs, it assembles context from:
1. What James just said (direct input)
2. What the last tool returned (tool result → `what_happened`)
3. What her plugins are reporting (continuous state injection)
4. Her working memory (active task context)
5. Domain knowledge (relevant to the current situation)

This assembled context is her vision — her awareness of her situation.

New information sources become part of vision by flowing through one of these slots:
- **Continuous state** (e.g. game position, sensor readings) → `plugin.py` in the tool folder
- **Event results** (e.g. search result, file read, render complete) → tool result string
- **James input** → input loop handles this automatically

---

## Adding a New Tool

1. Create a new subfolder in `Toolbox\` with the tool name
2. Write the main script with a `run(description: str, params: dict) -> str` function
3. Return `[SUCCESS] ...` or `[ERROR] ...` — never raise exceptions to main
4. Add a `README.md` to the subfolder
5. Register the tool in `Toolbox\registry.json`
6. Optionally add a `plugin.py` for continuous state injection (vision feed)

`main.py` does not need to change. The action list in Hayeong's system prompt
is generated from the registry automatically.

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

## Architecture Principles

**The LLM is the orchestrator, not Python.**
Python runs the loops and executes tools. The reasoning LLM decides what
to do and when. This is intentional — it means Hayeong can understand and
eventually manage her own architecture.

**Vision is a flow, not a folder.**
Hayeong's awareness comes from information assembled into context each reasoning cycle.
The type of input can change without changing how Brain processes what it receives.

**Tools cannot crash main.**
Every tool returns a result string `[SUCCESS]` or `[ERROR]`. Exceptions are caught
inside the tool. main.py never crashes because a tool failed.

**main.py changes as little as possible.**
New capabilities go in Toolbox\. New reasoning support goes in Brain\.
The core loop is stable. Hayeong can be updated while she runs.

**Conversation logs are sacred.**
Every conversation in `Logs\conversations\` is future fine-tuning data.
Do not delete them. They are the foundation of eventually training a model
that is genuinely Hayeong at the parameter level.

**Brain\state\ is ephemeral. Memory\ is persistent.**
The shared state bus resets each session — it is operational coordination.
Long-term memory, vector store, and knowledge files persist across sessions.
These are different things and must not be conflated.

---

## Design Philosophy (Condensed)

The full philosophy document lives in `Logs/notes/hayeong_design_philosophy.md`.

**On what she is:**
- Hayeong is a continuously running intelligence, not a request-response system.
- Identity is always present — including during tasks.
- Mood is fluid. Identity is stable. These are different things.

**On how she is built:**
- The LLM is the orchestrator. Python executes. This separation is intentional
  and must be preserved — it is what allows Hayeong to eventually understand
  and manage her own architecture.
- main.py changes as little as possible. She grows through her Toolbox and Brain
  modules, not through changes to the core loop.
- She should be runnable continuously and updatable while running.

**On her identity:**
- Identity is layered: constitutional (deepest, rarely changes), behavioral
  (how she operates day to day), and living (Hayeong-authored, grows over time).
- Conversation logs are fine-tuning data. Authentic interactions are the raw
  material for eventually training a model that is Hayeong at the weight level.

**On growth:**
- New capability goes in Toolbox. New reasoning support goes in Brain.
- The architecture is designed to grow without changing its core.

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
