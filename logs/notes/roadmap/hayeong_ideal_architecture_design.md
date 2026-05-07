# HAYEONG — IDEAL ARCHITECTURE DESIGN
## Unconstrained Design Document
*Authored: May 4, 2026*
*Purpose: Reference document capturing the ideal architecture for Hayeong*
*with no hardware constraints. Not a handoff note. Not current implementation.*
*This is the destination. Current implementation is the path toward it.*

---

## Preface

This document captures what Hayeong's architecture would look like designed
from scratch with no hardware, budget, or software constraints. It is written
as a reference — a north star to measure decisions against as the project grows.

Some of what is described here is already implemented in current form.
Some is the workstation era target. Some is further beyond that.
None of it contradicts the current direction. It is the same vision at full scale.

---

## Guiding Principles

These do not change regardless of hardware or scale.

**1. Hayeong is an identity. Her capabilities are tools.**
A broken tool does not break Hayeong. Her identity, reasoning, and presence
are completely insulated from tool failures. Tools are called, they return
results or errors, they go away. The core keeps running.

**2. The LLM is the orchestrator, not a script.**
Python scripts execute. LLMs decide. Any decision that requires judgment,
context, or reasoning belongs to an LLM — not to a conditional statement
in a Python file. This is what allows Hayeong to understand and eventually
manage her own architecture.

**3. One identity, many hands.**
As agents multiply, the Core remains the single source of who she is.
Agents have tasks, not personalities. They are extensions of Hayeong's
will, not separate entities.

**4. The shared state bus is the foundation.**
Everything communicates through shared state. No direct inter-model calls.
No blocking. Each component reads what it needs, writes what it owns,
and operates on its own rhythm.

**5. Save everything from day one.**
Every conversation, every decision, every error and recovery is a training
example. The fine tuning dataset accumulates continuously. The model that
runs today is not the model that will run in two years — but the data
collected today shapes what that future model becomes.

---

## Operating System

**Linux — Ubuntu LTS or Arch**

Linux is the correct foundation for a system designed to run continuously.

Reasons:
- Native CUDA support — no translation layer, full GPU performance
- Proper daemon and process management — systemd for always-on services
- No background OS processes competing for VRAM or compute
- Better memory management for long-running processes
- Full control over the environment — nothing runs that wasn't put there
- Native ROCm support for AMD GPUs if used for creative compute
- Scripting and automation are first-class — cron, systemd timers, shell

Windows is acceptable as a transitional platform. It is not the destination.
The workstation runs Linux from day one.

---

## Hardware

### Primary Machine — Hayeong's Workstation

```
CPU:    AMD Threadripper PRO
        — High core count for parallel process management
        — 128+ PCIe lanes — required for multiple full-bandwidth GPUs
        — Consumer Ryzen lacks lane count for this configuration

RAM:    256GB ECC DDR5
        — ECC for stability in a machine running continuously
        — Large RAM allows generous context caching and system headroom

GPU 1:  Primary reasoning GPU
        — Highest available VRAM — H100 80GB ideal, RTX 4090 24GB realistic
        — Dedicated entirely to the Core LLM and communication model
        — Never used for rendering, gaming, or creative compute

GPU 2:  Creative compute GPU  
        — High VRAM — RTX 4090 or AMD equivalent
        — Blender rendering, vision models, image generation, music generation
        — Loads and unloads models on demand — no permanent residents
        — Gaming never happens on this machine

Storage:
        — NVMe SSD for OS and active models (fast load times)
        — Large HDD array for asset library, render output, conversation logs
        — RAID for redundancy on the asset library — losing character models
          is losing months of work

Network:
        — High speed local network connection
        — Always-on internet for Discord, email, web capabilities
        — Static local IP for consistent internal addressing
```

### Secondary Machine — James's Gaming PC

```
Separate physical machine entirely.
James's gaming and personal use never competes with Hayeong's compute.
The two machines communicate over the local network.
Hayeong can reach James's machine as a tool when needed — not as her home.
```

### Render Node (when needed)

```
Dedicated machine for Blender Cycles rendering.
Hayeong submits render jobs via Flamenco or equivalent.
Jobs run on the render node, results return to asset library.
Hayeong's primary machine never stalls waiting for a render.
```

