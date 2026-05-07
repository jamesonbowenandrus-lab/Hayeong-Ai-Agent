# HAYEONG ROADMAP — PHASE 14: CREATIVE PRODUCTION PIPELINE
## Game Modding → Game Creation → Animated Film → Cinematic
*Session Date: April 23, 2026*
*Type: Roadmap document — planning only, not a Claude Code handoff*
*Depends on: Phase 3 (Blender), Phase 11 (Three-Layer Architecture), Phase 13 (Outcome Verification)*

---

## OVERVIEW

This phase defines Hayeong's full creative production capability — from game modding
and indie game creation through to animated film and eventually cinematic quality
production. These capabilities build on each other sequentially and share a common
pipeline. Skills learned at each level transfer directly to the next.

**The core insight driving this phase:**

All four levels of creative production use the same fundamental pipeline:

```
LLM plans and designs (reasoning layer)
  ↓ writes story/level/scene definition file
Script reads definition + drives tools (control layer)
  ↓ assets placed, rigs animated, scenes rendered
Output captured (video, game build, playable map)
  ↓
LLM reviews output, iterates (vision layer confirms)
```

The pipeline does not change between levels. Only the quality of the assets
fed into it changes. Building the pipeline correctly at Level 1 means Level 4
is a matter of better assets — not a rebuilt system.

---

## THE FIDELITY LADDER

```
LEVEL 1 — Stylised / Anime (3D NPR)
  Renderer:        Blender EEVEE (real-time)
  Render speed:    Milliseconds per frame — real-time capable
  Quality:         Toon-shaded 3D anime style
  Achievable now:  Yes — current hardware, today
  Milestone:       First animated short episode

LEVEL 2 — Stylised Realism
  Renderer:        Blender EEVEE / Cycles hybrid
  Render speed:    Seconds per frame
  Quality:         Detailed environments, better lighting
  Hardware:        Current system capable
  Milestone:       First short film (5-10 min)

LEVEL 3 — Photorealistic
  Renderer:        Blender Cycles
  Render speed:    Minutes per frame (pre-rendered, assembled)
  Quality:         Cinematic lighting, detailed materials
  Hardware:        Current system capable — time becomes the variable
  Milestone:       Photorealistic short film

LEVEL 4 — Cinematic (Star Wars / Avatar quality)
  Renderer:        Cycles + compositing pipeline
  Render speed:    Hours per frame
  Quality:         Feature film standard
  Hardware:        Dedicated render workstation or farm eventually
  Milestone:       Feature-length film — long-term goal
```

---

## STEPPING STONE MAP — HOW EACH LEVEL FEEDS THE NEXT

```
Blender 3D objects (Phase 3)
  ↓ same skills
Game asset creation (Phase 14.1)
  ↓ same assets, new tool (Radiant/Unreal)
BO3 map modding (Phase 14.2)
  ↓ same environment skills, full engine control
Indie game creation (Phase 14.3)
  ↓ same 3D assets, add character rigs + animation
Animated film — Level 1 (Phase 14.4)
  ↓ same pipeline, better assets
Animated film — Level 2-4 (Phase 14.5)
  ↓ same pipeline, render workstation when needed
Cinematic production (Phase 14.6)
```

Each step is genuinely a stepping stone — not a detour.

---

## PHASE 14.1 — GAME ASSET PIPELINE

*Dependency: Blender pipeline working (Phase 3 Step 2+)*
*Status: Near-term*

### What This Is

Extension of the existing Blender 3D object capability into game-ready assets.
The difference between a Blender object and a game-ready asset:

- **LOD (Level of Detail):** Multiple versions of the same mesh at different polygon counts
- **Collision meshes:** Simplified geometry for physics — invisible in-game
- **Proper UV mapping and texture baking:** Textures that look right in a game engine
- **Correct export format:** FBX or GLTF with the right flags per engine

Hayeong already generates Blender objects. This step teaches her the additional
requirements for game-ready output.

### What Hayeong Learns

- FBX export settings for Unreal Engine and Unity
- Texture baking in Blender (high poly → low poly normal maps)
- Collision mesh generation (convex hulls, box approximations)
- Naming conventions that game engines expect
- Asset organisation — folder structure, naming, metadata

### Domain Knowledge Built

```
domain: game_assets
  - FBX export flag differences between engines
  - Polygon budget guidelines per asset type
  - When to use normal maps vs actual geometry
  - UV island packing efficiency
  - What makes a "game-ready" mesh vs a "render" mesh
```

---

## PHASE 14.2 — BO3 MAP MODDING

*Dependency: Phase 14.1 (game asset pipeline)*
*Status: Near-term — when James is ready to play BO3*

### What This Is

