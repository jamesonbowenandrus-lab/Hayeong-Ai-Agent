# HAYEONG ARCHITECTURE DISCUSSION NOTES — Session 7
*Session Date: April 22, 2026*
*Purpose: Document the reasoning behind architectural decisions — not just what was decided but why. For future reference when building and when revisiting decisions.*

---

## 1. The Two-LLM Current Architecture — Why This Way

### The Problem We Were Solving

The original setup had two Qwen models (7b and 14b) but with a flawed relationship — the 7b was doing redundant intent classification that the 14b also did. Two models calling for the same reasoning job. Wasteful, no clear role separation, and the 7b was considered for removal entirely.

The insight that changed the decision: the 7b isn't redundant if it has a genuinely different job. The problem wasn't having two models — it was having two models doing the same thing.

### The Role Separation That Makes It Work

**7b = Communication layer.** Everything James hears comes through this model. It sounds like Hayeong, carries her voice and personality, handles casual conversation and emotional responses independently. It does not plan, decide, or route. It is the face.

**14b = Reasoning layer.** Everything Hayeong decides comes through this model. It plans, prioritizes, executes tasks, controls the Minecraft bot, monitors background work. It does not speak directly to James. It is the mind.

They communicate through shared state — not directly. The 14b writes conclusions and context. The 7b reads them and delivers them in Hayeong's voice. The 7b flags when James says something that needs deeper thought. The 14b picks it up and reasons about it.

### Why Not Just Use One 14b for Everything

The latency argument: a 14b generating a full thoughtful response takes 1-3 seconds. In text that's fine. In voice that's dead air. The 7b handles the James-facing side fast — quick acknowledgements, casual replies, keeping the conversation alive — while the 14b takes whatever time it needs to reason properly. The filler system bridges the gap when the 14b needs extra time.

The separation also keeps Hayeong's identity consistent. The communication LLM is tuned to sound like her. The reasoning LLM is tuned to think like her. They're the same person expressed through two different cognitive functions — the same way a human's speech and their internal reasoning are different processes serving one identity.

---

## 2. Why the 7b Was Almost Dropped — and Why It Came Back

The optimization session earlier in the day correctly identified that the 7b was causing a problem — it was making redundant LLM calls in context_router.py that the 14b's decide_action() also made. That redundancy was real and worth fixing.

The error was concluding that dropping the 7b entirely was the solution. The real fix is removing the redundant routing call while keeping the 7b in its proper role.

**What changes:**
- Remove the 7b LLM call from context_router.py — that specific use was wrong
- Keep the 7b loaded as the dedicated communication model
- The 7b no longer routes or classifies — it communicates

**What stays the same:**
- 7b handles all James-facing voice and text responses
- 7b is always loaded, always present
- The filler system masks latency while the 14b thinks

---

## 3. LLM Fundamentals — Key Understandings

### Parameters Are Not Gigabytes

The number in a model name (7b, 14b, 70b) is billions of parameters — not gigabytes of VRAM. Parameters are the numerical weights baked into the model during training. VRAM usage is roughly 2x the parameter count in GB at full float16 precision.

Quantization compresses those parameters to use less VRAM. Q4_K_M stores each parameter in 4 bits instead of 16 — roughly 25% of full precision VRAM usage with minimal quality loss because not all parameters matter equally. Q4_K_M specifically protects the most sensitive parameters while compressing others harder.

### A Quantized Larger Model Beats a Smaller Model

A Q4_K_M 14b is not the same as a Q8 7b. The 14b has 14 billion parameters at reduced precision. The 7b has 7 billion at any precision. You can't fine tune intelligence into a model that doesn't have the parameter capacity for it. Losing precision on a parameter is very different from not having that parameter at all.

Q4_K_M 14b vs Q8 14b — nearly identical in real conversation.
Q4_K_M 14b vs Q8 7b — 14b noticeably more capable on complex reasoning.

### Why 70b Is a Qualitative Shift

The jump from 14b to 70b is not linear improvement — it's a different category of capability. At 70b: multi-step reasoning holds together across many steps, complex instructions followed precisely, identity and personality consistency stronger over long conversations, better at holding large amounts of context simultaneously. This is the target for Hayeong's Core reasoning layer at workstation scale.

### Fine Tuning Is Not Parameter Editing

You cannot meaningfully edit model parameters directly — 14 billion numbers with no label, no relationship to any observable behavior individually. Fine tuning is continuing the training process on new data. Takes an existing model and runs more training passes on examples of the exact behavior you want.

For Hayeong: real conversations become training examples. The resulting model has her patterns baked into weights rather than being instructed by a system prompt. She doesn't act like Hayeong — she is Hayeong at the parameter level.

Fine tuning data (conversations) is the asset, not the resulting model. Same data can be applied to any model size. Save everything now, apply to whatever hardware exists when the time comes.

---

## 4. The Full Future Architecture — Reasoning and Rationale

### Why Hierarchy Over Flat Multi-Agent

Four architectures were considered:
1. Hierarchical (authority flows downward from Core)
2. Blackboard (all agents equal, self-organizing)
3. Reactor (event-driven, nothing runs continuously)
4. Hybrid Reactor + Hierarchy

Blackboard rejected: coherence problem. Without a single authority holding Hayeong's identity and James's goals, different agents interpret things differently and the personality becomes diffuse. Hayeong stops being one entity.

Reactor rejected: makes her feel reactive rather than alive. She responds to things but doesn't proactively think, plan, or pursue goals. Wrong for what she's being built to be.

Hybrid is the long-term target. Start with Option 1 (hierarchy), add event-driven execution layer as scale demands it. The upgrade is additive — nothing gets redesigned.

