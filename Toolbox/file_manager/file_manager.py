"""
toolbox/file_manager/file_manager.py

Hayeong's file management tool.
Read, write, append, list, check, delete, and create directories.
All paths are relative to the project root (H:/hayeong/) or absolute.

Called via registry:
    module:   toolbox.file_manager.file_manager
    function: run

Params:
    operation  (str) — read | write | append | list | exists | delete | mkdir
    path       (str) — file or directory path (relative to project root or absolute)
    content    (str) — text to write/append (write and append operations)
    pattern    (str) — glob pattern for list operation (default: "*")
    encoding   (str) — file encoding (default: "utf-8")

Returns:
    str — "[SUCCESS] ..." | "[ERROR] ..." | "[PARTIAL] ..."
    Never raises. All errors are returned as strings.
"""

import glob as glob_module
from pathlib import Path

# Project root — used to resolve relative paths
_ROOT = Path(__file__).parent.parent.parent


def run(description: str, params: dict) -> str:
    try:
        return _dispatch(description, params)
    except Exception as e:
        return f"[ERROR] file_manager: {e}"


def _resolve(path_str: str) -> Path:
    """Resolve a path — absolute or relative to project root."""
    p = Path(path_str)
    if p.is_absolute():
        return p
    return (_ROOT / p).resolve()


def _dispatch(description: str, params: dict) -> str:
    operation = str(params.get("operation", "")).lower().strip()
    if not operation:
        return (
            "[ERROR] file_manager: 'operation' param required. "
            "Options: read, write, append, list, exists, delete, mkdir"
        )

    path_str = str(params.get("path", "")).strip()

    if operation == "read":
        if not path_str:
            return "[ERROR] file_manager: 'path' param required for read"
        return _read(path_str, params.get("encoding", "utf-8"))

    if operation == "write":
        if not path_str:
            return "[ERROR] file_manager: 'path' param required for write"
        content = params.get("content", "")
        if content is None:
            content = ""
        return _write(path_str, str(content), params.get("encoding", "utf-8"))

    if operation == "append":
        if not path_str:
            return "[ERROR] file_manager: 'path' param required for append"
        content = params.get("content", "")
        if content is None:
            content = ""
        return _append(path_str, str(content), params.get("encoding", "utf-8"))

    if operation == "list":
        return _list(path_str or ".", str(params.get("pattern", "*")))

    if operation == "exists":
        if not path_str:
            return "[ERROR] file_manager: 'path' param required for exists"
        return _exists(path_str)

    if operation == "delete":
        if not path_str:
            return "[ERROR] file_manager: 'path' param required for delete"
        return _delete(path_str)

    if operation == "mkdir":
        if not path_str:
            return "[ERROR] file_manager: 'path' param required for mkdir"
        return _mkdir(path_str)

    return (
        f"[ERROR] file_manager: unknown operation '{operation}'. "
        "Options: read, write, append, list, exists, delete, mkdir"
    )


def _read(path_str: str, encoding: str) -> str:
    path = _resolve(path_str)
    if not path.exists():
        return f"[ERROR] file_manager: file not found: {path}"
    if not path.is_file():
        return f"[ERROR] file_manager: '{path}' is not a file"
    try:
        content = path.read_text(encoding=encoding)
        size    = len(content)
        lines   = content.count("\n") + 1
        # Return up to 4000 chars to avoid flooding context
        preview = content[:4000]
        truncated = size > 4000
        result = f"[SUCCESS] read '{path_str}' — {lines} lines, {size} chars"
        if truncated:
            result += f" (showing first 4000 of {size})"
        result += f"\n{preview}"
        if truncated:
            result += "\n[... truncated ...]"
        return result
    except Exception as e:
        return f"[ERROR] file_manager: read failed: {e}"


def _write(path_str: str, content: str, encoding: str) -> str:
    path = _resolve(path_str)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)
        return f"[SUCCESS] wrote {len(content)} chars to '{path_str}'"
    except Exception as e:
        return f"[ERROR] file_manager: write failed: {e}"


def _append(path_str: str, content: str, encoding: str) -> str:
    path = _resolve(path_str)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding=encoding) as f:
            f.write(content)
        return f"[SUCCESS] appended {len(content)} chars to '{path_str}'"
    except Exception as e:
        return f"[ERROR] file_manager: append failed: {e}"


def _list(path_str: str, pattern: str) -> str:
    path = _resolve(path_str)
    if not path.exists():
        return f"[ERROR] file_manager: directory not found: {path}"
    if not path.is_dir():
        return f"[ERROR] file_manager: '{path}' is not a directory"
    try:
        matches = sorted(path.glob(pattern))
        if not matches:
            return f"[SUCCESS] list '{path_str}' (pattern: {pattern}) — 0 items found"
        entries = []
        for p in matches:
            if p.is_dir():
                entries.append(f"  [dir]  {p.name}/")
            else:
                size = p.stat().st_size
                entries.append(f"  [file] {p.name}  ({size} bytes)")
        return (
            f"[SUCCESS] list '{path_str}' (pattern: {pattern}) — {len(matches)} items:\n"
            + "\n".join(entries)
        )
    except Exception as e:
        return f"[ERROR] file_manager: list failed: {e}"


def _exists(path_str: str) -> str:
    path = _resolve(path_str)
    if path.exists():
        kind = "directory" if path.is_dir() else "file"
        return f"[SUCCESS] '{path_str}' exists ({kind})"
    return f"[SUCCESS] '{path_str}' does not exist"


def _delete(path_str: str) -> str:
    path = _resolve(path_str)
    if not path.exists():
        return f"[SUCCESS] '{path_str}' does not exist — nothing to delete"
    try:
        if path.is_file():
            path.unlink()
            return f"[SUCCESS] deleted file '{path_str}'"
        elif path.is_dir():
            import shutil
            shutil.rmtree(path)
            return f"[SUCCESS] deleted directory '{path_str}' and all contents"
        return f"[ERROR] file_manager: '{path_str}' is neither file nor directory"
    except Exception as e:
        return f"[ERROR] file_manager: delete failed: {e}"


def _mkdir(path_str: str) -> str:
    path = _resolve(path_str)
    try:
        path.mkdir(parents=True, exist_ok=True)
        return f"[SUCCESS] directory '{path_str}' created (or already exists)"
    except Exception as e:
        return f"[ERROR] file_manager: mkdir failed: {e}"
