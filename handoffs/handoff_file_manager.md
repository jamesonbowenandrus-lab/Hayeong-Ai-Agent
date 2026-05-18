# HANDOFF — file_manager tool
*For: Hayeong to implement via handoff_reader*
*Layer: Control — how Hayeong acts on the filesystem*

---

## What This Tool Does

Gives Hayeong the ability to read, write, list, and manage files on disk.
This is how she stores her own notes, reads logs, manages her memory,
and works with any file-based data.

All operations are scoped to the project root for safety.
She cannot write outside the project directory.

---

FILE: Toolbox/file_manager/file_manager.py
```python
"""
Toolbox/file_manager/file_manager.py

Control layer tool — Hayeong's hands on the filesystem.
Read, write, list, append, and delete files within the project.

Operations:
    read    — read a file and return its contents
    write   — write content to a file (creates if not exists, overwrites if exists)
    append  — append content to a file (creates if not exists)
    list    — list files in a directory
    exists  — check if a file or directory exists
    delete  — delete a file (with safety checks)
    mkdir   — create a directory

All paths are relative to the project root.
Writes outside the project root are blocked.

Params:
    operation (str) — one of the operations above
    path      (str) — file or directory path, relative to project root
    content   (str) — content to write or append (write/append operations)
    pattern   (str) — glob pattern for list (default: *)

Returns:
    str — result or error message, never raises
"""

from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent


def run(description: str, params: dict) -> str:
    operation = params.get("operation", "").strip().lower()
    path_str  = (
        params.get("path") or
        params.get("file_path") or
        params.get("filepath") or
        params.get("file") or
        ""
    ).strip()

    try:
        if operation == "read":
            return _read(path_str)
        elif operation == "write":
            return _write(path_str, params.get("content", ""))
        elif operation == "append":
            return _append(path_str, params.get("content", ""))
        elif operation == "list":
            return _list(path_str, params.get("pattern", "*"))
        elif operation == "exists":
            return _exists(path_str)
        elif operation == "delete":
            return _delete(path_str)
        elif operation == "mkdir":
            return _mkdir(path_str)
        else:
            return (
                f"[file_manager] Unknown operation: '{operation}'. "
                f"Use: read, write, append, list, exists, delete, mkdir"
            )
    except Exception as e:
        return f"[file_manager] Error: {e}"


# ── Safety ────────────────────────────────────────────────────────────

def _resolve(path_str: str) -> Path:
    """
    Resolve path relative to project root.
    Raises ValueError if it escapes the project root.
    """
    if not path_str:
        raise ValueError("No path provided.")
    raw = Path(path_str)
    if raw.is_absolute():
        resolved = raw.resolve()
    else:
        resolved = (ROOT_DIR / raw).resolve()
    try:
        resolved.relative_to(ROOT_DIR.resolve())
    except ValueError:
        raise ValueError(
            f"Path '{path_str}' is outside the project root — blocked for safety."
        )
    return resolved


# ── Operations ────────────────────────────────────────────────────────

def _read(path_str: str) -> str:
    path = _resolve(path_str)
    if not path.exists():
        return f"[file_manager] File not found: {path_str}"
    if not path.is_file():
        return f"[file_manager] Not a file: {path_str}"

    content = path.read_text(encoding="utf-8", errors="replace")
    size    = len(content)

    # Truncate very large files
    max_chars = 8000
    truncated = ""
    if size > max_chars:
        content   = content[:max_chars]
        truncated = f"\n\n[... file truncated at {max_chars} chars — full size: {size} chars]"

    return f"Contents of {path_str}:\n\n{content}{truncated}"


def _write(path_str: str, content: str) -> str:
    path = _resolve(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    path.write_text(content, encoding="utf-8")
    action = "Overwrote" if existed else "Created"
    return f"[file_manager] {action} {path_str} ({len(content)} chars written)."


def _append(path_str: str, content: str) -> str:
    path = _resolve(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(content)
    return f"[file_manager] Appended {len(content)} chars to {path_str}."


def _list(path_str: str, pattern: str) -> str:
    path = _resolve(path_str) if path_str else ROOT_DIR
    if not path.exists():
        return f"[file_manager] Directory not found: {path_str}"
    if not path.is_dir():
        return f"[file_manager] Not a directory: {path_str}"

    items = sorted(path.glob(pattern))
    if not items:
        return f"[file_manager] No files matching '{pattern}' in {path_str or 'project root'}."

    lines = [f"Contents of {path_str or 'project root'} (pattern: {pattern}):"]
    for item in items:
        rel     = item.relative_to(ROOT_DIR)
        suffix  = "/" if item.is_dir() else ""
        size    = f"  ({item.stat().st_size} bytes)" if item.is_file() else ""
        lines.append(f"  {rel}{suffix}{size}")

    return "\n".join(lines)


def _exists(path_str: str) -> str:
    try:
        path = _resolve(path_str)
    except ValueError as e:
        return f"[file_manager] {e}"
    if path.exists():
        kind = "directory" if path.is_dir() else "file"
        return f"[file_manager] Exists ({kind}): {path_str}"
    return f"[file_manager] Does not exist: {path_str}"


def _delete(path_str: str) -> str:
    path = _resolve(path_str)
    if not path.exists():
        return f"[file_manager] Nothing to delete — not found: {path_str}"
    if not path.is_file():
        return f"[file_manager] Delete only works on files, not directories: {path_str}"

    # Safety: never delete core files
    rel = path.relative_to(ROOT_DIR).as_posix()
    protected = {"main.py", "brain/config.py", "toolbox/registry.json"}
    if rel in protected:
        return f"[file_manager] Blocked: '{rel}' is a protected file."

    path.unlink()
    return f"[file_manager] Deleted: {path_str}"


def _mkdir(path_str: str) -> str:
    path = _resolve(path_str)
    if path.exists():
        return f"[file_manager] Already exists: {path_str}"
    path.mkdir(parents=True, exist_ok=True)
    return f"[file_manager] Created directory: {path_str}"
```

FILE: Toolbox/file_manager/__init__.py
```python
```

FILE: Toolbox/file_manager/README.md
```
# Toolbox/file_manager

Control layer tool. Hayeong's hands on the filesystem.

## Operations

All paths are relative to the project root. Writes outside the project are blocked.

### read
Read a file and return its contents (truncates at 8000 chars for large files).
  path: relative path to file

### write
Write content to a file. Creates parent directories if needed. Overwrites existing.
  path   : relative path to file
  content: text to write

### append
Append content to a file. Creates if not exists.
  path   : relative path to file
  content: text to append

### list
List files in a directory.
  path   : relative path to directory (or empty for project root)
  pattern: glob pattern (default: *)

### exists
Check if a file or directory exists.
  path: relative path to check

### delete
Delete a file. Core files are protected.
  path: relative path to file

### mkdir
Create a directory (and any missing parents).
  path: relative path to new directory

## Safety Rules
- All paths resolved relative to project root
- Cannot write or delete outside project root
- main.py, brain/config.py, toolbox/registry.json are protected from deletion
- Directories cannot be deleted (use Claude Code for that)
```
