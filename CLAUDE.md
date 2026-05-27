# CLAUDE.md — Hayeong Project Briefing
*Read this at the start of every session. This is the standing context for all work on this project.*

---

## What This Project Is

Hayeong is a locally-running autonomous AI companion. She runs continuously on James's machine, thinks through a local LLM, speaks via TTS, and acts through a modular toolset. The goal is a persistent, self-managing intelligence that can be updated while running.

**James is the architect. Claude Code is the implementation partner.**
New features are planned in conversation with Claude (claude.ai), then handed off here as `.md` files for implementation.

---

## The Three-Layer Architecture — Never Violate This

Every piece of code in this project belongs to exactly one layer. Before touching any file, identify which layer it belongs to.

```
Brain/      — WHO SHE IS AND HOW SHE THINKS
              The LLM reasoning loop. Identity. Config. Shared state bus.
              The brain decides everything. It never hardcodes decisions.

Brain/vision/ — HOW SHE PERCEIVES
              How information reaches the brain: text input, voice (Whisper STT),
              screen observation, terminal output, tool results via shared state.
              Vision is abstract — the type of input can change without changing
              how the brain processes what it receives.

Toolbox/    — WHAT SHE CAN DO
              Every tool she uses to act in the world. Minecraft bot control,
              Blender, ComfyUI, voice output, web search, file management, etc.
              Tools are modular. Each lives in its own folder. Each exposes run().
```

When adding anything new: **Brain for cognition, Vision for perception, Toolbox for action.**

---

## The Most Important Rule: main.py Is Sacred

`main.py` is Hayeong's heartbeat. It runs three threads and never stops:
- **Presence loop** — calls Qwen 32b (port 11435) on a heartbeat. Reads state, thinks, writes decisions.
- **Task loop** — watches for task assignments written by presence. Calls the right tool. Writes results back to state.
- **Input loop** — reads James's messages into shared state.

**main.py changes as little as possible.** New capabilities go in Toolbox and Brain, not main.

If a handoff note says to change main.py, think hard about whether it's truly necessary. If it is, make the smallest possible change and explain why in a comment. If it isn't, find the right layer instead.

Hayeong should be updatable while running. Tools and Brain modules are hot-swappable. main.py is the one thing that should never need to be restarted for a feature addition.

---

## Current Architecture State

**Single LLM brain:**
- Qwen 2.5 32b-instruct-q4_K_M on port 11435 (all reasoning, presence, task planning)
- DeepSeek R1 on port 11436 (on-demand specialist for code tasks — not always active)
- Port 11434 = Discord bot only

**Hardware:**
- RTX 3090 (CUDA) — runs all LLMs via Ollama
- AMD RX 7900 XTX (ROCm) — reserved for creative compute (ComfyUI, Blender, music gen, gaming). Never runs LLMs.

**Config source of truth:** `Brain/config.py` — all paths, ports, model names live here. Import from here, never hardcode.

**Shared state bus:** `Brain/state/core.json` managed by `Brain/state/core_manager.py`
- This is fast, temporary, session-scoped coordination between loops
- It is NOT long-term memory (that lives in `Memory/`)

---

## File Structure Reference

