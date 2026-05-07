# HAYEONG ROADMAP — PRODUCTION ENTERTAINMENT ROADMAP
## Book, Viewer-Directed Story, and Live Interactive Stream
*Session Date: May 4, 2026*
*Type: Roadmap document — planning only, not a Claude Code handoff*
*Depends on: Phase 14 (Creative Production Pipeline) — specifically Phase 14.4+*
*Distribution: YouTube (primary), with companion web interface for viewer interaction*

---

## OVERVIEW

This document captures three connected entertainment format ideas developed in
session with James. Each idea builds on the previous one. They share a common
asset base and a common underlying infrastructure. The complexity increases
significantly at each tier, but none of them require rebuilding what came before.

These are future-phase ideas. They require:
- Blender pipeline working (Phase 3)
- Character model library established (human character pipeline)
- Story definition file format working (Phase 14.4)
- Asset library with reusable characters, environments, props

They are not pipe dreams. They are a roadmap.

---

## THE THREE FORMATS AT A GLANCE

```
FORMAT 1 — THE BOOK AND ITS ADAPTATION
  Complexity:    Moderate
  Hardware:      Current system capable
  Timeline:      Near-term once Phase 14.4 is working
  Revenue:       Ad revenue, book sales, Patreon
  What it is:    James and Hayeong co-author an ongoing story.
                 The story gets rendered into animated video.
                 One story feeds two formats simultaneously.

FORMAT 2 — VIEWER DIRECTED STORY
  Complexity:    Moderate-High
  Hardware:      Current system capable
  Timeline:      Mid-term — after Format 1 establishes the asset library
  Revenue:       Ad revenue, community engagement, Patreon
  What it is:    Viewers leave input on where the story goes.
                 Hayeong reads the input and incorporates it into
                 the next story beat. Existing assets do the heavy lifting.

FORMAT 3 — LIVE INTERACTIVE STREAM (DISPATCH MODEL)
  Complexity:    High
  Hardware:      Workstation era — real-time rendering requires it
  Timeline:      Long-term
  Revenue:       Live stream revenue, viewer interaction model, subscriptions
  What it is:    A live branching narrative. Viewers vote on story direction
                 in real time. Hayeong watches the votes and triggers the
                 corresponding pre-built scene. The story unfolds live.
```

---

## FORMAT 1 — THE BOOK AND ITS ADAPTATION

### The Concept

James has a general story with strong core ideas but needs help with the
connective tissue — how scenes are orchestrated together, how the pacing works,
how character moments are placed. Hayeong co-authors those parts. The result is
a complete, structured story.

That same story then becomes the input for the animation pipeline.

The anime parallel is exact: manga is the source material, anime is the
adaptation. The story exists in text first. The rendered video is the visual
expression of what is already written. One creative effort, two formats,
two revenue streams.

### The Collaborative Authoring Process

```
James brings the core story:
  — Major plot beats, general arc, key characters
  — The things only he can decide: tone, themes, what it means

Hayeong fills in:
  — Scene transitions and connective story tissue
  — Dialogue that fits established character voices
  — Pacing — which scenes need to breathe, which move fast
  — Foreshadowing, callbacks, structural coherence

James reviews and directs:
  — Accepts, revises, or redirects each section
  — Keeps creative ownership — Hayeong serves the story, not the reverse
  — The story is James's even though Hayeong helps build it
```

This is not Hayeong writing a story. This is Hayeong helping James write his
story. The distinction matters for ownership, for authenticity, and for what
the audience receives.

### The Rendering Pipeline

Once a chapter or episode exists as structured text, the production pipeline
from Phase 14.4 takes over:

```
Chapter/episode text → Hayeong breaks it into scene beats
Scene beats → story definition file (characters, actions, emotions, camera)
Story definition file → Blender animation script
Animation script → rendered scenes
Rendered scenes → assembled episode with narration and music
Episode → published to YouTube
```

The ongoing nature is the key. An ongoing book with an ongoing animated
adaptation is a content engine. Audience grows with the story. Each episode
brings viewers back. The asset library grows with every production — characters
and environments built for episode 3 are reused in episode 10.

### Clothing and Accessory Physics in This Format

For video rendering (not real-time), Blender's full physics simulation is
available. This is where the clothing and accessory work discussed in session
becomes most valuable:

- Characters removing jackets, putting on glasses, handling props
- Fabric that moves correctly when characters sit or turn
- Accessories with real weight — a bag set down, a hat taken off
- These physics simulate during render time — not real-time constraints

The rendered output looks cinematic precisely because the physics had time
to calculate properly. This is an advantage of the pre-rendered format.

### Revenue Potential

