# Claude Code Bridge

This folder contains the bridge infrastructure for Claude Code ↔ Hayeong sessions.

## How It Works

Claude Code sends messages to Hayeong via `cc_bridge.py`, which posts to the
same HTTP endpoint the dashboard uses. Hayeong's response is captured by polling
`Brain/state/core.json` for a new `presence_output.expressed_at` timestamp.

Hayeong always knows she is talking to Claude Code, not James.
Claude Code sessions produce capability/task evaluation data.
James's direct sessions produce relational data.
These are kept separate and serve different purposes.

## Files

- `cc_bridge.py` — the bridge script, never modified between sessions
- `current_prompt.md` — the prompt used in the most recent session (auto-overwritten)
- `session_result.md` — the full result log from the most recent session (auto-overwritten)
- `session_prompts/` — reusable prompt templates, one per objective type

## Running a Session

Ensure Hayeong is running and the dashboard server is active, then give Claude Code
the relevant prompt file from `session_prompts/` and instruct it to use the bridge.

Example terminal instruction to Claude Code:
  "Use Claude/session_prompts/blender_eval.md as your session prompt.
   Run the bridge using Claude/cc_bridge.py for each message.
   Follow the session parameters in the prompt."

## Session History

Full session history is stored in `Brain/session_log.db` (SQLite).
Query by date: SELECT * FROM cc_sessions WHERE date = '2026-06-05';

The current_prompt.md and session_result.md always reflect the most recent run only.