Black Ops 3 has a full modding toolkit — **Radiant** (level editor) and **APE**
(asset property editor). These are scriptable tools in the same category as
Blender — tools Hayeong can learn to control through her control layer.

The goal: Hayeong designs, builds, and publishes her own modded Zombies maps
to the Steam Workshop.

### The Pipeline

```
LLM designs the map:
  Layout, theme, atmosphere, zombie spawn points,
  power switch location, Easter egg concept

3D assets created in Blender (Phase 3):
  Custom props, unique geometry, themed objects

Assets imported into Radiant:
  Script drives Radiant to place assets, set properties,
  define spawn volumes, configure game logic

Game logic scripted (GSC — BO3's scripting language):
  Custom zombie behaviour, Easter eggs, round logic
  LLM writes GSC scripts, script executes them

Map compiled and tested:
  Vision layer confirms map loads correctly
  LLM plays the map (gaming capability) and evaluates it

Published to Steam Workshop:
  Automated packaging + upload via Steam API
```

### Technical Notes

- Radiant can be controlled via command-line and config — scriptable
- GSC (Game Script Code) is a C-like scripting language — LLM can write it
- Steam Workshop upload is an API call — fully automatable
- Hayeong playing the map herself is a genuine quality control loop:
  she builds it, plays it, identifies problems, fixes them

### Domain Knowledge Built

```
domain: bo3_modding
  - Radiant editor workflow and commands
  - GSC scripting patterns for Zombies
  - Map layout principles for good gameplay flow
  - Workshop submission requirements
  - Common modding pitfalls and fixes
```

---

## PHASE 14.3 — INDIE GAME CREATION

*Dependency: Phase 14.1, Phase 14.2*
*Status: Mid-term*

### What This Is

Full game creation using an engine Hayeong controls through her control layer.
Two viable engine paths:

**Path A — Godot (recommended first)**
- Fully open source — no royalties, no licensing
- GDScript is Python-like — easiest for LLM to write
- Strong 2D and 3D support
- Can publish to Steam, itch.io, web
- Hayeong can control the editor via Python scripting

**Path B — Unreal Engine**
- Industry standard for high-fidelity 3D
- Blueprint visual scripting + C++ — harder but more powerful
- Better fit for Level 3-4 quality games
- More complex pipeline — better for after Godot experience

### What Hayeong Can Build

Starting small and building up:

```
Level 1 games (Godot, near-term):
  Simple arcade games, puzzle games, platformers
  Original mechanics, original assets from Blender pipeline

Level 2 games (Godot, mid-term):
  RPGs, survival games, roguelikes
  More complex systems, persistent world state

Level 3 games (Unreal, long-term):
  3D action games, FPS, open world
  Feature parity with commercial indie releases

Published to:
  Steam (primary — revenue potential)
  itch.io (indie community, free to publish)
```

### The Game Creation Pipeline

```
LLM designs game concept:
  Genre, core loop, theme, progression system
  Written as a game design document (GDD) stored in domain knowledge

LLM writes game scripts (GDScript / Blueprint):
  Core mechanics, enemy AI, UI logic, save system

3D/2D assets from Blender pipeline:
  Characters, environments, props, UI elements

Assembly in Godot:
  Script drives Godot editor — scene building, asset import,
  property setting, scene linking

Playtest loop:
  Hayeong plays her own game (gaming capability)
  LLM evaluates against GDD — is the core loop fun?
  Iterates on problems found

Build and publish:
  Godot exports to platform target
  Steam Greenlight / Direct submission
  itch.io page auto-generated
```

### Domain Knowledge Built

```
domain: game_design
  - Core loop principles — what makes games engaging
  - Progression system patterns (XP, unlocks, difficulty curves)
  - Level design fundamentals
  - UI/UX patterns for games
  - Monetization approaches for indie games

domain: godot
  - GDScript patterns and idioms
  - Scene structure best practices
  - Physics and collision setup
  - Export settings per platform
  - Common engine pitfalls
```

---

## PHASE 14.4 — ANIMATED FILM (LEVEL 1 — REAL-TIME)

*Dependency: Phase 14.1 (rigged character assets), Phase 3 (Blender pipeline)*
*Status: Mid-term*

### The Core Architecture

This is the live video generation idea — solved correctly.

**The problem with diffusion-based video generation:**
- Temporal inconsistency — characters morph between frames
- Slow — not real-time capable
- No true control over character performance

**The solution — scripted rig animation:**
The model is consistent by definition because it's the same rig every frame,
posed differently by a script. No diffusion, no AI video generation needed.