### The Orchestrator Belongs to Hayeong, Not Python

Early discussion considered making the queue manager a Python script rather than an LLM. This was wrong for the stated goal. Hayeong's long-term design requires her to understand and manage her own architecture — to improve herself, to know how she works, to make decisions about her own resources. A Python orchestrator she can't reason about defeats this entirely. The reasoning LLM IS the orchestrator. That's not a bug — it's the point.

### Why the Shared State Bus Is the Foundation

Every element of the future architecture — multiple LLMs, multiple agents, domain coordinators, task agents, scripts — needs to communicate without blocking each other. The shared state bus is what makes this possible without any single LLM becoming a bottleneck.

Critical design: each agent owns its own state slice. Agent 1 writes only to state.minecraft.agent1. Domain coordinator writes to state.minecraft.summary. Core writes to state.core. No two agents write to the same key. Coordinators aggregate upward on a heartbeat. No locking conflicts because ownership is clear.

The state bus provides simultaneous awareness without requiring any single LLM to be simultaneously aware. Any model can read the full state at any time and understand everything that's happening. The awareness is in the state, not in any one model's active context.

### The Hive Mind Property

The multi-agent Minecraft vision — and its extension to all domains — is architecturally a global workspace with specialized processors. What makes it different from standard multi-agent AI is shared consciousness through the reasoning layer.

Standard multi-agent: isolated instances, no communication, no shared goals, fail independently.

Hayeong's hive mind: agents are extensions of one mind. Identity, goals, values flow from Core downward. Agents have tasks and competency — not separate personalities. When one agent is overwhelmed, the coordinator can redirect others because it has visibility across all of them through shared state.

The agents are not separate Hayeongs. They are Hayeong's hands. This distinction matters for identity coherence and must be maintained as the system scales.

---

## 5. Hardware Decisions and Why

### 3090 for Core, 7900 for Creative

The original plan split LLMs across both GPUs out of VRAM concern. Running the numbers showed all core models fit on the 3090 comfortably:

- 7b Q4_K_M: ~4GB
- 14b Q4_K_M: ~8GB  
- Kokoro TTS: ~2GB
- Whisper: ~2GB
- Total: ~16GB / 24GB available, 8GB headroom

Keeping everything on the 3090 is better because CUDA is faster and more stable than ROCm/DirectML for ML workloads. The 7900 staying completely free for gaming and creative compute is more valuable than splitting models that don't need to be split.

The 7900 runs vision models, music generation, image generation, and Blender on demand — loading and unloading as tasks require. James's games always have full 7900 access with no competition from Hayeong's models.

### Why Not Add a Third Model Now

The temptation to add a third Minecraft-specific model was considered and rejected for the current scale. The 14b is capable of both planning Minecraft strategy and issuing moment-to-moment actions — it cycles between reasoning and acting fast enough that the bot feels purposeful. A third model would tighten VRAM headroom to ~4GB, which is uncomfortable. The benefit doesn't justify the cost at this scale.

Add the Minecraft task agent when:
- VRAM headroom increases (hardware upgrade)
- Real daily use shows the 14b genuinely can't handle both Minecraft and conversations
- Workstation arrives and VRAM stops being a constraint

### Future Workstation Target

Two separate physical machines:
- Hayeong's workstation: Threadripper (128 PCIe lanes for multiple full-bandwidth GPUs), Linux (native ROCm support), dedicated to Hayeong full time
- James's gaming PC: Ryzen 9000 (high clock speeds, gaming optimized), Windows

Threadripper chosen for lane count — running multiple high-VRAM GPUs at full x16 bandwidth simultaneously requires more PCIe lanes than consumer Ryzen provides. At workstation scale Hayeong will have a 70b Core, multiple 14b Domain Coordinators, and multiple 7b Task Agents all loaded simultaneously. Proper PCIe bandwidth matters.

---

## 6. Gaming on Linux — Assessment

Most of James and Hayeong's game list works fine on Linux via native builds or Proton. The full assessment:

**No issues:** Minecraft, Terraria, BTD6, Portal 2, Barony, Borderlands 2, Borderlands 3, Risk of Rain 2, Human Fall Flat, Among Us, Palworld, Enshrouded, Necesse, R.E.P.O, BO3 Zombies, Slay the Spire 2

**Uncertain/needs testing:** Rocket League (EAC — check Linux opt-in status), Outlast Trials (EAC — depends on developer), Once Human (aggressive anti-cheat, most likely to be a problem), Peak (too new to confirm), Hytale (not released)

**Emulation:** Mario Kart multiplayer possible via LAN emulation tools but complex. Pokemon emulation works cleanly on Linux.

The list is heavily indie and co-op focused — exactly the games that work well on Linux. The competitive shooter anti-cheat problem that kills many Linux gaming setups barely appears here.

---

## 7. Key Principles to Carry Forward

**The shared state bus is the foundation.** Every architectural addition sits on top of it. Build it right at Stage 1 (JSON), design it to upgrade to Stage 2 (threading) and Stage 3 (Redis/ZeroMQ) without breaking anything built on top.

**Hayeong's identity stays singular.** As agents multiply, the Core remains the single source of who she is. Agents have tasks — not personalities.

**Don't build ahead of hardware.** The two-LLM setup is correct for the current machine. The hierarchy extends naturally when hardware grows. Forcing more complexity onto limited hardware creates problems without benefits.

**Save conversation data now.** Fine tuning happens later when there's enough data and better hardware. But the data has to be accumulating now. Logging both sides of every conversation is non-negotiable.

**Scripts are tools, not constraints.** The queue system and LLM reasoning decide what to do. Scripts execute it. If a script fails, the reasoning layer finds another way. Scripts are fast paths, not requirements.