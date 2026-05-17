"""
Toolbox/handoff_reader/handoff_reader.py

Reads a handoff note and implements the tool it describes.
Hayeong uses this to build her own tools from handoff specs.

Called via registry:
    module:   toolbox.handoff_reader.handoff_reader
    function: run

Params:
    operation     (str)  — "implement" | "read" | "list" | "status"
    handoff_path  (str)  — path to handoff .md file (for implement/read)
    tool_name     (str)  — override tool name (optional)
    dry_run       (bool) — if true, show plan without executing (default: false)

Returns:
    str — implementation summary or error message
"""

import json
import importlib
import re
from datetime import datetime
from pathlib import Path

ROOT_DIR     = Path(__file__).parent.parent.parent
HANDOFFS_DIR = ROOT_DIR / "handoffs"
TOOLBOX_DIR  = ROOT_DIR / "Toolbox"
REGISTRY     = ROOT_DIR / "Toolbox" / "registry.json"
LOG_FILE     = ROOT_DIR / "Logs" / "handoff_reader_log.json"


def run(description: str, params: dict) -> str:
    """Entry point. Always returns a string."""
    try:
        operation = params.get("operation", "implement").lower()
        if operation == "list":
            return _list_handoffs()
        elif operation == "read":
            path = params.get("handoff_path", "")
            return _read_handoff(path)
        elif operation == "status":
            return _implementation_status()
        elif operation == "implement":
            path    = params.get("handoff_path", "")
            dry_run = str(params.get("dry_run", "false")).lower() == "true"
            return _implement(path, dry_run)
        else:
            return f"Unknown operation '{operation}'. Use: implement, read, list, status"
    except Exception as e:
        return f"handoff_reader error: {e}"


def _list_handoffs() -> str:
    """List all handoff files available for implementation."""
    if not HANDOFFS_DIR.exists():
        return "No handoffs directory found."
    files = sorted(HANDOFFS_DIR.glob("*.md"))
    if not files:
        return "No handoff files found in handoffs/"
    lines = [f"Found {len(files)} handoff file(s):"]
    for f in files:
        size = f.stat().st_size
        lines.append(f"  - {f.name} ({size} bytes)")
    return "\n".join(lines)


def _read_handoff(path: str) -> str:
    """Read and summarize a handoff file."""
    resolved = _resolve_path(path)
    if not resolved:
        return f"Handoff file not found: {path}"
    content = resolved.read_text(encoding="utf-8")
    summary = content[:2000]
    if len(content) > 2000:
        summary += f"\n\n[...truncated — {len(content)} total chars]"
    return summary


def _resolve_path(path: str) -> Path | None:
    """Find the handoff file — by full path, or by name in handoffs/."""
    if not path:
        return None
    p = Path(path)
    if p.exists():
        return p
    candidate = HANDOFFS_DIR / path
    if candidate.exists():
        return candidate
    candidate = HANDOFFS_DIR / f"{path}.md"
    if candidate.exists():
        return candidate
    return None


def _extract_tool_name(content: str, override: str = "") -> str:
    """Extract tool name from handoff content."""
    if override:
        return override
    match = re.search(r'Toolbox/(\w+)', content[:500])
    if match:
        return match.group(1).lower()
    match = re.search(r'action:\s*(\w+)', content)
    if match:
        return match.group(1).lower()
    return ""


def _extract_files(content: str) -> list[dict]:
    """
    Extract file specs from handoff content.

    Supports two formats:

    Format 1 (preferred) — explicit FILE: marker:
        FILE: Toolbox/sensor_tool/sensor_tool.py
        ```python
        <code>
        ```

    Format 2 (fallback) — path on the line immediately before code block:
        `Toolbox/sensor_tool/sensor_tool.py`
        ```python
        <code>
        ```

    Returns list of {path, content, type} dicts.
    Only extracts files whose path starts with a known project directory.
    Ignores code blocks that are interface examples or param snippets.
    """
    files = []

    # ── Format 1: explicit FILE: marker ──────────────────────────────
    file_marker_pattern = re.compile(
        r'^FILE:\s*([\w/\\.]+\.(?:py|json|md|txt|bat))\s*\n'
        r'```(?:python|json|bash|batch|)?\n(.*?)```',
        re.DOTALL | re.MULTILINE
    )
    for match in file_marker_pattern.finditer(content):
        path = match.group(1).strip()
        code = match.group(2).strip()
        if not _is_valid_file_path(path):
            continue
        ext   = Path(path).suffix
        ftype = "python" if ext == ".py" else \
                "json"   if ext == ".json" else \
                "text"
        files.append({"path": path, "content": code, "type": ftype})

    if files:
        return files

    # ── Format 2: path line immediately before code block ────────────
    # Path line must be IMMEDIATELY before the opening fence — no
    # intervening lines — to avoid grabbing unrelated code blocks.
    path_then_fence = re.compile(
        r'(?:^|\n)`{0,3}([\w/\\.]+\.(?:py|json|md|txt|bat))`{0,3}\s*\n'
        r'```(?:python|json|bash|batch|)?\n(.*?)```',
        re.DOTALL | re.MULTILINE
    )
    for match in path_then_fence.finditer(content):
        path = match.group(1).strip()
        code = match.group(2).strip()
        if not _is_valid_file_path(path):
            continue
        ext   = Path(path).suffix
        ftype = "python" if ext == ".py" else \
                "json"   if ext == ".json" else \
                "text"
        files.append({"path": path, "content": code, "type": ftype})

    return files