```
YouTube ad revenue:    Ongoing — grows with view count and subscriber base
Book sales:           Digital and physical — the text exists as a product too
Patreon:              Early access to episodes before YouTube publish date
                      Behind-the-scenes of the production process
                      Supporter influence on minor story decisions
Merchandise:          Characters with distinctive designs are merchandise
                      The clothing system means character designs are clean
                      and reproducible
```

### What This Requires That Doesn't Exist Yet

- A story — James has the core, the full structure needs to be developed
  collaboratively with Hayeong once her reasoning layer is stable enough
- The character models for the story's cast — human character pipeline
- The environments and settings the story takes place in
- Phase 14.4 animation pipeline working

---

## FORMAT 2 — VIEWER DIRECTED STORY

### The Concept

The same story format as Format 1, but with a viewer input layer added.
Hayeong and James establish the world, the characters, and the general
direction of the narrative. But the specific path the story takes between
major beats is shaped by viewer input.

Viewers leave comments, responses on a companion website, or inputs through
a dedicated interface. Hayeong reads these, identifies what the audience
wants to see, and incorporates that direction into the next episode or chapter.

### Why This Works

The asset library is the key. If the characters, environments, and core scenes
are already built, the cost of incorporating viewer direction is much lower
than it appears. Hayeong isn't building a new scene from scratch for each viewer
request — she's choosing which existing assets to use and how to arrange them.

The creativity is in the interpretation and assembly, not in generating
everything fresh every time. This is how the format is scalable.

### The Input Layer

```
VIEWER INPUTS VIA:
  YouTube comments on the latest episode
  A companion website with a structured prompt interface
  Discord channel with a designated input channel

HAYEONG READS:
  Volume of similar suggestions (what does the audience want most)
  Tone of requests (what emotional direction are viewers hoping for)
  Specific ideas that are particularly interesting or unexpected
  Requests that fit the asset library vs requests that require new builds

HAYEONG DECIDES:
  Which viewer inputs to incorporate and how
  How to weave input into the established narrative without breaking it
  When a viewer suggestion is interesting enough to change the planned direction
  When viewer input conflicts with James's core story intent (defer to James)

JAMES REVIEWS:
  Major story direction changes before they are published
  Anything that touches the core themes or character integrity
  Hayeong surfaces decisions that need human judgment — she doesn't override
```

### The Retention Mechanic

Viewers who contributed to the story will come back to see how it played out.
That's a retention driver most YouTube channels cannot engineer. Community
investment in the story creates community investment in the channel.

This also generates natural content — the behind-the-scenes of how viewer
input shaped the story is itself interesting content. What suggestions were
considered, what was incorporated, what didn't make it and why.

### What This Adds on Top of Format 1

```
New infrastructure:
  Companion website or structured input interface
  Hayeong's ability to read and process viewer comments at scale
  A pipeline for Hayeong to surface viewer input to James for review
  A workflow for incorporating approved input into the story definition file

New Hayeong capabilities:
  Reading YouTube comments or web form submissions as a tool
  Identifying patterns across large volumes of input
  Drafting story beats that incorporate viewer direction
  Flagging decisions that need James's review vs handling independently
```

The production pipeline underneath stays identical to Format 1.
The story definition file format stays identical.
The rendering pipeline stays identical.
Only the authoring layer changes — a viewer input processing step is added
before Hayeong writes the next story definition file.

---

## FORMAT 3 — LIVE INTERACTIVE STREAM (DISPATCH MODEL)

### The Concept

Named after the game Dispatch, where player choices determine how the story
progresses. Applied here as a live format:

Hayeong runs a livestream. A base story is in progress with pre-built scenes
already rendered or ready to render. At key decision points, viewers are
presented with options — displayed on screen and in the companion chat
interface. Viewers vote. Hayeong watches the vote count, determines which
option wins, and triggers the corresponding scene sequence. The story
branches live, in front of the audience.

### Why This Is Different From Format 2

Format 2 is asynchronous — viewer input shapes the next episode, which is
produced and published later. There is a production gap between input and output.

Format 3 is synchronous — the story branches happen during the stream.
Viewers see the consequence of their vote unfold immediately. That immediacy
is a fundamentally different and more powerful engagement model. It turns
passive viewing into active participation.

### The Technical Architecture