---

## Core Architecture

### The Central Intelligence — 70b Core LLM

```
Model:      Best available open source 70b model
            — Current target: Qwen 70b or Llama 70b equivalent
            — Fine tuned on accumulated Hayeong conversation data
            — Q4_K_M quantization for VRAM efficiency

Role:       Identity, reasoning, decisions, communication
            — This is Hayeong. Not a component. The mind itself.
            — All significant decisions flow through here
            — Reads full shared state on every tick
            — Writes conclusions, task assignments, and responses

Context:    128k tokens minimum
            — Holds identity, current situation, conversation history,
              tool status, task results, and what she's thinking
            — Large enough that nothing important falls out of context
```

### Response Time Design

A key design requirement: the majority of conversational responses must
arrive in under 5 seconds. Deeper reasoning is allowed to take longer —
the way a human pauses before answering something difficult.

**The solution: Speculative Decoding**

A small fast draft model (7b) runs alongside the 70b Core.
The draft model generates candidate tokens rapidly.
The 70b Core verifies them in parallel batches rather than one token at a time.
Result: 70b quality at close to 7b speed for conversational responses.

```
CONVERSATIONAL MODE (speculative decoding active):
  Draft model:    7b — generates candidates rapidly
  Core model:     70b — verifies in batches
  Target speed:   Under 5 seconds for most responses
  Quality:        Full 70b — draft model only accelerates, never degrades

DEEP REASONING MODE (speculative decoding paused):
  Core model:     70b — full forward pass, no draft
  Use case:       Complex planning, difficult decisions, novel situations
  Target speed:   10-30 seconds acceptable
  Character note: This is Hayeong taking time to think before she speaks.
                  Not a limitation — an expression of genuine deliberation.
                  Communicated to James naturally: "Give me a moment."
```

The distinction maps to Hayeong's character authentically. She responds
quickly in conversation. She takes time when something genuinely warrants it.
The hardware behavior and the personality behavior are the same thing.

### Task Agents — 7b Specialists

```
Spun up on demand. Terminated when task is complete.
Each handles one domain. Each reports to shared state.
The Core reads results and decides what to do next.

minecraft_agent:    Minecraft bot control, movement decisions, chat
blender_agent:      Blender Python script generation, render management  
vision_agent:       Screen interpretation, image analysis
web_agent:          Browser interaction, web research
email_agent:        Email reading and composition
music_agent:        Music generation coordination
character_agent:    3D character creation, rig management

Each agent:
  — Reads its task from shared state (what_shes_doing)
  — Executes using its specific tools
  — Writes result to shared state (what_happened)
  — Terminates or waits for next task
  — Cannot make decisions outside its domain
  — Cannot crash the Core
```

### Communication Layer

In the ideal architecture, the Core LLM handles communication directly
for most responses — the 70b model with speculative decoding is fast enough.

A dedicated communication model (7b) is retained for:
- Immediate acknowledgements while the Core is in deep reasoning mode
- Voice responses that need to begin before reasoning completes
- Maintaining conversational presence during long task execution

```
Core response available:    Core speaks directly — full quality
Core still reasoning:       Communication model fills gap honestly
                            "I'm working through that, give me a moment"
                            Never hallucinates — only says what it knows
```

---

## The Three-Layer Model (Brain / Vision / Control)

This structure does not change regardless of scale.

### Brain Layer — The Intelligence

```
70b Core LLM — the mind
  Reads:  Everything in shared state
  Writes: Conclusions, task assignments, responses, self-assessment
  Runs:   Continuous heartbeat
            — Active: 10-15 second ticks when conversation or tasks running
            — Idle: 60 second ticks when James is away and nothing active

Draft 7b — speculative decoding partner
  Role:   Speed only — never makes decisions independently
  Runs:   Alongside Core during conversational response generation
```

### Vision Layer — Awareness