```
hayeong/
├── main.py                         ← STABLE CORE — touch last, change minimally
├── SELF.md                         ← Hayeong's self-awareness doc (her map of herself)
├── start_hayeong.bat / stop_hayeong.bat
│
├── Brain/                          ← BRAIN LAYER
│   ├── config.py                   ← SOURCE OF TRUTH for all config
│   ├── identity.json               ← Constitutional — do not change without discussion
│   ├── reasoning_loop.py           ← Reasoning heartbeat thread
│   ├── hayeong_core.py             ← Core cognitive functions
│   ├── hayeong_architecture.py     ← Architecture self-knowledge
│   ├── hayeong_state.py            ← Behavioral state management
│   ├── state_manager.py            ← State read/write interface
│   ├── prompt_layer_manager.py     ← Prompt assembly
│   ├── commitment_manager.py       ← Tracks active commitments
│   ├── domain_knowledge.py         ← Domain-specific reasoning context
│   ├── state/                      ← SHARED STATE BUS (ephemeral, session-scoped)
│   │   ├── core.json               ← Live state — loops communicate here
│   │   └── core_manager.py         ← Read/write interface
│   ├── vision/                     ← VISION LAYER (how info reaches brain)
│   │   └── vision_layer.md         ← Design doc — read before adding new inputs
│   └── voice/
│       └── voice_concept.md        ← How Hayeong chooses to communicate
│
├── Toolbox/                        ← CONTROL LAYER (what she can do)
│   ├── registry.json               ← Tool registry — maps tool names to modules
│   ├── plugin_registry.py          ← Auto-discovers and ticks plugins
│   ├── minecraft/                  ← Minecraft bot (Python bridge + hayeong_bot.js)
│   ├── voice/                      ← Voice I/O (Whisper STT, Kokoro TTS, F5-TTS)
│   ├── blender/                    ← Blender 3D generation and rendering
│   ├── comfyui/                    ← Image generation (7900 XTX via ComfyUI)
│   ├── web/                        ← Web search (DuckDuckGo)
│   ├── music/                      ← Music generation pipeline
│   ├── gaming/                     ← Gaming awareness (BO3 memory reader, gamepad)
│   ├── email/                      ← Email monitoring and sending
│   ├── script/                     ← General script execution
│   ├── dev/                        ← Self-development tool (file creation/editing)
│   ├── handoff_reader/             ← Reads .md handoff files and implements them
│   ├── self_check/                 ← Verifies handoff implementations
│   ├── sensor_tool/                ← System sensors (GPU, CPU, temp)
│   ├── finetune_curator/           ← Curates conversation logs for fine-tuning
│   ├── ffmpeg/                     ← Video/audio processing
│   ├── vision_tools/               ← Screen observation (screen_observer, vision_bridge)
│   └── calendar_manager/           ← Calendar management
│
├── Memory/                         ← PERSISTENT MEMORY (across sessions)
│   ├── long_term_memory.py
│   ├── working_memory.py
│   ├── finetune_logger.py
│   ├── chroma_db/                  ← Vector memory store
│   └── knowledge/toolknowledge/    ← Domain knowledge files
│
├── Dashboard/                      ← READ-ONLY OBSERVER (never affects Hayeong)
│   ├── dashboard_server.py
│   └── dashboard_tui.py
│
└── logs/
    ├── conversations/              ← FINE-TUNING DATA — NEVER DELETE
    ├── handoffs/                   ← Handoff notes from James/Claude → Hayeong
    ├── notes/roadmap/              ← Architecture decisions, design docs
    ├── sessions/                   ← Runtime session records
    └── outputs/                    ← Things Hayeong creates
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

- Tools NEVER crash main. All exceptions must be caught and returned as `[ERROR] ...`
- Tools NEVER write directly to Brain state — they return a string result
- The task loop in main.py writes the result to `what_happened` in shared state
- The brain reads `what_happened` on the next reasoning cycle

**To register a new tool**, add an entry to `Toolbox/registry.json`:
```json
"tool_name": { "module": "toolbox.tool_name.tool_name", "function": "run" }
```
This is the ONLY registration step needed.

---

## Plugin Contract — For Tools With Continuous State

A plugin provides heartbeat context to Hayeong's brain every tick. If a tool has ongoing state Hayeong should always be aware of (e.g. Minecraft bot position, ComfyUI queue status), it needs a plugin.

```python
# Toolbox/tool_name/plugin.py
def tick() -> dict:
    """Returns a dict injected into Hayeong's context every presence loop cycle."""
    return {
        "status": "...",
        "relevant_info": "..."
    }
