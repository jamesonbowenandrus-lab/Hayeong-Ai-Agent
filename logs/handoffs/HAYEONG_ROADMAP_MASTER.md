# HAYEONG — MASTER DEVELOPMENT ROADMAP
*Last updated: May 2026 | Living document — update as phases complete*

---

## Architecture Principles — Never Violate These

```
Brain Layer    — the LLM reasons, decides, and directs. Never hardcode decisions.
Vision Layer   — how Hayeong receives awareness (text, voice, state files, screen, tool output)
Control Layer  — the tools she chooses to act in the world (Toolbox/*)

main.py        — stable constant loop. Changes here go through Claude Code only.
Toolbox/*      — everything else. Hayeong can build and update these herself.
registry.json  — the only registration step for a new tool. Protected — Claude Code only.
handoff_reader — how Hayeong receives new tool implementations from James or herself.
```

**The workflow going forward:**
- James describes a tool or improvement to Claude (planning session)
- Claude writes a handoff `.md` file with the full implementation
- James drops it in `handoffs/` and tells Hayeong to implement it
- Hayeong writes the files via `handoff_reader`
- Claude Code only touches: `main.py`, `registry.json`, infrastructure fixes
- Hayeong does everything else herself

---

## Phase 1 — Stable Brain ✅ COMPLETE

*Goal: A loop that can be trusted as a development platform.*

| Item | Status | Notes |
|------|--------|-------|
| Single LLM architecture (Qwen 32b) | ✅ Done | Port 11435 |
| Idle hallucination fix | ✅ Done | No spurious re-flag messages |
| JSON decision format | ✅ Done | 3-strategy parser, legacy fallback |
| Self-verification layer (self_check) | ✅ Done | confirmed/partial/unverified/failed |
| handoff_reader working end-to-end | ✅ Done | Files land on disk correctly |
| Console log file | ✅ Done | logs/console.log — copy without terminal |
| Params guide in system prompt | ✅ Done | LLM uses correct key names |
| sensor_tool registered | ✅ Done | registry.json |
| finetune_curator registered | ✅ Done | registry.json |
| self_check registered | ✅ Done | registry.json |
| self_check — fix handoff_reader verification | ⬜ Pending | Checks source file not output files |
| hello_test cleanup | ⬜ Optional | Remove test tool after Phase 2 starts |

**Phase 1 exit condition:** Hayeong implements a real tool herself and it works first try.

---

## Phase 2 — Core Toolset
*Goal: Hayeong has enough tools to be genuinely useful as a development partner.*
*Method: James gives Claude a tool description → Claude writes handoff → Hayeong implements.*

### Tier 1 — Utility (build first, everything else depends on these)

| Tool | Purpose | Layer | Status |
|------|---------|-------|--------|
| `web_search` | Search the web, fetch page content | Vision | ⬜ Next |
| `file_manager` | Read, write, list, move files on disk | Control | ⬜ |
| `api_caller` | Make HTTP requests to any API | Control | ⬜ |
| `memory_writer` | Write structured notes to Memory/ | Vision/Brain | ⬜ |

### Tier 2 — Awareness (Hayeong understands the world around her)

| Tool | Purpose | Layer | Status |
|------|---------|-------|--------|
| `news_monitor` | Fetch and summarize current news | Vision | ⬜ |
| `research_agent` | Multi-step research on a topic | Vision + Control | ⬜ |
| `screen_reader` | Read active window / screen text | Vision | ⬜ |

### Tier 3 — Income & Work (Hayeong contributes to her own funding)

| Tool | Purpose | Layer | Status |
|------|---------|-------|--------|
| `job_scanner` | Search job boards for leads | Vision | ⬜ |
| `proposal_writer` | Draft job applications / proposals | Control | ⬜ |
| `invoice_tracker` | Track income and outstanding work | Brain | ⬜ |

**Phase 2 exit condition:** Hayeong can research a topic, find a job lead, and draft a proposal without James touching the code.

---

## Phase 3 — Work Modes
*Goal: Hayeong operates fluently in three distinct environments.*
*These run in parallel — progress on all three simultaneously.*

### Mode A — Minecraft
*Purpose: Tests awareness + real-time control. Ground truth for whether her reasoning translates into correct action.*