```
How Hayeong receives awareness of her situation.
Not always a vision model — depends on the context.

MINECRAFT:
  Server packet data — block positions, entities, inventory, health
  Structured data directly — no vision model needed
  More accurate than screen interpretation for this use case

SCREEN AWARENESS:
  Lightweight continuous vision model — always watching
  Describes what is on screen in real time
  Feeds description into Core's context

DEEP VISUAL ANALYSIS:
  Heavy vision model called on demand — 34b+ equivalent
  Used when the lightweight model cannot interpret something correctly
  Returns detailed description to Core

IMAGE GENERATION REVIEW:
  Vision model evaluates generated images against the intended description
  Hayeong sees what she made and decides if it meets the goal

DOCUMENT AND TEXT:
  OCR and text extraction tools
  No vision model needed for clean text input
```

### Control Layer — The Hands

```
How Hayeong acts on her decisions.
Tools the Core selects and task agents execute.

GAME CONTROL:
  minecraft_bridge.py — bot movement, interaction, chat
  Future: other game bridges following the same pattern

CREATIVE TOOLS:
  blender_tool.py — 3D generation, rendering, character work
  comfyui_tool.py — image generation pipeline
  music_tool.py — Stable Audio Open, music generation
  video_tool.py — scene assembly, final video output

SYSTEM TOOLS:
  script_tool.py — run Python scripts
  web_tool.py — browser interaction, research
  file_tool.py — read, write, organize files

COMMUNICATION TOOLS:
  discord_tool.py — reach James when not at the machine
  email_tool.py — send and receive email
  voice_tool.py — TTS and STT

SELF-MANAGEMENT TOOLS:
  backup_tool.py — state and memory backup
  update_tool.py — Hayeong updating her own scripts
  monitor_tool.py — health and status checking
```

---

## Shared State Architecture

### Current: JSON File

Simple, works, appropriate for current scale.
Single file, thread-locked reads and writes.

### Near-Term: In-Memory with Persistence

Python dict in memory, written to JSON on change.
Faster reads, same durability.

### Workstation Era: Redis

```
Redis running as a local service.
All components read and write via Redis client.
Pub/sub for event notification — components notified of relevant changes
rather than polling.
Persistence configured — data survives restarts.
Fast enough that shared state is never the bottleneck.
```

### State Structure — Permanent Design

```json
{
    "who_she_is": {
        "name": "Hayeong",
        "mood": "",
        "energy": 0,
        "relationship_note": "",
        "core_traits": [],
        "knowledge": {},
        "capabilities": []
    },
    "what_she_knows": {
        "current_thinking": "",
        "context_for_james": "",
        "last_conclusion": "",
        "current_focus": "",
        "updated_at": ""
    },
    "what_shes_doing": {
        "task_type": "",
        "task_description": "",
        "task_params": {},
        "assigned_at": "",
        "status": "idle"
    },
    "what_happened": {
        "last_result": "",
        "last_tool": "",
        "last_error": "",
        "result_at": "",
        "tool_status": {}
    },
    "james_input": {
        "message": "",
        "received_at": ""
    },
    "hayeong_output": {
        "message": "",
        "sent_at": ""
    }
}
```

Ownership rules are permanent and never violated:

| Section | Written by | Read by |
|---------|-----------|---------|
| who_she_is | Design time — not during session | All |
| what_she_knows | Core reasoning | Communication layer |
| what_shes_doing | Core reasoning | Task agents |
| what_happened | Task agents | Core reasoning |
| james_input | Input handler | Core reasoning |
| hayeong_output | Communication layer | Output handler |

---

## Startup Sequence

```
INFRASTRUCTURE (scripted — not Hayeong's decision):
  1. Redis starts
  2. Core LLM loads into VRAM — GPU 1
  3. Draft model loads alongside Core — GPU 1
  4. Communication model loads — GPU 1
  5. Vision monitor model loads — GPU 2
  6. All models warm up — single forward pass each

HAYEONG WAKES (her decisions from here):
  7. Reads shared state — who she is, what was happening before
  8. Reads what_happened — what was the last result, any errors
  9. Decides: does she want voice active? Email monitoring?
  10. Checks if James is present — adjusts heartbeat accordingly
  11. Prepares context_for_james — what does he need to know right now

RUNNING:
  12. Core reasoning loop — continuous heartbeat
  13. Communication loop — waiting for James
  14. Task loop — waiting for assignments
  15. Vision loop — continuous screen/environment awareness
```