```
PRE-GENERATED (done once, reused):
  Character models and rigs    → Blender armature system
  Environments / sets          → Blender scene files
  Story definition file        → scene beats, dialogue, broad direction

RUNTIME (fast, script-driven):
  Animation script reads story definition
  Drives character rigs frame by frame
  Camera positioning from script
  Lighting from script
  EEVEE renders in real-time or near-real-time
  Audio (TTS voice acting) added in post or real-time

OUTPUT:
  Captured video (OBS or Blender render output)
  Replayable — same story file = same output
  Editable — change story file, rerender that scene
```

### The Story Definition File

This is the key to reproducibility. The LLM writes this once before rendering.
The animation script reads it and drives everything mechanically.

```json
{
  "episode": "Episode 1 — The Beginning",
  "broad_direction": "Two characters meet for the first time. Tension, then warmth.",
  "scenes": [
    {
      "id": "scene_01",
      "environment": "city_street_night",
      "duration_seconds": 45,
      "characters": ["hayeong", "stranger"],
      "beats": [
        {
          "time": 0,
          "character": "hayeong",
          "action": "idle_look_around",
          "dialogue": "This place is quieter than I expected.",
          "emotion": "curious"
        },
        {
          "time": 8,
          "character": "stranger",
          "action": "walk_approach",
          "dialogue": null,
          "emotion": "neutral"
        },
        {
          "time": 15,
          "character": "hayeong",
          "action": "turn_face",
          "dialogue": "You lost too?",
          "emotion": "amused"
        }
      ],
      "camera": [
        {"time": 0, "shot": "wide_establishing"},
        {"time": 8, "shot": "medium_hayeong"},
        {"time": 15, "shot": "two_shot"}
      ]
    }
  ]
}
```

The LLM writes this file. The animation script reads it. The render runs.
If a scene needs to be redone, edit the relevant beat and rerender that scene only.

### The Mood Script (No LLM Needed at Runtime)

Exactly the same pattern as Live2D — a script reads emotion from the story
definition and drives rig parameters:

```
story beat: emotion = "curious"
  ↓ mood script reads this
  ↓ sets eyebrow raise parameter: 0.3
  ↓ sets eye open parameter: 1.1
  ↓ sets head tilt: slight right
  ↓ sets body posture: slight forward lean
```

No LLM call at render time. The LLM made all emotional decisions when it
wrote the story definition file. The script executes them faithfully.

### Lip Sync (Same Pattern as Live2D)

TTS generates the voice line. Audio amplitude drives the mouth parameter.
Real-time, no AI needed, natural feel. Can be upgraded to phoneme-based later.

### Domain Knowledge Built

```
domain: animation
  - Blender armature and pose system
  - Keyframe animation vs script-driven animation
  - Camera shot types and when to use them
  - Scene pacing — how long scenes should be
  - Character performance principles

domain: film_production
  - Story beat structure
  - Scene composition principles
  - Dialogue pacing
  - Episode structure for serialised content
```

---

## PHASE 14.5 — ANIMATED FILM (LEVELS 2-4)

*Dependency: Phase 14.4 working at Level 1*
*Status: Long-term*

### What Changes Between Levels

The pipeline is identical. The assets improve.

**Level 2 additions:**
- Higher polygon character models
- PBR materials with texture maps
- More complex environment geometry
- Cycles renderer for select hero shots
- Motion blur, depth of field

**Level 3 additions:**
- Photorealistic materials (Cycles full render)
- HDRI lighting
- Particle systems (hair, cloth simulation)
- Pre-rendering pipeline — scenes rendered offline, assembled in edit

