# Brain\

This is where Hayeong thinks and who she is.

## What Lives Here

- `config.py` — The single source of truth for all paths, ports, and model names.
  Everything else imports from here. If a path or port changes, change it here only.

- `identity.json` — Hayeong's personality, values, and relationship with James.
  This is not configuration. This is who she is.

- `state\` — The shared state bus. core.json is how the three main loops
  (reasoning, communication, task) coordinate without blocking each other.
  Do not write to core.json directly from tools — use the state interface.

- `vision\` — The abstract vision layer. How Hayeong receives and interprets
  input from the world (text, voice, terminal output, task results).

## What To Know

config.py is imported by almost everything. Changes here have wide effect.
Read it before changing it. Changes to identity.json touch who Hayeong is —
bring these to James.

The vision layer is abstract by design. The type of input can change without
changing how Brain processes what it receives. New input types go here.