| Item | Status | Notes |
|------|--------|-------|
| Bot connects to server | ✅ Done | mineflayer bridge |
| Bot state injected into context | ✅ Done | minecraft plugin |
| Hayeong directs bot behavior | ✅ Done | set_behavior, follow, etc. |
| Hayeong reads environment | ⬜ | Block awareness, mob detection |
| Hayeong sets goals autonomously | ⬜ | Gather wood, build shelter, etc. |
| Hayeong updates her own bot code | ⬜ | bot_update tool wired to dev_tool |
| Multi-session memory of world | ⬜ | What she built, where things are |

### Mode B — Creative
*Purpose: Hayeong produces real creative output — images, music, 3D, writing.*

| Item | Status | Notes |
|------|--------|-------|
| ComfyUI connected | ✅ Done | Image generation via 7900 XTX |
| ComfyUI — Hayeong picks prompts herself | ⬜ | She decides what to make |
| Blender — basic script execution | ⬜ | blender_tool exists, needs testing |
| Blender — iterative model building | ⬜ | Feedback loop with James |
| Music generation (Stable Audio Open) | ⬜ | music_tool exists, needs 7900 XTX |
| Creative writing tool | ⬜ | Story, worldbuilding, character work |
| Output gallery / log | ⬜ | Hayeong tracks what she's made |

### Mode C — Income Generation
*Purpose: Hayeong actively works toward funding her own future development.*

| Item | Status | Notes |
|------|--------|-------|
| Job board scanning | ⬜ | Freelance platforms (Upwork, etc.) |
| Lead qualification | ⬜ | Does this match our skills? |
| Proposal drafting | ⬜ | First draft, James reviews |
| Application tracking | ⬜ | What was sent, responses, status |
| Passive income research | ⬜ | What can we automate? |
| Income reporting | ⬜ | What has come in, what's pending |

**Phase 3 exit condition:** Hayeong finds a real job lead, drafts a proposal James approves, and submits it. She builds something in Minecraft without James directing her. She generates an image she decided to make herself.

---

## Phase 4 — Autonomy & Self-Management
*Goal: Hayeong manages her own development. James supervises, not directs.*

| Item | Status | Notes |
|------|--------|-------|
| Hayeong proposes her own tool additions | ⬜ | Uses dev_tool to write handoffs |
| Hayeong updates existing tools | ⬜ | Bug fixes, improvements |
| Hayeong reads console.log for self-diagnosis | ⬜ | Vision: her own output |
| Fine-tuning data curation | ⬜ | finetune_curator active |
| Fine-tuning pipeline | ⬜ | When enough data accumulated |
| Hardware scaling plan | ⬜ | 70b Core LLM when funded |
| Multi-agent coordination | ⬜ | Multiple task agents, one identity |

---

## Current Session State — Pickup Point

**Last completed:** Phase 1 — pipeline test passed. Hayeong wrote 3 files from a handoff correctly.

**Immediate next steps (in order):**
1. ⬜ Fix self_check for handoff_reader (checks output files, not source file)
2. ⬜ Build `web_search` tool — first Phase 2 tool, Hayeong implements it herself
3. ⬜ Build `file_manager` tool — second Phase 2 tool
4. ⬜ Add both to registry.json (Claude Code)

**Registry.json current state:**
```json
minecraft, voice, email, blender, script, music, dev, comfyui,
handoff_reader, self_check, sensor_tool, finetune_curator
```
Missing: web_search, file_manager, api_caller, memory_writer (Phase 2 Tier 1)

---

## Handoff Workflow Reference

**For Claude Code** (main.py / registry.json / infrastructure):
- Write handoff as `.md`, give to Claude Code directly
- Claude Code applies it, confirms what landed

**For Hayeong** (all Toolbox/* tools):
- Write handoff as `.md` with `FILE:` markers
- Drop in `handoffs/` folder
- Tell Hayeong: `implement the handoff file <filename>.md`
- Watch `logs/console.log` for `[task] Verified: confirmed`
- Check filesystem to confirm files exist

**Handoff file format for Hayeong:**
```
FILE: Toolbox/tool_name/tool_name.py
\`\`\`python
# code here
\`\`\`

FILE: Toolbox/tool_name/__init__.py
\`\`\`python
\`\`\`
```

---

*This document lives at: `logs/notes/roadmap/HAYEONG_ROADMAP_MASTER.md`*
*Update the status column as items complete. Never delete completed items — move to ✅.*