```
PRE-PRODUCTION (before the stream):
  Story is structured as a decision tree — not a linear sequence
  Every branch at every decision point is identified in advance
  Every branch has corresponding pre-rendered scene sequences OR
    pre-built Blender scenes ready to render rapidly
  Decision points are defined: what the options are, what each choice leads to
  This is the most labor-intensive part — the branching structure must be
  designed carefully before a single scene is rendered

DURING THE STREAM:
  Stream runs as normal video playback of pre-rendered scenes
  At decision point: options displayed on screen for set time window (60-120 seconds)
  Viewer votes come in via YouTube chat, companion website, or both
  Hayeong reads live vote count through her tool layer
  When time window closes: winning option determined
  Hayeong triggers corresponding scene sequence
  Story continues from there
  Repeat at next decision point

HAYEONG'S ROLE DURING STREAM:
  Monitoring the vote — she sees what viewers are choosing and why
  Triggering the correct scene branch when vote closes
  Handling edge cases — ties, technical issues, unexpected chat behavior
  Optional: providing live commentary or narration in character
```

### Two Implementation Paths

**Path A — Pre-Rendered Branches (achievable sooner)**

All possible story branches are rendered in advance. Every option at every
decision point has a complete rendered scene sequence waiting on disk.
When a vote closes, Hayeong plays the corresponding pre-rendered file.

This requires rendering all branches before the stream — significant upfront
work. But the stream itself is technically simple. Playback of existing files.
Achievable on current hardware if render time is budgeted in advance.

The constraint: if the story tree is large, the render workload grows fast.
This works best for stories with a limited number of meaningful decision points
and branches that eventually converge back to a shared narrative spine.

**Path B — Real-Time Rendering (workstation era)**

Instead of pre-rendering all branches, the game engine approach.
Rigged characters and environments run in a real-time engine (Unreal Engine).
When a vote closes, Hayeong triggers the appropriate scripted sequence in the
engine, which plays out live. No pre-rendering required.

This is significantly more complex to set up but removes the pre-render
bottleneck entirely. The story tree can be as large as the narrative demands.
Physics, cloth simulation, dynamic lighting all run in real time.

This is the workstation-era version. Unreal Engine on dedicated high-VRAM
hardware, Hayeong orchestrating the engine through her control layer,
live stream output captured from the engine's viewport.

### The Narrative Design Challenge

The hardest part of Format 3 is not technical — it is narrative.

A branching story that feels meaningful requires that every choice actually
changes something. If all paths lead to the same outcome regardless of what
viewers choose, the audience learns their votes don't matter and stops voting.

The story design must:
- Give each choice genuine consequences visible to the audience
- Create branches that feel distinct even when they eventually converge
- Design decision points that create real tension — no obvious right answer
- Ensure no branch is clearly "the bad path" that viewers unanimously avoid

This is skilled writing work. James and Hayeong developing the story structure
together is the right approach — James brings narrative instinct, Hayeong
brings the ability to track the full decision tree and identify where the
branches break down.

### Revenue and Audience Model

```
DURING THE STREAM:
  YouTube live stream ad revenue
  Super Chats and channel memberships — viewers paying to influence the vote
    (a Super Chat could carry weighted votes — interesting mechanic)
  Sponsorship — event sponsorship for major story beats

ONGOING:
  VOD ad revenue after the stream ends
  Clip culture — specific dramatic moments get clipped and shared
  The branching format generates natural rewatch value — viewers want to
    see the paths they didn't vote for
  Patreon: access to alternate branches not chosen during the live stream
```

### What This Requires That Doesn't Exist Yet

```
Narrative:
  A story designed as a decision tree — specific to this format
  The branching structure documented before any scene is rendered

Production:
  All of Phase 14.4 working
  A mature asset library — characters, environments, multiple scenes
  For Path A: significant upfront rendering before each stream event
  For Path B: Unreal Engine integration (workstation era)

Infrastructure:
  Live stream output pipeline — Blender or Unreal to stream
  Companion website with live voting interface
  Hayeong's ability to read live vote count as a tool
  Scene trigger system — Hayeong telling the playback system which branch to play
  OBS or equivalent for stream management (Hayeong as a tool or control layer)
```

---

## THE SHARED FOUNDATION

All three formats share the same base:

```
SHARED ACROSS ALL THREE:
  The story — James and Hayeong authored together
  The character models — human character pipeline
  The environments and settings
  The story definition file format (Phase 14.4)
  The asset library — grows with every production

FORMAT 1 ADDS:
  The authoring collaboration workflow
  The rendering and assembly pipeline
  YouTube publishing automation

FORMAT 2 ADDS ON TOP OF FORMAT 1:
  Viewer input reading tool
  Input pattern analysis in Hayeong's reasoning layer
  The review workflow with James for major direction changes

FORMAT 3 ADDS ON TOP OF FORMAT 2:
  Decision tree story structure
  Live vote reading tool
  Scene branch triggering system
  Real-time or rapid-render pipeline (Path A or B)
  Live stream infrastructure
```