```

The plugin registry auto-discovers `plugin.py` files — no registration needed beyond the file existing.

---

## Adding a New Tool — Pre-Implementation Checklist

Answer these before writing any code:

- [ ] **Which layer?** Brain (cognition) / Vision (perception) / Toolbox (action)?
- [ ] **Does main.py need to change?** Almost always: NO.
- [ ] **What does run() return?** Define the return string format.
- [ ] **Does it need a plugin?** Does it have continuous state the brain should always see?
- [ ] **What vision does it provide?** What state slot does new info flow through?
- [ ] **Is it registered?** Add entry to `Toolbox/registry.json`.
- [ ] **Is it hot-swappable?** Can it be updated while Hayeong runs?

---

## What Is Off-Limits — Do Not Touch Without Explicit Instruction

| File / Folder | Why |
|---|---|
| `Brain/identity.json` | Constitutional — who Hayeong is |
| `Brain/state/core.json` schema | Changing the schema breaks all loops |
| `logs/conversations/` | Fine-tuning data asset — sacred, never delete |
| `Memory/chroma_db/` | Vector store — never manually edit |

---

## Handoff Workflow

**Two kinds of handoffs exist:**

1. **Claude Code handoffs** (infrastructure, main.py, registry.json) — given directly to Claude Code as `.md` files. Claude Code implements them.

2. **Hayeong handoffs** (all Toolbox/* tools) — dropped in `logs/handoffs/` with `FILE:` markers. James tells Hayeong to implement them via `handoff_reader`. This lets Hayeong build her own tools.

**Handoff file format for Hayeong (FILE: marker format):**
```
FILE: Toolbox/tool_name/tool_name.py
\`\`\`python
# code here
\`\`\`
```

**When Claude Code gets a handoff note:**
1. Read the note fully before writing any code
2. Check the layer classification — does this touch the right layer?
3. Verify main.py really needs to change (if the note says so)
4. Implement, then confirm what files were created/modified

---

## Key Technical Facts

- Python imports use lowercase `brain.` and `toolbox.` (not `Brain.` / `Toolbox.`)
- `Brain/config.py` is the single source of truth — always import from there, never hardcode paths or ports
- Ollama instances: port 11435 (Qwen 32b — main brain), port 11436 (DeepSeek — on-demand)
- Voice: Whisper (STT) → Kokoro TTS primary, F5-TTS fallback — both CUDA-only
- Minecraft: mineflayer bot (`hayeong_bot.js`) + Python bridge (`minecraft_bridge.py`) + state at `Toolbox/minecraft/state/minecraft_state.json`
- ComfyUI at `http://127.0.0.1:8188` — workflows in `Toolbox/comfyui/workflows/`
- Blender at `H:/blender/blender.exe`
- GPU allocation: RTX 3090 = LLMs only. RX 7900 XTX = ComfyUI/Blender/music/gaming only. These must NEVER cross.
- ROCR_VISIBLE_DEVICES and HIP_VISIBLE_DEVICES must be empty in Ollama bat files (prevents AMD from stealing LLM workload)

---

## Current Tool Registry (as of May 2026)

`minecraft`, `voice`, `email`, `blender`, `script`, `music`, `dev`, `comfyui`, `ffmpeg`, `handoff_reader`, `self_check`, `sensor_tool`, `finetune_curator`, `web_search`, `file_manager`, `gaming`

---

## Design Principles — These Guide Every Decision

1. **The brain decides, tools execute.** Never hardcode a decision that the LLM should be making.
2. **main.py is the last thing that changes.** New capabilities extend Toolbox and Brain, not the core loop.
3. **Hayeong should be able to update herself.** Tools go in Toolbox so she can modify them via the dev tool.
4. **Identity coherence under growth.** Hayeong grows without changing who she is.
5. **State is the bus.** Loops communicate through `Brain/state/core.json`, never by calling each other.
6. **GPU allocation is sacred.** 3090 = LLMs. 7900 XTX = creative compute. No crossover.
