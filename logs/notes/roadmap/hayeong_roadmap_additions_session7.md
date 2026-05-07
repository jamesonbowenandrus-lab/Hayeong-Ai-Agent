# HAYEONG ROADMAP ADDITIONS — Session 7
*Session Date: April 22, 2026*
*Add these phases and milestones to HAYEONG_ROADMAP.md*

---

## MILESTONE UPDATES

Add to the milestone tracker:

| # | Milestone | Phase | Status |
|---|---|---|---|
| 81 | Two-LLM architecture implemented — 7b communication, 14b reasoning, clean role separation | 14 | 🔲 Pending |
| 82 | 7b repurposed as dedicated communication LLM — redundant routing removed | 14 | 🔲 Pending |
| 83 | 14b Q4_K_M confirmed as reasoning LLM — ~40% faster, 8GB saved vs Q8 | 14 | 🔲 Pending |
| 84 | Two Ollama instances configured — communication on one port, reasoning on another | 14 | 🔲 Pending |
| 85 | Shared state bus Stage 1 — JSON file connecting communication and reasoning LLMs | 11.2 | 🔲 Pending |
| 86 | Reasoning LLM confirmed as Minecraft controller — plans goals and issues actions | Gaming | 🔲 Pending |
| 87 | GPU split finalized — 3090 for all Hayeong core models, 7900 for creative compute and gaming | 5.0 | 🔲 Pending |
| 88 | Conversation data logging confirmed — saving for future fine tuning | Future | 🔲 Pending |
| 89 | Future architecture documented — hierarchical multi-LLM vision recorded | 15 | 🔲 Pending |
| 90 | Fine tuning infrastructure — first fine tune on 7b when sufficient data exists | Future | 💤 Deferred |
| 91 | Domain coordinator layer — mid-tier reasoning per domain (workstation era) | 15 | 💤 Deferred |
| 92 | Hive mind multi-agent Minecraft — reasoning LLM coordinating multiple bots | 15 | 💤 Deferred |
| 93 | Multi-agent scaling beyond Minecraft — creative, work, research domains | 15 | 💤 Deferred |

---

## PHASE 14 — TWO-LLM ARCHITECTURE (CURRENT SCALE)
*Priority: HIGH — implement now, foundation for everything above it.*
*This is the correct current-scale implementation of the larger vision.*

### 14.1 — Role Separation 🔲

Two models. Two jobs. Neither crosses into the other's role.

| Model | Role | Always On | Talks to James |
|---|---|---|---|
| Qwen 7b Q4_K_M | Communication — voice, speech, James-facing responses | Yes | Yes — only one that does |
| Qwen 14b Q4_K_M | Reasoning — planning, decisions, task execution, Minecraft | Yes | No — writes to shared state |

**The key design principle:**
The 14b never speaks directly to James. The 7b never reasons deeply about tasks. The 7b reads context from shared state that the 14b has written and delivers it in Hayeong's voice. The 14b reads conversation context from shared state that the 7b has written and uses it to inform reasoning.

They communicate through shared state — not directly.

### 14.2 — Communication LLM (Qwen 7b) 🔲

**What it does:**
- Receives everything James says
- Delivers all responses to James in Hayeong's voice
- Drives TTS — everything spoken comes through this model
- Reads shared state for context from reasoning LLM
- Flags to reasoning LLM when James says something that needs deeper thought
- Handles casual conversation, quick replies, emotional responses independently
- Does NOT make decisions about tasks, capabilities, or planning

**What it is NOT:**
- Not an intent classifier for the 14b (that was the old broken role)
- Not a router deciding which model to call
- Not a fallback — it is a dedicated role

### 14.3 — Reasoning LLM (Qwen 14b) 🔲

**What it does:**
- Receives flagged messages from communication LLM via shared state
- Plans and decides what Hayeong does and how
- Manages task queue — what needs attention and in what order
- Controls Minecraft bot — reads game state, reasons about goals, issues actions
- Monitors background tasks — scripts running, results coming in
- Writes conclusions and context to shared state for communication LLM to reference
- Does NOT speak directly to James — always routes through communication LLM

**Minecraft specifically:**
- Holds the overall goal ("find diamonds, build shelter before dark")
- Issues action instructions to the bot script
- Monitors game state and adjusts plan as needed
- The bot script handles mechanical execution — the 14b handles strategy

### 14.4 — Two Ollama Instances 🔲

Each model runs as a separate Ollama instance to allow independent GPU targeting and port separation.

```
Instance 1 — Communication (port 11434)
  Model: qwen2.5:7b-instruct-q4_K_M
  GPU: 3090 (CUDA device 0)
  Always loaded, never unloaded

Instance 2 — Reasoning (port 11435)
  Model: qwen2.5:14b-instruct-q4_K_M
  GPU: 3090 (CUDA device 0, same GPU — different instance)
  Always loaded, never unloaded
```

Both on the 3090. Both always loaded. Combined VRAM: ~12GB leaving ~12GB for TTS, Whisper, and headroom.

### 14.5 — Shared State Bus Stage 1 🔲

JSON file connecting the two LLMs. This is the minimum viable shared state — upgrades to threading and then message queue as scale demands.

**Minimum viable contents:**
```json
{
  "conversation": {
    "last_james_message": "",
    "last_hayeong_response": "",
    "current_topic": "",
    "flags": []
  },
  "reasoning": {
    "current_goal": "",
    "task_queue": [],
    "active_task": "",
    "last_conclusion": "",
    "minecraft_state": {}
  },
  "system": {
    "active_scripts": [],
    "pending_results": [],
    "priority_flags": []
  }
}
```

