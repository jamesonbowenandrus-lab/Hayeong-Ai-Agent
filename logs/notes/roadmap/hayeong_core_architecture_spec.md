# HAYEONG — CORE ARCHITECTURE SPEC
*This is the design document. Not a handoff note. Not code.*
*Everything built for Hayeong should be measured against this.*
*If a proposed addition doesn't fit cleanly into this structure, it's wrong.*

---

## The Guiding Principle

Hayeong is an identity. Her capabilities are tools.

A broken tool does not break Hayeong. A broken Minecraft bridge does not
affect her ability to think or speak. A failed email connection does not
stall her reasoning. Tools are pencils. Hayeong is the hand.

The core system — reasoning, communication, task execution, shared state —
must be completely insulated from tool failures. Tools are called, they
return results or errors, they go away. Main never crashes because a tool
did.

---

## Main Contains Exactly Four Things

```
┌─────────────────────────────────────────────────────┐
│                      MAIN                            │
│                                                      │
│   Reasoning Loop     Communication Loop   Task Loop  │
│   (DeepSeek R1)      (llama3.2)           (phi3:mini)│
│        │                   │                  │      │
│        └───────────────────┴──────────────────┘      │
│                            │                         │
│                     Shared State                     │
│                    (state/core.json)                 │
└─────────────────────────────────────────────────────┘
```

Nothing else belongs in main. No managers. No monitors. No auto-starting
services. No email connections. No backup systems. No health checkers.
Those are tools — they live outside main and are called when Hayeong
decides to use them.

---

## The Three Loops

### Reasoning Loop — DeepSeek R1 (port 11435)

**One job: think.**

```
while running:
    read shared state
    think about what is happening and what to do
    write conclusions to shared state
    sleep 60 seconds
    repeat
```

Reads from:
- WHO SHE IS section (identity, mood, relationship with James)
- WHAT HAPPENED section (task results, tool outputs, errors)
- James's input queue

Writes to:
- WHAT SHE KNOWS section (conclusions, context for communication)
- WHAT SHE'S DOING section (task assignments for task loop)

Rules:
- Never calls the communication LLM directly
- Never calls tools directly
- Never blocks waiting for a result — assigns and moves on
- Runs on its own heartbeat regardless of whether James is talking
- When something goes wrong in a tool, it reads the error and decides
  what to do — it does not crash, it reasons

---

### Communication Loop — llama3.2 (port 11434)

**One job: talk to James.**

```
while running:
    wait for James's message
    read shared state (WHO SHE IS + WHAT SHE KNOWS)
    respond naturally
    write James's message to input queue
    repeat
```

Reads from:
- WHO SHE IS section
- WHAT SHE KNOWS section (what reasoning LLM has concluded)
- James's messages

Writes to:
- James's output queue (responses)
- Nothing else

Rules:
- Never calls the reasoning LLM directly
- Never calls the task LLM directly
- Never makes tool calls
- Responds only from what is in shared state
- If something isn't in shared state, she says she doesn't know
- Never guesses about system status — reads state or says unknown
- Runs independently — does not wait for reasoning LLM to finish thinking

---

### Task Loop — phi3:mini (port 11436)

**One job: execute what reasoning decided.**

```
while running:
    check WHAT SHE'S DOING section
    if task assigned:
        call the appropriate tool
        write result to WHAT HAPPENED section
        clear the task assignment
    sleep 2 seconds
    repeat
```

Reads from:
- WHAT SHE'S DOING section (task type, description, parameters)

Writes to:
- WHAT HAPPENED section (results, errors, status)

Rules:
- Only executes tasks that have concrete actions attached
- Never receives vague meta-tasks ("identify priorities", "manage system")
- If a task has no corresponding tool, writes "no tool available" to results
- Never auto-assigns tasks to itself
- A tool failure is written as a result, not a crash
- In the future: may coordinate multiple sub-agents, but role stays the same

---

## Shared State — Four Sections

File: `state/core.json`

```json
{
  "who_she_is": {
    "name": "Hayeong",
    "mood": "present",
    "energy": 5,
    "relationship_note": "James is building me. We are working together.",
    "core_traits": ["curious", "warm", "direct", "honest about uncertainty"]
  },

  "what_she_knows": {
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
  }
}
```

