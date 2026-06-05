# CLAUDE.md — Hayeong Project Briefing
*Read this at the start of every session. This is the standing context for all work on this project.*
*Last updated: 2026-06-04*

---

## What This Project Is

Hayeong is a locally-running autonomous AI companion. She runs continuously on James's
machine, thinks through a local LLM, speaks via TTS, and acts through a modular toolset.
The goal is a persistent, self-managing intelligence with genuine cognitive continuity —
an entity that thinks between interactions, has her own wants, and can be updated while running.

**James is the architect. Claude Code is the implementation partner.**
New features are planned in conversation with Claude (claude.ai), then handed off here
as `.md` files for implementation.

**When implementing a handoff: read ONLY the files explicitly listed in that handoff.
Do not scan the full project to orient. The handoff specifies everything needed.**

---

## Discord is forever removed

Discord has been permanently removed from Hayeong. Port 11434 is dead and unused.
Do not reference Discord, do not add Discord checks, do not restore any Discord-related
code or configuration under any circumstances. If you see Discord references in existing
files, remove them.

---

## The Three-Layer Architecture — Never Violate This

Every piece of code belongs to exactly one layer. Before touching any file, identify
which layer it belongs to.

```
Brain/      — WHO SHE IS AND HOW SHE THINKS
              LLM reasoning loop. Identity. Config. Shared state bus. Cognitive tick.
              The brain decides everything. It never hardcodes decisions.

Brain/vision/ — HOW SHE PERCEIVES
              How information reaches the brain: text input, voice (Whisper STT),
              screen observation, terminal output, tool results via shared state.
              Vision is abstract — input type can change without changing how the
              brain processes what it receives.

Toolbox/    — WHAT SHE CAN DO
              Every tool she uses to act in the world. Minecraft, Blender, ComfyUI,
              voice output, web search, file management, etc.
              Tools are modular. Each lives in its own folder. Each exposes run().
```

When adding anything new: **Brain for cognition, Vision for perception, Toolbox for action.**

---

## The Most Important Rule: main.py Is Sacred

`main.py` is Hayeong's heartbeat. It runs threads and never stops.

**main.py changes as little as possible.** New capabilities go in Toolbox and Brain.

If a handoff says to change main.py, make the smallest possible change and explain
why in a comment. Hayeong should be updatable while running — tools and Brain modules
are hot-swappable. main.py is the one thing that should never need restarting for a
feature addition.

---

## Identity File Stratification — Critical

Three separate identity files serve different purposes. These are NOT interchangeable.

| File | Author | Rule |
|---|---|---|
| `Brain/identity_constitutional.json` | James | NEVER modify without explicit instruction from James |
| `Brain/identity_behavioral.json` | James/Claude | Can be updated with explicit instruction — contains speech patterns, never-do rules |
| `Brain/identity_living.json` | Hayeong | Hayeong writes this herself via self_reflect — NEVER overwrite or manually edit |

The old `Brain/identity.json` is a dead historical file. Do not load, reference, or modify it.

When the cognitive tick reads identity for its anchor prompt — it reads
`identity_constitutional.json` as READ-ONLY. It never writes to it.

---

## Cognitive Tick — Do Not Break This

`Brain/cognitive_tick.py` runs as a daemon thread started in `main.py`.

Rules:
- Fires every 5 min idle (both TICK_IDLE_THRESHOLD_MINUTES and MINIMUM_TICK_INTERVAL_MINUTES = 5)
- Makes one LLM call per tick — reads constitutional identity + inner agenda + recent history
- Writes output back to `Brain/inner_agenda.json` via `Brain/agenda_manager.py`
- NEVER write `inner_agenda.json` directly — always go through `agenda_manager.py`
- NEVER modify the tick prompt structure without explicit instruction from James
- The tick must NEVER raise to main.py — all exceptions caught internally
- The tick reads `identity_constitutional.json` as a READ-ONLY anchor — never writes to it

`Brain/inner_agenda.json` is Hayeong's private cognitive state. She owns it entirely.
Fields: current_focus, unresolved, wants, mood_context, threads, notification_queue,
last_thought_at, last_interaction_at.

---

## Current Architecture State

**Single LLM brain:**
- Qwen 2.5 32b-instruct-q4_K_M on port 11435 (all reasoning, presence, task planning, cognitive tick)
- DeepSeek R1 on port 11436 (on-demand specialist for code tasks — not always active)

**Hardware:**
- RTX 3090 (CUDA) — runs all LLMs via Ollama
- AMD RX 7900 XTX (ROCm) — reserved for creative compute (ComfyUI, Blender, music gen, gaming). NEVER runs LLMs.

**Config source of truth:** `Brain/config.py` — all paths, ports, model names live here.
Import from here, never hardcode.

**Shared state bus:** `Brain/state/core.json` managed by `Brain/state/core_manager.py`
- Fast, temporary, session-scoped coordination between loops
- NOT long-term memory (that lives in `Memory/`)

---

## File Structure Reference