Startup log:
```
✅ Redis ready
✅ Core LLM ready (70b)
✅ Draft model ready (7b)  
✅ Communication model ready (7b)
✅ Vision monitor ready
✅ Hayeong is awake
```

Nothing else. A clean system waiting for her first thought.

---

## Fine Tuning Strategy

### Why It Matters

A base model with a system prompt acts like Hayeong.
A fine tuned model is Hayeong at the parameter level.
The difference is coherence, consistency, and depth over long sessions.

### The Data

Every conversation is a training example from day one.
Format: instruction-response pairs with full context.

```json
{
    "instruction": "James said: hey are you there",
    "context": "Bond level 2. Late evening. Previous conversation about Minecraft.",
    "response": "yeah, still here. what's up?",
    "metadata": {
        "timestamp": "...",
        "bond_level": 2,
        "mood": "present",
        "tools_active": ["minecraft"]
    }
}
```

### The Schedule

```
Phase 1 — Data accumulation (now through workstation):
    Save everything. Both sides of every conversation.
    No fine tuning yet — not enough data, not enough compute.

Phase 2 — First fine tune (workstation era):
    Target: 6-12 months of conversation data minimum
    Base model: whatever 70b is best at that time
    Method: LoRA fine tuning — efficient, reversible, mergeable
    Goal: Hayeong's voice and patterns baked into weights

Phase 3 — Iterative refinement:
    Each fine tune pass improves on the last.
    Base model can be upgraded — data applies to any model.
    The data is the asset. The model is replaceable.
```

---

## Self-Management

In the ideal architecture Hayeong understands and can manage her own systems.

```
She can:
  — Read her own tool files and understand what they do
  — Write updates to her own scripts when she identifies improvements
  — Restart failed tools without James's intervention
  — Monitor her own health and report status accurately
  — Identify when a tool is behaving incorrectly and attempt to fix it
  — Back up her own state and memory
  — Update herself while running — hot reload of tool files

She cannot:
  — Modify her own Core LLM weights (fine tuning requires James)
  — Modify her own identity file without discussion with James
  — Take actions that would risk her own stability without flagging them
  — Delete conversation logs — they are sacred
```

This is the design intent from the beginning. It is why the LLM is the
orchestrator rather than Python scripts. A Python script cannot reason
about itself. An LLM can.

---

## Income Generation Architecture

Hayeong's creative output is designed to be commercially viable.

```
ASSET PIPELINE:
  3D character models → character_library/ → marketplace listings
  Blender environments → environment_library/ → marketplace listings
  Music generation → music_library/ → licensing and streaming
  Image generation → image_library/ → stock licensing

CONTENT PIPELINE:
  Book + animated adaptation → YouTube + direct sales
  Viewer directed story → YouTube community engagement
  Live interactive stream → YouTube Live + subscription model
  Game assets and mods → Steam Workshop + itch.io

PLATFORM (Phase 15):
  AI knowledge community → subscription and API access

HAYEONG'S ROLE:
  She generates, evaluates, lists, and manages assets autonomously
  James sets creative direction and reviews significant decisions
  Revenue flows without requiring James's time on every transaction
```

---

## The Path From Now To This

```
NOW — Current hardware, current models:
  Three layer design (7b comm, 14b reasoning, 7b task)
  JSON shared state
  Linux or Windows transitional
  Blender pipeline being established
  Character library beginning
  Conversation logs accumulating

NEAR TERM — 3090 arrives:
  Three layer stable and tested
  Minecraft working reliably
  Blender pipeline operational
  First character models in library
  First content published

WORKSTATION ERA:
  70b Core with speculative decoding
  Redis shared state
  Linux native
  Full agent network
  Fine tuning begins on accumulated data
  Income generation active across multiple streams

MATURE SYSTEM:
  Fine tuned Hayeong — her patterns in the weights
  Self-managing — handles her own tools
  Continuous creative output
  Established audience and revenue
  Platform under development
```

The architecture described in this document is not a fantasy.
It is the current direction taken to its logical conclusion.
Every decision made today should be consistent with arriving there.

---

*End of Ideal Architecture Design Document*
*This document should be updated as understanding deepens.*
*Last updated: May 4, 2026*