# Brain\

This is where Hayeong thinks and who she is.

## What Lives Here

- `config.py` — The single source of truth for all paths, ports, and model names.
  Everything else imports from here. If a path or port changes, change it here only.

- `identity.json` — Hayeong's personality, values, and relationship with James.
  This is not configuration. This is who she is.

- `state\` — The shared operational state bus. core.json is how the three main loops
  (reasoning, communication, task) coordinate without blocking each other.
  Do not write to core.json directly from tools — use the state interface.
  This is runtime state, not memory — it reflects what is happening right now,
  not what has happened over time.

- `vision\` — Architecture placeholder for the vision layer coordination logic.
  Current input handling (tool results, Minecraft packets) flows through the
  reasoning loop directly. This folder expands when the workstation arrives
  and screen-awareness becomes active. Implementation lives in Toolbox\vision_tools\.

## State vs Memory

Brain\state\ and Memory\ serve different purposes:

- `Brain\state\` — **What is happening now.** Loop coordination, active task,
  current mood, plugin signals. Overwritten on every cycle. Ephemeral.
- `Memory\` — **What has happened over time.** Conversations, learned facts,
  emotional moments, domain knowledge. Persistent. Grows over time.

Tools and plugins read from state. The reasoning loop reads from both.

## What To Know

config.py is imported by almost everything. Changes here have wide effect.
Read it before changing it. Changes to identity.json touch who Hayeong is —
bring these to James.