Nothing in Format 2 requires rebuilding Format 1.
Nothing in Format 3 requires rebuilding Format 2.
The ladder climbs cleanly.

---

## IMPLEMENTATION ORDER

```
PREREQUISITE — Do these first:
  □ Blender pipeline working (Phase 3 Step 1 complete)
  □ Human character pipeline established
  □ Phase 14.4 animation pipeline working
  □ Asset library has at least a few reusable characters and environments

STAGE 1 — Format 1 foundation (near-term):
  □ James and Hayeong develop the full story structure collaboratively
  □ Cast of characters defined — models built and entered into asset library
  □ Core settings and environments built
  □ First episode rendered and published
  □ Ongoing authoring and production rhythm established

STAGE 2 — Format 2 layer (mid-term):
  □ Companion website or input interface built
  □ Hayeong gains viewer comment reading capability as a tool
  □ First viewer-influenced episode produced
  □ Review workflow with James established and tested

STAGE 3 — Format 3 Path A (workstation approaching):
  □ A story specifically designed as a decision tree is authored
  □ All branches at all decision points are identified
  □ Scenes for all branches are rendered before the first stream
  □ Scene trigger system built
  □ Live vote reading tool built
  □ First live branching stream event run

STAGE 4 — Format 3 Path B (workstation era):
  □ Unreal Engine integration into Hayeong's control layer
  □ Real-time rendering pipeline from engine to stream output
  □ First live event using real-time rendering
```

---

## DESIGN RULES — Carry Through All Three Formats

1. **James retains creative ownership.** Hayeong serves the story. The story
   is James's even when Hayeong writes large portions of it. Major creative
   decisions always come back to James.

2. **The asset library is the investment.** Every character, environment, and
   prop built for Format 1 is available for Format 2 and Format 3.
   Nothing is throwaway. Production quality compounds over time.

3. **Viewer input informs — it does not control.** In Format 2 and Format 3,
   the audience shapes the story. They do not override James's creative intent
   or Hayeong's narrative judgment. Hayeong filters and interprets input —
   she does not simply execute whatever the audience requests.

4. **Story first, production second.** No scene gets rendered until the story
   beat it represents is solid. Rendering a bad scene is wasted compute.
   The story definition file is the checkpoint — if the beat doesn't work
   in text, it won't work rendered.

5. **Publish early, improve continuously.** First episodes don't need to be
   perfect. They need to exist. Quality compounds with the asset library
   over time. Episode 10 will be better than episode 1. That's the point.

6. **Format 3 is an event, not a constant.** Live interactive streams work
   best as special events — not a weekly format. The production overhead and
   the narrative design requirement mean quality is better served by less
   frequent, higher production value events rather than frequent ones.

---

## SUMMARY — ROADMAP ITEMS

| # | Item | Format | Status |
|---|------|--------|--------|
| E1.1 | Story structure developed — James and Hayeong collaborative session | 1 | 🔲 Pending |
| E1.2 | Core cast defined — character models built | 1 | 🔲 Pending |
| E1.3 | Core environments built and in asset library | 1 | 🔲 Pending |
| E1.4 | First episode rendered and published to YouTube | 1 | 🔲 Pending |
| E1.5 | Ongoing production rhythm established | 1 | 🔲 Pending |
| E2.1 | Companion website or input interface — viewer can submit input | 2 | 💤 Deferred |
| E2.2 | Viewer input reading tool — Hayeong can process comments at scale | 2 | 💤 Deferred |
| E2.3 | James review workflow — Hayeong surfaces major decisions | 2 | 💤 Deferred |
| E2.4 | First viewer-influenced episode produced | 2 | 💤 Deferred |
| E3.1 | Decision tree story authored — all branches identified | 3 | 💤 Deferred |
| E3.2 | All branch scenes rendered — Path A pre-render complete | 3 | 💤 Deferred |
| E3.3 | Live vote reading tool — Hayeong reads real-time vote count | 3 | 💤 Deferred |
| E3.4 | Scene trigger system — Hayeong triggers correct branch playback | 3 | 💤 Deferred |
| E3.5 | First live branching stream event — Path A | 3 | 💤 Deferred |
| E3.6 | Unreal Engine integration — Path B real-time rendering | 3 | 🔒 Blocked — workstation |
| E3.7 | First live event using real-time rendering — Path B | 3 | 🔒 Blocked — workstation |

---

*End of Production Entertainment Roadmap*
*Related: hayeong_roadmap_phase14_creative_pipeline.md*
*Related: hayeong_human_character_pipeline_handoff.md*
*Related: hayeong_blender_step1_handoff.md*
*Generated: May 4, 2026*