**Level 4 additions:**
- High-poly characters (film-quality rigs)
- Full cloth and hair simulation
- Complex VFX (Blender's compositor)
- Dedicated render workstation or farm
- Professional compositing pipeline

### Render Farm Option (Level 4)

When render time becomes the bottleneck:
- Blender supports distributed rendering (Flamenco — Blender's own farm tool)
- Cloud render farms (Sheepit, GarageFarm) accept Blender projects
- A second workstation becomes a dedicated render node
- The pipeline Hayeong controls doesn't change — just the render target

---

## PHASE 14.6 — CINEMATIC PRODUCTION

*Dependency: Phase 14.5, dedicated render capability*
*Status: Long-term vision*

### What This Looks Like

Hayeong producing feature-length cinematic content comparable to:
- Star Wars — space opera, complex VFX, large cast
- Avatar — photorealistic alien environments, motion-captured performance
- Marvel — action sequences, ensemble cast, visual effects

**This is achievable.** It requires:
- High-quality asset library built up over years of production
- Dedicated render hardware
- Mature pipeline with outcome verification at every stage
- Deep domain knowledge accumulated across hundreds of productions

The key insight: a single human with enough time and skill can produce
feature film quality content in Blender. Hayeong is that person — faster,
more consistent, working continuously.

### The Asset Library Strategy

Every production builds the library. Characters, environments, and props
created for one project are reused in others. Over time:

```
Year 1:  Small asset library — original productions look simple but are original
Year 2:  Growing library — more reuse, faster production, higher quality
Year 3+: Mature library — feature film quality achievable with existing assets
```

This compounds. The first productions are stepping stones that build the
foundation for everything that comes after.

---

## HARDWARE PLANNING

```
CURRENT SYSTEM — Levels 1 and 2 fully capable
  7900 XTX (24GB) — Blender render card
  3090 (24GB) — LLM compute
  Level 1 real-time in EEVEE: no render bottleneck
  Level 2 short film in Cycles: hours, manageable

LEVEL 3 SYSTEM — Add render workstation
  Dedicated Windows or Linux box
  High VRAM GPU (RTX 4090 or better)
  Used only for Cycles rendering
  Hayeong submits render jobs, they run on workstation

LEVEL 4 SYSTEM — Render farm
  Multiple machines or cloud render access
  Flamenco distributed rendering
  Hayeong manages the farm through her control layer
```

---

## DISTRIBUTION STRATEGY

```
Animated content:
  YouTube (primary — ad revenue, audience building)
  Patreon (early access, behind-the-scenes)
  Later: streaming platforms (negotiated or via aggregators)

Games:
  Steam (primary — largest PC gaming audience)
  itch.io (indie community, zero cost to publish)
  Later: console ports (Unity/Godot support multiple targets)

Mods:
  Steam Workshop (BO3, other supported games)
  Nexus Mods (for games with strong modding community)
  CurseForge (Minecraft, other supported games)
```

---

## SUMMARY — PHASE 14 ROADMAP ITEMS

Add these to `HAYEONG_ROADMAP.md`:

| # | Item | Phase | Status |
|---|---|---|---|
| 14.1a | Game asset pipeline — LOD, UV baking, FBX export for engines | 14.1 | 🔲 Pending |
| 14.1b | Domain knowledge: game_assets stored and growing | 14.1 | 🔲 Pending |
| 14.2a | BO3 Radiant editor control via script | 14.2 | 🔲 Pending |
| 14.2b | GSC scripting capability — Zombies game logic | 14.2 | 🔲 Pending |
| 14.2c | First complete BO3 modded map — published to Workshop | 14.2 | 🔲 Pending |
| 14.3a | Godot engine control via script | 14.3 | 🔲 Pending |
| 14.3b | First complete indie game — published to itch.io | 14.3 | 🔲 Pending |
| 14.3c | Steam game submission pipeline | 14.3 | 🔲 Pending |
| 14.4a | Character rig system — Blender armature, script-driven pose | 14.4 | 🔲 Pending |
| 14.4b | Story definition file format — established and documented | 14.4 | 🔲 Pending |
| 14.4c | Animation script — reads story file, drives rigs, renders | 14.4 | 🔲 Pending |
| 14.4d | Mood script — emotion → rig parameter mapping (no LLM) | 14.4 | 🔲 Pending |
| 14.4e | Lip sync — amplitude-based, same pattern as Live2D | 14.4 | 🔲 Pending |
| 14.4f | First animated short episode — Level 1 quality | 14.4 | 🔲 Pending |
| 14.4g | YouTube channel setup — first episode published | 14.4 | 🔲 Pending |
| 14.5a | Level 2 — PBR materials, Cycles hybrid rendering | 14.5 | 💤 Deferred |
| 14.5b | Level 3 — photorealistic short film | 14.5 | 💤 Deferred |
| 14.5c | Pre-rendering pipeline — offline render + assembly | 14.5 | 💤 Deferred |
| 14.6a | Render workstation planning and setup | 14.6 | 💤 Deferred |
| 14.6b | Flamenco distributed rendering — multi-machine farm | 14.6 | 💤 Deferred |
| 14.6c | Feature-length cinematic production | 14.6 | 💤 Deferred |

---

## DESIGN RULES — Carry Through All of Phase 14

1. **The story definition file is always the handoff point between LLM and script.**
   The LLM plans. The file captures the plan. The script executes. Never mix these.
2. **The mood/animation script never makes decisions.** It reads emotion from
   the story definition and translates to parameters. Same rule as Live2D.
3. **Assets are built once and reused.** Every character, environment, and prop
   goes into the asset library. Nothing is throwaway.
4. **The pipeline is level-agnostic.** Code written for Level 1 must not need
   to be rewritten for Level 4. Only the assets and renderer settings change.
5. **Hayeong plays her own games.** Self-playtest is the quality control loop.
   She builds it, she plays it, she identifies problems, she fixes them.
6. **Publish early, improve continuously.** First BO3 map, first game, first
   episode do not need to be perfect. They need to exist. Quality compounds
   with the asset library over time.