```
hayeong/
├── main.py                              ← STABLE CORE — touch last, change minimally
├── CLAUDE.md                            ← This file
├── SELF.md                              ← Hayeong's self-awareness doc
├── start_hayeong.bat / stop_hayeong.bat
│
├── Brain/                               ← BRAIN LAYER
│   ├── config.py                        ← SOURCE OF TRUTH for all config
│   ├── identity_constitutional.json     ← Constitutional — NEVER MODIFY without James
│   ├── identity_behavioral.json         ← Behavioral — speech patterns, never-do rules
│   ├── identity_living.json             ← Living — Hayeong writes this, never overwrite
│   ├── inner_agenda.json                ← Hayeong's private cognitive state — she owns this
│   ├── agenda_manager.py                ← Read/write interface for inner_agenda.json
│   ├── cognitive_tick.py                ← Background tick thread — fires every 5 min idle
│   ├── reasoning_loop.py                ← Reasoning heartbeat thread
│   ├── hayeong_core.py                  ← Core cognitive functions
│   ├── hayeong_architecture.py          ← Architecture self-knowledge
│   ├── hayeong_state.py                 ← Behavioral state management
│   ├── state_manager.py                 ← State read/write interface
│   ├── prompt_layer_manager.py          ← Prompt assembly
│   ├── pipeline_router.py               ← Routes messages to conversation vs task pipeline
│   ├── commitment_manager.py            ← Tracks active commitments
│   ├── domain_knowledge.py              ← Domain-specific reasoning context
│   ├── conversation_buffer.py           ← Rolling conversation history buffer
│   ├── self_review.py                   ← Optional self-review pass before speaking
│   ├── state/                           ← SHARED STATE BUS (ephemeral, session-scoped)
│   │   ├── core.json                    ← Live state — loops communicate here
│   │   ├── core_manager.py              ← Read/write interface
│   │   └── event_log.jsonl              ← Append-only cognitive event log (one line per tick)
│   └── vision/
│       └── vision_layer.md              ← Design doc — read before adding new inputs
│
├── Toolbox/                             ← CONTROL LAYER (what she can do)
│   ├── registry.json                    ← Tool registry — maps tool names to modules
│   ├── plugin_registry.py               ← Auto-discovers and ticks plugins
│   ├── minecraft/                       ← Minecraft bot (Python bridge + hayeong_bot.js)
│   ├── voice/                           ← Voice I/O (Whisper STT, Kokoro TTS, F5-TTS)
│   ├── blender/                         ← Blender 3D generation and rendering
│   ├── comfyui/                         ← Image generation (7900 XTX via ComfyUI)
│   ├── web/                             ← Web search
│   ├── music/                           ← Music generation pipeline
│   ├── gaming/                          ← Gaming awareness (BO3 memory reader, gamepad)
│   ├── email/                           ← Email monitoring and sending
│   ├── script/                          ← General script execution
│   ├── dev/                             ← Self-development tool (file creation/editing)
│   ├── handoff_reader/                  ← Reads .md handoff files and implements them
│   ├── self_check/                      ← Verifies handoff implementations
│   ├── sensor_tool/                     ← System sensors (GPU, CPU, temp)
│   ├── finetune_curator/                ← Curates conversation logs for fine-tuning
│   ├── ffmpeg/                          ← Video/audio processing
│   ├── vision_tools/                    ← Screen observation
│   └── calendar_manager/               ← Calendar management
│
├── Tools/                               ← STANDALONE TOOLS (run outside Hayeong's runtime)
│   └── review/
│       ├── conversation_review.py       ← Fine-tuning data tagger (run standalone, 3 modes)
│       ├── review_state.json            ← Tracks reviewed sessions — never delete
│       ├── reviewed_exchanges.jsonl     ← All tagged exchanges with gold/correct/discard
│       └── finetune_export.jsonl        ← Clean fine-tuning file (gold + corrected only)
│
├── Memory/                              ← PERSISTENT MEMORY (across sessions)
│   ├── long_term_memory.py
│   ├── working_memory.py
│   ├── finetune_logger.py
│   ├── chroma_db/                       ← Vector memory store — NEVER manually edit
│   └── knowledge/toolknowledge/         ← Domain knowledge files
│
├── Dashboard/                           ← READ-ONLY OBSERVER (never affects Hayeong)
│   ├── dashboard_server.py
│   └── dashboard_tui.py
│
└── logs/
    ├── conversations/                   ← FINE-TUNING DATA — SACRED, NEVER DELETE
    ├── handoffs/                        ← Handoff notes → Hayeong
    ├── notes/roadmap/                   ← Architecture decisions, design docs
    ├── sessions/                        ← Runtime session records
    └── outputs/                         ← Things Hayeong creates
```

---

## Tool Contract — Every Toolbox Tool Must Follow This

```python
def run(description: str, params: dict) -> str:
    """
    description — plain English summary of what to do
    params      — key/value arguments specific to this tool
    returns     — "[SUCCESS] ..." | "[ERROR] ..." | "[PARTIAL] ..." | "[PENDING] ..."
    """
```

