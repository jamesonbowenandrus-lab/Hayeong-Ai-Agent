# Toolbox/dev

Hayeong's self-modification tool. Allows the reasoning layer to propose and apply
changes to her own tools, scripts, and domain prompts — within enforced scope
constraints. James remains the correction authority.

## Files

- `hayeong_dev_tool.py` — main tool and registry entry point

## How It Works

Every call goes through three checks and routes to one of three outcomes:

### Outcomes

**applied** — Change was applied directly.
- File was backed up before modification.
- Logged to `logs/dev_tool_log.json`.
- Result written to shared state bus.

**handoff** — Change requires Claude Code or James.
- A structured `handoffs/YYYYMMDD_HHMMSS.md` file is written for manual pickup.
- Triggered by: `change_type="new_file"`, `change_type="structural"`, or edits over 50 lines.

**blocked** — Change is not permitted.
- A review file is written to `pending_james_review/`.
- Triggered by: protected paths, or `requires_review=True` (Hayeong self-flags).

## Scope Rules

### In-scope for direct edit:
- `toolbox/**` — any tool script, prompt file, or config in a tool folder
- `brain/identity_living.json` — Hayeong's self-authored layer (full write access)

### Always handoff (not blocked, just too large for direct apply):
- `change_type="new_file"` — creating any new file
- `change_type="structural"` — architectural changes
- Any edit over 50 lines of proposed content

### Blocked (requires James review):
- `main.py`
- `app_manager.py`
- `brain/identity_constitutional.json`
- `brain/identity_behavioral.json`
- `toolbox/registry.json`
- Any path in `brain/` except `identity_living.json`
- Any path outside the project root
- `requires_review=True` — Hayeong self-flagged

## Calling This Tool

    action: dev
    params:
      target_path=toolbox/blender/blender_prompt.txt
      change_type=prompt_update
      change_description=Update blender prompt to include export format guidance
      proposed_content=[new content]

## Backup Policy

Before every direct edit:
- `edit`: file is copied to `filename.backup.YYYYMMDD_HHMMSS` in the same directory
- `prompt_update`: latest backup overwrites `filename.backup.ext`, full history in `logs/prompt_history/`

Backups are never auto-deleted.

## Logging

All calls (applied, handoff, blocked) are logged to `logs/dev_tool_log.json`:

    {
      "timestamp": "...",
      "target": "...",
      "change_type": "...",
      "description": "...",
      "outcome": "applied|handoff|blocked",
      "backup_created": true|false,
      "backup_path": "..."
    }