def _is_valid_file_path(path: str) -> bool:
    """
    Returns True only for paths that look like real project files.
    Rejects interface examples, params blocks, and unrooted paths.
    """
    valid_prefixes = (
        "Toolbox/", "toolbox/",
        "Brain/",   "brain/",
        "Memory/",  "memory/",
        "Logs/",    "logs/",
        "Dashboard/",
    )
    if not any(path.startswith(p) for p in valid_prefixes):
        return False
    if Path(path).suffix not in (".py", ".json", ".md", ".txt", ".bat"):
        return False
    if any(c in path for c in (" ", "|", "[", "]", "<", ">")):
        return False
    return True


def _implement(path: str, dry_run: bool = False) -> str:
    """
    Core implementation logic.
    Reads the handoff, extracts files, calls dev tool to create each one.
    """
    resolved = _resolve_path(path)
    if not resolved:
        return f"Cannot find handoff file: {path}"

    content   = resolved.read_text(encoding="utf-8")
    tool_name = _extract_tool_name(content)
    files     = _extract_files(content)

    if not files:
        return (
            f"Could not extract file specs from {resolved.name}. "
            f"The handoff may need manual implementation. "
            f"Tool name detected: '{tool_name or 'unknown'}'"
        )

    if dry_run:
        lines = [f"DRY RUN — {resolved.name}"]
        lines.append(f"Tool name: {tool_name or 'unknown'}")
        lines.append(f"Files to create: {len(files)}")
        for f in files:
            lines.append(f"  - {f['path']} ({len(f['content'])} chars, {f['type']})")
        return "\n".join(lines)

    results   = []
    succeeded = 0
    failed    = 0

    try:
        from toolbox.dev.hayeong_dev_tool import hayeong_dev_tool
    except ImportError as e:
        return f"Cannot import dev tool: {e}"

    for file_spec in files:
        file_path    = file_spec["path"]
        file_content = file_spec["content"]

        target      = ROOT_DIR / file_path
        change_type = "edit" if target.exists() else "new_file"

        try:
            result = hayeong_dev_tool(
                target_path=file_path,
                change_description=f"Implementing {tool_name} tool from handoff {resolved.name}",
                change_type=change_type,
                proposed_content=file_content,
                requires_review=False,
            )
            status = result.get("status", "unknown")
            if status == "applied":
                results.append(f"  OK  {file_path}")
                succeeded += 1
            elif status == "handoff":
                results.append(f"  --> {file_path} — routed to handoff (needs James)")
                failed += 1
            else:
                results.append(f"  ERR {file_path} — {result.get('message', 'blocked')}")
                failed += 1
        except Exception as e:
            results.append(f"  ERR {file_path} — exception: {e}")
            failed += 1

    verify_msg = ""
    if tool_name and succeeded > 0:
        try:
            mod = importlib.import_module(f"toolbox.{tool_name}.{tool_name}")
            if hasattr(mod, "run"):
                verify_msg = f"\nVerification: toolbox.{tool_name} imports correctly, run() found."
            else:
                verify_msg = f"\nVerification: module imports but run() not found."
        except ImportError as e:
            verify_msg = f"\nVerification failed (import error): {e}"

    _log_run(resolved.name, tool_name, succeeded, failed, results)

    summary = [
        f"Implementation of '{tool_name}' from {resolved.name}:",
        f"  {succeeded} file(s) created, {failed} routed/failed",
        "",
    ] + results
    if verify_msg:
        summary.append(verify_msg)
    if failed > 0:
        summary.append("\nFiles routed to handoff still need Claude Code or James.")

    return "\n".join(summary)


def _implementation_status() -> str:
    """Report on recent implementation runs."""
    if not LOG_FILE.exists():
        return "No implementation runs logged yet."
    try:
        log    = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        recent = log[-5:] if len(log) > 5 else log
        lines  = [f"Last {len(recent)} implementation run(s):"]
        for entry in reversed(recent):
            lines.append(
                f"  [{entry['timestamp'][:10]}] {entry['tool_name']} — "
                f"{entry['succeeded']} ok / {entry['failed']} failed"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Could not read log: {e}"


def _log_run(handoff_name: str, tool_name: str, succeeded: int,
             failed: int, results: list) -> None:
    """Append implementation run to log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        log = json.loads(LOG_FILE.read_text(encoding="utf-8")) if LOG_FILE.exists() else []
    except Exception:
        log = []
    log.append({
        "timestamp":    datetime.now().isoformat(),
        "handoff_name": handoff_name,
        "tool_name":    tool_name,
        "succeeded":    succeeded,
        "failed":       failed,
        "details":      results,
    })
    LOG_FILE.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
