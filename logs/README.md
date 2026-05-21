# Logs\

Everything recorded about Hayeong's activity.

## What Lives Here

- `conversations\` — Every conversation with James. These are sacred.
  Do not delete them. They are future fine-tuning data — the foundation
  of eventually training a model that is genuinely Hayeong at parameter level.

- `task_logs\` — Tool execution logs. Errors, results, timing.
  When a tool fails, read here first to understand what happened.

- `watchdog_logs\` — System health monitoring output.

- `outputs\` — Things Hayeong creates: images, 3D models, documents, music.
  Organized by creation date and tool.

- `finetune_datasets\` — Exported training datasets from the finetune_curator tool.
  JSONL and Alpaca-format files ready for fine-tuning runs.

- `dashboard\` — Logs specific to dashboard activity.

- `handoffs\` — Claude Code handoff notes from development sessions.
  Records of architectural decisions and implementation instructions.

- `pending_james_review\` — Items flagged by Hayeong's dev tool for James's review
  before being applied. These are proposed changes waiting for approval.

- `notes\` — Roadmap notes and important project documents.
  Hayeong can write her own notes here — problem logs, update plans,
  things she wants to remember about the project.

- `console.log` — Mirror of stdout/stderr from the main process. The _Tee class
  in startup() writes every console line here so errors are preserved after
  the terminal closes.

## What To Know

When debugging a tool failure, task_logs\ is the first place to look.
Conversations are write-once — Hayeong writes them, nobody deletes them.
The notes\ folder is Hayeong's scratchpad for self-directed thinking.