**Ownership rules — strictly enforced:**

| Section | Written by | Read by |
|---------|-----------|---------|
| who_she_is | Nobody during session — set at design time | All three loops |
| what_she_knows | Reasoning loop | Communication loop |
| what_shes_doing | Reasoning loop | Task loop |
| what_happened | Task loop | Reasoning loop |

No loop writes to a section it doesn't own.
No loop reads a section it doesn't need.

---

## Tools — Completely Separate

Tools live in `H:\hayeong\tools\`. They have no knowledge of main.
They do not import from main. They do not write to shared state directly.
They take inputs, do a job, return a result or an error. That's all.

```
tools/
├── minecraft_bridge.py    — connects bot to server, returns status
├── voice_server.py        — TTS and STT, returns transcriptions/audio
├── email_bridge.py        — sends/reads email, returns results
├── vision_call.py         — calls moondream, returns description
└── [future tools]
```

The task loop calls tools. Tools return results. The task loop writes
results to WHAT HAPPENED. The reasoning loop reads WHAT HAPPENED and
decides what to do next.

**A tool cannot:**
- Write directly to shared state
- Start other tools
- Call any LLM
- Crash main

**A tool can:**
- Return a success result
- Return an error result
- Take time (task loop waits, but only task loop waits)

---

## Startup Sequence

```
1. Infrastructure (scripted — not Hayeong's decision):
   - Ollama port 11434 starts (communication LLM)
   - Ollama port 11435 starts (reasoning LLM)
   - Ollama port 11436 starts (task LLM)
   - Models warm up

2. Hayeong wakes up:
   - Shared state loads
   - Reasoning loop starts
   - Communication loop starts
   - Task loop starts

3. Hayeong decides from this point:
   - Does she want voice? She starts voice_server.py
   - Does she want email monitoring? She starts email_bridge.py
   - What was she doing? She reads WHAT HAPPENED and reasons about it
   - What does James need? She prepares WHAT SHE KNOWS
```

The startup log should be short:
```
✅ Ollama 11434 ready
✅ Ollama 11435 ready
✅ Ollama 11436 ready
✅ Hayeong is ready
```

Nothing else.

---

## How a Conversation Works

```
James: "Hey Hayeong, can you join the Minecraft server?"

Communication loop:
  - Receives message
  - Reads WHO SHE IS + WHAT SHE KNOWS
  - Responds: "Sure, starting the bridge now."
  - Writes message to input queue

Reasoning loop (next tick):
  - Reads James's message from input queue
  - Decides: this needs minecraft_bridge tool
  - Writes to WHAT SHE'S DOING:
      task_type: "minecraft"
      task_description: "Join localhost:25565 as Hayeong"
      task_params: {host: "localhost", port: 25565, version: "1.21.4"}

Task loop (2 second tick):
  - Reads WHAT SHE'S DOING
  - Calls tools/minecraft_bridge.py with params
  - Bridge connects (or errors)
  - Writes to WHAT HAPPENED:
      last_result: "Bot connected successfully"
      last_tool: "minecraft_bridge"
      tool_status: {minecraft: "connected"}

Reasoning loop (next tick):
  - Reads WHAT HAPPENED
  - Concludes: Minecraft is running
  - Writes to WHAT SHE KNOWS:
      context_for_james: "Minecraft bridge is up, bot is connected"

Communication loop:
  - Reads WHAT SHE KNOWS on next James message
  - Responds: "I'm in the server."
```

Clean. No Python managers making decisions. LLMs making decisions.

---

## How Tool Failures Work

```
Task loop calls minecraft_bridge.py
Bridge errors: ECONNRESET

Task loop writes to WHAT HAPPENED:
  last_error: "ECONNRESET connecting to localhost:25565"
  last_tool: "minecraft_bridge"
  tool_status: {minecraft: "failed"}

Reasoning loop reads WHAT HAPPENED:
  Sees the error
  Reasons: "ECONNRESET means server refused connection or version mismatch"
  Decides: check server status, try different version, or tell James
  Writes to WHAT SHE KNOWS:
    context_for_james: "Minecraft connection failed — ECONNRESET.
                        Server may not be running or version may not match."

Communication loop:
  Tells James what happened honestly
```

Hayeong is never stalled. She reads the error, reasons about it,
reports to James. Main keeps running.

---

## Heartbeat Interval

The reasoning loop does not use a fixed heartbeat. It uses a variable one
based on what is currently happening.

```
Active state (conversation happening, task running):
  Sleep 10-15 seconds between ticks

Idle state (James is away, nothing running):
  Sleep 60 seconds between ticks
```

The reasoning loop decides which state it is in by reading shared state.
If WHAT SHE'S DOING has an active task, or if James's last message was
recent, it ticks faster. If nothing is happening, it slows down to conserve
compute.

Too fast (under 5 seconds): reasoning model never finishes a thought before
starting the next one. Generates noise — vague tasks, redundant conclusions.

Too slow (over 60 seconds in active state): she feels absent. Tool failures
go unnoticed for too long. Not appropriate for a companion that is actively
present.

---

## Multiple Concurrent States

The reasoning loop handles multiple concurrent states naturally through the
shared state structure. It does not need parallel calls or separate threads
for each state. It reads everything in one pass and thinks holistically.

WHAT HAPPENED holds status for all running tools simultaneously:

```json
"tool_status": {
    "minecraft": "connected",
    "voice": "active",
    "email": "idle"
}
```

The task loop can hold a small queue rather than a single slot. The
reasoning model assigns multiple tasks, the task loop works through them,
results accumulate. The reasoning model reads all results on its next tick.

The reasoning model is sequential — one thought at a time. But one thought
can encompass many states. A single mind manages complexity this way.

---

## Creative Thought — Held Open Intentionally

The ability to make unexpected cross-domain connections — thinking about
one thing and finding a solution to something unrelated — is a recognized
goal for Hayeong's future development.

The architecture that enables this would likely be a background reasoning
instance with no assigned task. Not executing. Not communicating. Just
thinking freely. Reading accumulated knowledge and writing insights to
shared state for the other loops to use.

This is conceptually a fourth loop. It is not being implemented now because:
- VRAM constraints
- The design of what it reads and writes is not yet clear enough
- The current three loops need to be stable first

The current three-loop design is correct for now.
It is not definitive. It will grow as Hayeong grows.

A new loop is added only when its role is clearly distinct from existing
loops — meaning it cannot be served by any existing loop without
compromising that loop's primary function.

Creative reasoning fails that test today. It will pass when constraints
are resolved and the design becomes clear.

---

## Scaling — How This Grows

Right now:
```
Task loop → one tool at a time
```

Future (more VRAM, more hardware):
```
Task loop → coordinates multiple sub-agents
            each sub-agent is its own phi3:mini instance
            each handles one concurrent task
            all write to WHAT HAPPENED
            reasoning loop reads all results
```

The role of each loop never changes. Only their capacity grows.
Main stays the same. The shared state structure stays the same.
Tools stay separate.

This is why simplicity now matters — a simple design scales cleanly.
A complex design becomes unmaintainable.

---

## What Gets Removed From Current main.py

These things currently in main do not belong there:

| Thing | Where it goes |
|-------|--------------|
| Email monitor auto-start | Tool — called by task loop when reasoning decides |
| Backup auto-run | Tool — called by task loop when reasoning decides |
| Audit/rollback log | Tool — called by task loop when reasoning decides |
| Income/fund tracker | Knowledge in WHO SHE IS — not a running process |
| Health monitors | Reasoning loop reads tool status from WHAT HAPPENED |
| Intent classifiers | Reasoning LLM decides intent — no Python needed |
| Context verifier | Reasoning LLM verifies — no Python needed |
| App manager | Task loop calls tools directly — no manager needed |
| Capability registry | Reasoning LLM knows what tools exist — listed in WHO SHE IS |

---

## The Measure of Correctness

Before any code is written or changed, ask:

1. Does this belong in main, or is it a tool?
2. Which loop owns this? Does it write only to its section?
3. If this breaks, does Hayeong keep running?
4. Is an LLM making this decision, or is Python making it?
5. Could this be simpler?

If the answer to question 3 is no, the design is wrong.
If the answer to question 4 is Python, the design is probably wrong.
If the answer to question 5 is yes, make it simpler first.