**Access pattern:**
- Communication LLM reads reasoning section, writes conversation section
- Reasoning LLM reads conversation section, writes reasoning section
- Both read system section, scripts write to system section

---

## PHASE 15 — FUTURE HIERARCHICAL ARCHITECTURE (WORKSTATION ERA)
*Priority: Documentation only — do not build yet.*
*Dependency: Workstation hardware, Phase 14 stable and proven.*

### 15.1 — Architecture Overview 💤 Deferred

The full vision for Hayeong at workstation scale. Phase 14 maps directly onto this — the two LLMs become the Core and Communication layers, Domain Coordinators and Task Agents are added underneath.

```
CORE REASONING LLM (70b — always loaded)
One coherent identity. Source of who Hayeong is.
Manages domain coordinators.
Only handles James-level decisions and cross-domain priorities.
Not involved in moment-to-moment execution.

COMMUNICATION LLM (small tuned — always loaded)
James-facing always. Reads shared state for full context.
Sounds like Hayeong regardless of what the Core is focused on.

DOMAIN COORDINATORS (14b each — always loaded per active domain)
Each owns a domain — Minecraft, Creative, Work, Research
Runs its own sub-queue independently
Reports to Core only when needed
Manages Task Agents within its domain

TASK AGENTS (7b each — on demand)
Loaded when a specific task starts, unloaded when done
Minecraft agent, Code agent, Vision agent, etc.
Competent within their domain without constant supervision
Report status to their Domain Coordinator

SCRIPTS AND TOOLS (always available, no VRAM)
Parallel execution — music gen, image gen, Blender, email
Orchestrated by Domain Coordinators
Results written to shared state

SHARED STATE BUS (Redis/ZeroMQ at this scale)
Every layer reads and writes here
Provides system-wide awareness without any single bottleneck
Each agent owns its own state slice — no write conflicts
```

### 15.2 — Hive Mind Multi-Agent System 💤 Deferred

One coherent Hayeong identity expressed through multiple simultaneous agents. Not separate instances — one mind, many hands.

**Core principle:**
The agents are not separate Hayeongs. They are Hayeong's hands. Identity, goals, and values flow from the Core LLM down to every agent. An agent has a task and the competency to execute it — not its own separate personality or relationship with James.

**Minecraft implementation:**
```
Core/Domain Coordinator holds mission:
"Cave exploring, find diamonds, build shelter before dark,
 music generation running for atmosphere"

Agent 1 — gathering materials (mining)
Agent 2 — building shelter at base
Agent 3 — guard/escort following James
Agent N — additional task as needed

Each agent:
- Competent to execute its task without constant supervision
- Writes status to shared state continuously
- Flags urgent needs upward to Coordinator
- Receives goal updates from Coordinator when mission changes

Coordinator:
- Monitors all agent status streams
- Reallocates agents when priorities shift
- "Agent 2 overwhelmed — redirect Agent 1 to assist"
- Reports to Core only when cross-domain decision needed
```

**Scales beyond Minecraft:**
Same pattern applies to creative work, research, coding projects, content creation. Multiple specialized agents coordinated by one coherent intelligence.

### 15.3 — Priority Queue System 💤 Deferred

The reasoning layer manages everything through a structured queue — not random attention.

```
URGENT — interrupts current reasoning immediately
  (James says something critical, health critical in game,
   system alert requiring immediate response)

HIGH — addressed at next heartbeat
  (Minecraft needs next goal instruction,
   script completed and needs follow-up decision)

NORMAL — addressed in regular cycle
  (Background task status check,
   email monitoring, scheduled review)

BACKGROUND — addressed when nothing else is pending
  (Long term planning, self improvement thinking,
   proactive ideas to surface to James)
```

### 15.4 — Fine Tuning Path 💤 Deferred

**When:** After sufficient conversation data accumulated — minimum several months of daily use.

**What to save now:**
- Full conversation logs (both sides — James and Hayeong)
- Moments where her response felt exactly right (flag these)
- Moments where she felt off (flag these too — negative examples matter)
- Task execution logs — what she did and whether it succeeded

**Fine tuning order:**
1. Fine tune 7b first — communication model, shapes voice and personality
2. Apply same data to 14b — reasoning model gets her patterns too
3. When workstation arrives — retrain on 70b with accumulated data, or use LoRA transfer as head start

**Key principle:**
The conversation data is the asset. The model it's applied to is just the vessel. Save everything now. Apply it to whatever hardware exists at the time.

---

## GPU SPLIT — FINALIZED
*Update the hardware section of HAYEONG_ROADMAP.md*

```
RTX 3090 (24GB CUDA) — Hayeong's core, all primary models
├── Qwen 7b Q4_K_M — communication LLM (~4GB)
├── Qwen 14b Q4_K_M — reasoning LLM (~8GB)
├── Kokoro TTS — voice output (~2GB)
├── Whisper — voice input (~2GB)
└── Headroom: ~8GB

RX 7900 XTX (24GB AMD) — creative compute and gaming
├── Vision models — moondream (~2GB), LLaVA (~9GB) on demand
├── Stable Audio Open — music generation (~10GB) on demand
├── Stable Diffusion XL / Flux — image generation on demand
├── Blender rendering — GPU accelerated via HIP
├── Future 3D generation models on demand
└── James's games — always free, no competition from Hayeong
```

**Design principle:**
Nothing from Hayeong's core permanently occupies the 7900. Creative and vision models load on demand, unload when done. James's games always have full 7900 access.