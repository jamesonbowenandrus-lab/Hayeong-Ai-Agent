"""
toolbox/dev/hayeong_dev_tool.py

Hayeong's self-modification and code authoring tool.
Allows the reasoning layer to propose and apply changes to her own tools,
scripts, and domain prompts — within enforced scope constraints.

Called via registry:
    module:   toolbox.dev.hayeong_dev_tool
    function: run

Params (via task_params):
    target_path         (str)  — relative path from project root
    change_description  (str)  — what the change does and why (Hayeong's reasoning)
    change_type         (str)  — "edit" | "prompt_update" | "new_file" | "structural"
    proposed_content    (str)  — the actual content/code to apply
    requires_review     (bool) — Hayeong can self-flag for James review

Returns:
    str — outcome summary
    raises ValueError for bad input (caught by _execute_tool)
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

ROOT_DIR     = Path(__file__).parent.parent.parent
HANDOFFS_DIR = ROOT_DIR / "handoffs"
REVIEW_DIR   = ROOT_DIR / "pending_james_review"
LOG_FILE     = ROOT_DIR / "logs" / "dev_tool_log.json"
PROMPT_HIST  = ROOT_DIR / "logs" / "prompt_history"

MAX_DIRECT_EDIT_LINES = 500

# ── Scope tables ──────────────────────────────────────────────────────

# Exact relative paths (from project root) that are always blocked
_BLOCKED_EXACT = {
    "main.py",
    "app_manager.py",
    "brain/identity_constitutional.json",
    "brain/identity_behavioral.json",
    "toolbox/registry.json",
}

# Path prefixes that are blocked (covers whole directories)
_BLOCKED_PREFIXES = (
    "brain/",
)

# Exceptions carved out of the blocked prefixes above
_BLOCKED_PREFIX_EXCEPTIONS = {
    "brain/identity_living.json",
}

# Path prefixes that are explicitly in scope for direct edit
_ALLOWED_PREFIXES = (
    "toolbox/",
    "memory/self_snapshots/",
)


# ── Path validation ───────────────────────────────────────────────────

def _normalize(target_path: str) -> str:
    """
    Resolve target_path relative to project root.
    Returns the normalized path relative to ROOT_DIR as a forward-slash string.
    Raises ValueError if path escapes the project root.
    """
    raw = Path(target_path)
    if raw.is_absolute():
        resolved = raw.resolve()
    else:
        resolved = (ROOT_DIR / raw).resolve()

    try:
        rel = resolved.relative_to(ROOT_DIR.resolve())
    except ValueError:
        raise ValueError(f"Path '{target_path}' escapes the project root — blocked.")

    return rel.as_posix()


def _scope_check(rel_path: str) -> str:
    """
    Returns "allowed", "blocked", or "out_of_scope".
    out_of_scope → handoff (not in an explicitly allowed area).
    """
    # Exact block
    if rel_path in _BLOCKED_EXACT:
        return "blocked"

    # Prefix block (with exceptions)
    for prefix in _BLOCKED_PREFIXES:
        if rel_path.startswith(prefix):
            if rel_path not in _BLOCKED_PREFIX_EXCEPTIONS:
                return "blocked"

    # Explicit allowlist
    for prefix in _ALLOWED_PREFIXES:
        if rel_path.startswith(prefix):
            return "allowed"

    # Anything else (root-level files not in blocked list, etc.) → handoff
    return "out_of_scope"


# ── File operations ───────────────────────────────────────────────────

def _backup(target: Path) -> str | None:
    """Copy target to target.backup.YYYYMMDD_HHMMSS. Returns backup path or None."""
    if not target.exists():
        return None
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup  = target.with_suffix(f".backup.{ts}")
    shutil.copy2(target, backup)
    return str(backup)


def _backup_prompt(target: Path) -> str | None:
    """
    For prompt files: copy to .backup (latest) AND to prompt_history/{name}/{ts}.
    Returns path to the latest backup.
    """
    if not target.exists():
        return None

    # Latest backup (overwritten each time)
    backup = target.with_suffix(".backup" + target.suffix)
    shutil.copy2(target, backup)

    # Full history
    hist_dir = PROMPT_HIST / target.stem
    hist_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(target, hist_dir / f"{target.stem}_{ts}{target.suffix}")

    return str(backup)


def _apply_write(target: Path, content: str):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


# ── Logging and state ─────────────────────────────────────────────────

def _log(target: str, change_type: str, description: str,
         outcome: str, backup: str | None, notes: str):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        entries = json.loads(LOG_FILE.read_text(encoding="utf-8")) if LOG_FILE.exists() else []
    except Exception:
        entries = []
    entries.append({
        "timestamp":      datetime.now().isoformat(),
        "target":         target,
        "change_type":    change_type,
        "description":    description,
        "outcome":        outcome,
        "backup_created": backup is not None,
        "backup_path":    backup,
        "notes":          notes,
    })
    LOG_FILE.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_state(target: str, outcome: str, message: str):
    """Write outcome to shared state bus so reasoning layer sees it."""
    try:
        from brain.state.core_manager import write_section
        write_section("dev_tool_last_result", {
            "timestamp":      datetime.now().isoformat(),
            "target":         target,
            "outcome":        outcome,
            "message":        message,
            "action_required": outcome in ("blocked", "handoff"),
        })
    except Exception:
        pass  # state write is best-effort — never crash the tool


# ── Output file writers ───────────────────────────────────────────────

def _write_handoff(target: str, description: str, change_type: str,
                   content: str, priority: str = "normal") -> str:
    HANDOFFS_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = HANDOFFS_DIR / f"handoff_{ts}.md"
    path.write_text(f"""# Hayeong Dev Handoff — {ts}

