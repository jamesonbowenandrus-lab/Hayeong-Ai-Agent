# Hayeong — Vision Layer (Brain)

## What This Is

This folder represents the abstract vision layer — how Hayeong
understands and maintains awareness of her own state across all domains.

This is distinct from vision_tools\ in the toolbox, which contains
the technical implementations (vision models, screen observers, bridges).

## What Vision Means For Hayeong

Vision is not just seeing a screen. It is how Hayeong knows:
- Her state in games (position, health, inventory, surroundings)
- Her state in creative work (what is rendering, what has been produced)
- Her state in income generation (what assets exist, what is listed)
- Her state in development (what is running, what has errors)
- Her state in her own code and processes

## Current State

In the current phase, vision is primarily handled through:
- Minecraft server packets (structured data — no vision model needed)
- Tool result strings written to shared state
- Reasoning loop reading what_happened

## Workstation Era

When the workstation arrives, this layer expands significantly:
- Continuous lightweight vision model for screen awareness
- Domain-specific state monitors (one per active domain)
- Hayeong maintaining real awareness of multiple simultaneous contexts

## Context Assembly

Each reasoning cycle, the brain assembles a context block from all active
input sources before passing it to the LLM. This is the current implementation:

**Sources injected each cycle:**
- `Brain\state\core.json` — active task, loop phase, current mood
- Plugin context injections — each active plugin with a `get_context_injection()`
  method adds a labelled block (e.g. `[Gaming — BO3 Zombies]`, Minecraft state)
- Tool result from the previous cycle — what happened, whether it verified
- Memory recall — semantically relevant memories retrieved from ChromaDB

**Assembly point:** `main.py:build_presence_context()` and `build_presence_system()`
combine these into the system prompt + user message passed to the reasoning LLM.

**Key principle:** context assembly is additive and graceful — a missing plugin,
stale state file, or empty memory recall degrades quality but never crashes the loop.
Each source is read defensively with a fallback to empty/default.

## Implementation Notes

The Brain\vision\ folder will contain the coordination logic —
what Hayeong does with what she perceives.
The Toolbox\vision_tools\ folder contains the perception mechanisms.
These are intentionally separate.
