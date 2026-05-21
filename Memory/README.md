# Memory\

Hayeong's persistent memory — what she remembers, who she knows, and what she
has learned. Distinct from Brain\state\, which holds transient runtime signals.
Memory accumulates over time; state resets each cycle.

## What Lives Here

- `memory.json` — Active memory state. Current context, recent events,
  active goals. Read by the reasoning loop each cycle.

- `chromadb\` — Vector memory store. Long-term searchable memory.
  Hayeong stores and retrieves memories here by semantic similarity.

- `knowledge\` — Accumulated knowledge organized by domain.
  This grows over time as Hayeong learns and experiences things.

  - `toolknowledge\` — What Hayeong knows about her own tools:
    how to use them, their quirks, what works and what doesn't.

- `backups\` — Timestamped backups of Hayeong's state and memory files.
  Created automatically during updates. If something goes wrong, restore from here.

## What To Know

memory.json and the chromadb store are the most frequently read/written
files in the system. If something seems wrong with memory, check for
stale .lock files in the root — delete them if Hayeong isn't running.

Knowledge files are Hayeong's own — she builds them through experience
and inference. They are not pre-loaded databases. They grow as she learns.

Minecraft knowledge (once she starts playing) will live in:
`knowledge\minecraft\` with separate files per server instance or mod profile.