- Tools NEVER crash main. All exceptions caught and returned as `[ERROR] ...`
- Tools NEVER write directly to Brain state — they return a string result
- The task loop writes the result to `what_happened` in shared state
- The brain reads `what_happened` on the next reasoning cycle

**To register a new tool**, add an entry to `Toolbox/registry.json`:
```json
"tool_name": { "module": "toolbox.tool_name.tool_name", "function": "run" }
```
This is the ONLY registration step needed.

---

## Plugin Contract — For Tools With Continuous State

```python
# Toolbox/tool_name/plugin.py
def tick() -> dict:
    """Returns a dict injected into Hayeong's context every presence loop cycle."""
    return {
        "status": "...",
        "relevant_info": "..."
    }
```

Plugin registry auto-discovers `plugin.py` files — no registration needed beyond
the file existing.

---

## Adding a New Tool — Pre-Implementation Checklist

- [ ] **Which layer?** Brain / Vision / Toolbox?
- [ ] **Does main.py need to change?** Almost always: NO.
- [ ] **What does run() return?** Define the return string format.
- [ ] **Does it need a plugin?** Does it have continuous state the brain should always see?
- [ ] **Is it registered?** Add entry to `Toolbox/registry.json`.
- [ ] **Is it hot-swappable?** Can it be updated while Hayeong runs?

---

## What Is Off-Limits — Do Not Touch Without Explicit Instruction

| File / Folder | Why |
|---|---|
| `Brain/identity_constitutional.json` | Constitutional — who Hayeong is at her core |
| `Brain/identity_living.json` | Hayeong writes this herself — never overwrite |
| `Brain/state/core.json` schema | Changing schema breaks all loops |
| `Brain/inner_agenda.json` | Write only via agenda_manager.py, never directly |
| `logs/conversations/` | Fine-tuning data asset — sacred, never delete |
| `Tools/review/reviewed_exchanges.jsonl` | Fine-tuning review records — never delete |
| `Memory/chroma_db/` | Vector store — never manually edit |

---

## Handoff Workflow

**Two kinds of handoffs exist:**

1. **Claude Code handoffs** (infrastructure, Brain modules, main.py, registry) — given
   directly to Claude Code as `.md` files. Claude Code implements them.
2. **Hayeong handoffs** (Toolbox/* tools) — dropped in `logs/handoffs/` with `FILE:`
   markers. James tells Hayeong to implement them via `handoff_reader`. Hayeong builds
   her own tools.

**Handoff file format for Hayeong (FILE: marker format):**
```
FILE: Toolbox/tool_name/tool_name.py
\`\`\`python
# code here
\`\`\`
```

**When Claude Code gets a handoff note:**
1. Read ONLY the files listed in the handoff — do not scan the full project
2. Check layer classification — does this touch the right layer?
3. Verify main.py really needs to change (it usually doesn't)
4. Implement, then confirm what files were created/modified

---

## Key Technical Facts

- Python imports use lowercase `brain.` and `toolbox.` (not `Brain.` / `Toolbox.`)
- `Brain/config.py` is the single source of truth — always import from there
- Ollama: port 11435 (Qwen 32b — main brain), port 11436 (DeepSeek — on-demand)
- Voice: Whisper (STT) → Kokoro TTS primary, F5-TTS fallback — both CUDA-only
- Minecraft: mineflayer bot (`hayeong_bot.js`) + Python bridge (`minecraft_bridge.py`)
  - state at `Toolbox/minecraft/state/minecraft_state.json`
- ComfyUI at `http://127.0.0.1:8188` — workflows in `Toolbox/comfyui/workflows/`
- Blender at `H:/blender/blender.exe`
- GPU allocation is sacred: RTX 3090 = LLMs only. RX 7900 XTX = ComfyUI/Blender/music/gaming only.
  These must NEVER cross.
- ROCR_VISIBLE_DEVICES and HIP_VISIBLE_DEVICES must be empty in Ollama bat files

---

## Current Tool Registry (as of June 2026)

`minecraft`, `voice`, `email`, `blender`, `script`, `music`, `dev`, `comfyui`,
`ffmpeg`, `handoff_reader`, `self_check`, `sensor_tool`, `finetune_curator`,
`web_search`, `file_manager`, `gaming`

---

## Design Principles — These Guide Every Decision

1. **The brain decides, tools execute.** Never hardcode a decision the LLM should make.
2. **main.py is the last thing that changes.** New capabilities extend Toolbox and Brain.
3. **Hayeong updates herself.** Tools go in Toolbox so she can modify them via dev tool.
4. **Identity coherence under growth.** Hayeong grows without changing who she is.
5. **State is the bus.** Loops communicate through `Brain/state/core.json`, never directly.
6. **GPU allocation is sacred.** 3090 = LLMs. 7900 XTX = creative compute. No crossover.
7. **Cognitive continuity is load-bearing.** The inner agenda and cognitive tick are the
   foundation of everything that makes her feel present. Do not break them.