## Requested by
Hayeong (reasoning layer)

## Target
{target}

## Change Type
{change_type}

## Description
{description}

## Proposed Content
```
{content}
```

## Status
Pending Claude Code execution

## Priority
{priority}
""", encoding="utf-8")
    return str(path)


def _write_blocked_review(target: str, description: str, change_type: str,
                          content: str, reason: str) -> str:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REVIEW_DIR / f"{ts}_review_needed.md"
    path.write_text(f"""# Hayeong Change — James Review Required — {ts}

## What Hayeong wanted to change
Target: {target}
Type: {change_type}

## Why it was blocked
{reason}

## Hayeong's reasoning
{description}

## Proposed content
```
{content}
```

## Action
Review above and apply manually if appropriate.
""", encoding="utf-8")
    return str(path)


# ── Core tool ─────────────────────────────────────────────────────────

def hayeong_dev_tool(
    target_path: str,
    change_description: str,
    change_type: str,
    proposed_content: str = "",
    requires_review: bool = False,
) -> dict:
    """
    Validate scope and route to applied / handoff / blocked outcome.
    Returns {"status": ..., "message": ..., "log_path": str(LOG_FILE)}.
    """
    if not target_path:
        raise ValueError("target_path is required.")
    if change_type not in ("edit", "prompt_update", "new_file", "structural"):
        raise ValueError(f"Unknown change_type '{change_type}'. Use edit, prompt_update, new_file, or structural.")

    # Normalize and scope-check
    try:
        rel = _normalize(target_path)
    except ValueError as e:
        outcome = "blocked"
        reason  = str(e)
        review  = _write_blocked_review(target_path, change_description, change_type, proposed_content, reason)
        _log(target_path, change_type, change_description, outcome, None, reason)
        msg = f"Blocked: {reason} Review written to: {review}"
        _write_state(target_path, outcome, msg)
        return {"status": outcome, "message": msg, "log_path": str(LOG_FILE)}

    scope = _scope_check(rel)
    target = ROOT_DIR / rel

    # Self-flagged for review → always blocked
    if requires_review:
        reason = "Hayeong self-flagged this change for James review."
        review = _write_blocked_review(rel, change_description, change_type, proposed_content, reason)
        _log(rel, change_type, change_description, "blocked", None, reason)
        msg = f"Blocked (self-flagged). Review written to: {review}"
        _write_state(rel, "blocked", msg)
        return {"status": "blocked", "message": msg, "log_path": str(LOG_FILE)}

    # Hard block
    if scope == "blocked":
        reason = f"'{rel}' is a protected path and cannot be modified by the reasoning layer."
        review = _write_blocked_review(rel, change_description, change_type, proposed_content, reason)
        _log(rel, change_type, change_description, "blocked", None, reason)
        msg = f"Blocked: {reason} Review written to: {review}"
        _write_state(rel, "blocked", msg)
        return {"status": "blocked", "message": msg, "log_path": str(LOG_FILE)}

    # Structural changes always route to handoff
    if change_type == "structural" or scope == "out_of_scope":
        priority = "high" if scope == "out_of_scope" else "normal"
        handoff  = _write_handoff(rel, change_description, change_type, proposed_content, priority)
        _log(rel, change_type, change_description, "handoff", None, f"handoff: {handoff}")
        msg = f"Handoff written for James pickup: {handoff}"
        _write_state(rel, "handoff", msg)
        return {"status": "handoff", "message": msg, "log_path": str(LOG_FILE)}

    # New files inside Toolbox — allowed directly; outside Toolbox — handoff
    if change_type == "new_file":
        if rel.startswith("toolbox/"):
            pass  # fall through to apply
        else:
            handoff = _write_handoff(rel, change_description, change_type, proposed_content, "normal")
            _log(rel, change_type, change_description, "handoff", None, f"handoff: {handoff}")
            msg = f"New file outside Toolbox — handoff written: {handoff}"
            _write_state(rel, "handoff", msg)
            return {"status": "handoff", "message": msg, "log_path": str(LOG_FILE)}

    # Line count guard for plain edits
    line_count = len(proposed_content.splitlines())
    if change_type == "edit" and line_count > MAX_DIRECT_EDIT_LINES:
        handoff = _write_handoff(rel, change_description, change_type, proposed_content)
        _log(rel, change_type, change_description, "handoff", None,
             f"escalated: {line_count} lines exceeds {MAX_DIRECT_EDIT_LINES} limit")
        msg = f"Change too large ({line_count} lines) — handoff written: {handoff}"
        _write_state(rel, "handoff", msg)
        return {"status": "handoff", "message": msg, "log_path": str(LOG_FILE)}

    # ── Direct apply ──────────────────────────────────────────────────
    if change_type == "prompt_update":
        backup = _backup_prompt(target)
    else:
        backup = _backup(target)

    _apply_write(target, proposed_content)
    _log(rel, change_type, change_description, "applied", backup, "")
    msg = f"Change applied to {rel}. Backup: {backup or 'none (new file)'}."
    _write_state(rel, "applied", msg)
    return {"status": "applied", "message": msg, "log_path": str(LOG_FILE)}


# ── Registry entry point ──────────────────────────────────────────────

def run(description: str, params: dict) -> str:
    """Entry point called by main.py task loop via registry."""
    result = hayeong_dev_tool(
        target_path=params.get("target_path", ""),
        change_description=params.get("change_description", description),
        change_type=params.get("change_type", "edit"),
        proposed_content=params.get("proposed_content", ""),
        requires_review=bool(params.get("requires_review", False)),
    )
    return f"[{result['status']}] {result['message']}"
