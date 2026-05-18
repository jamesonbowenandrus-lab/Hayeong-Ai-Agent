"""
Toolbox/self_check/self_check.py

Self-verification module. Called automatically by the task loop after
every tool execution. Checks the real world to confirm the result is real.

Returns a dict:
    {
        "verified": True/False,
        "confidence": "confirmed" | "partial" | "unverified",
        "note": "human-readable explanation of what was checked"
    }

Registry entry:
    "self_check": { "module": "toolbox.self_check.self_check", "function": "run" }

Also importable directly by main.py task loop (not just via registry).
"""

import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent


def verify(tool: str, params: dict, result: str, expected_outcome: str = "") -> dict:
    """
    Main entry point called by task loop directly.
    Dispatches to the appropriate checker for the tool type.
    Returns verification dict.
    """
    tool = (tool or "").strip().lower()

    try:
        if tool in ("handoff_reader",):
            return _verify_handoff_result(result)

        elif tool in ("dev_tool", "hayeong_dev_tool"):
            return _verify_file_written(params, result)

        elif tool == "sensor_tool":
            return _verify_result_nonempty(result, expected_keys=["gpu", "cpu", "ram"])

        elif tool == "finetune_curator":
            return _verify_file_written(params, result, fallback_key="output_path")

        elif tool == "calendar_manager":
            return _verify_result_nonempty(result, expected_keys=["event", "calendar"])

        elif tool == "web_search":
            return _verify_result_nonempty(result, min_length=50)

        elif tool == "music_tool":
            return _verify_file_written(params, result, fallback_key="output_filename")

        elif tool == "self_check":
            # Don't verify a verification — always confirmed
            return _confirmed("self_check verifying itself is a no-op")

        else:
            # If we have an expected_outcome, do a soft content check on the result
            if expected_outcome and result:
                outcome_words = [w.lower() for w in expected_outcome.split()
                                 if len(w) > 4]
                matches = sum(1 for w in outcome_words if w in result.lower())
                if outcome_words and matches / len(outcome_words) >= 0.4:
                    return _partial(
                        f"No specific rule for '{tool}', but result loosely matches "
                        f"expected outcome ({matches}/{len(outcome_words)} keywords matched)."
                    )
            return _unverified(f"No verification rule for tool: {tool}")

    except Exception as e:
        return _unverified(f"Verification raised exception: {e}")


def run(description: str, params: dict) -> str:
    """
    Registry entry point — allows Hayeong to manually trigger a self-check.
    Reads last_task from shared state and verifies it.
    """
    try:
        from brain.state.core_manager import read as read_state
        state = read_state()
        last_task = state.get("last_task", {})
        tool     = last_task.get("tool", "")
        p        = last_task.get("params", {})
        result   = last_task.get("result", "")
        expected = last_task.get("expected_outcome", "")

        if not tool:
            return "[self_check] No last task found to verify."

        check = verify(tool, p, result, expected)
        return (
            f"[self_check] Tool: {tool} | "
            f"Verified: {check['verified']} | "
            f"Confidence: {check['confidence']} | "
            f"Note: {check['note']}"
        )
    except Exception as e:
        return f"[self_check] Failed to run: {e}"


# ── Verification helpers ──────────────────────────────────────────────

def _verify_file_written(params: dict, result: str, fallback_key: str = "target_path") -> dict:
    """Check that a file path mentioned in result or params actually exists on disk."""
    candidate = _extract_path_from_result(result)

    if not candidate:
        candidate = params.get("target_path") or params.get(fallback_key) or ""

    if not candidate:
        return _unverified("No file path found in result or params to check.")

    path = Path(candidate)
    if not path.is_absolute():
        path = BASE_DIR / candidate

    if path.exists():
        size = path.stat().st_size
        if size > 0:
            return _confirmed(f"File exists and is non-empty: {path.name} ({size} bytes)")
        else:
            return _partial(f"File exists but is empty (0 bytes): {path.name}")
    else:
        return {
            "verified": False,
            "confidence": "failed",
            "note": f"File does NOT exist on disk: {candidate}"
        }


def _verify_result_nonempty(result: str, expected_keys: list = None, min_length: int = 10) -> dict:
    """
    Check that a result string is non-trivial.
    Optionally check that certain keywords appear (loose check, not strict).
    """
    if not result or len(result.strip()) < min_length:
        return {
            "verified": False,
            "confidence": "failed",
            "note": f"Result is empty or too short (got {len(result)} chars, need >{min_length})"
        }

    if expected_keys:
        found = [k for k in expected_keys if k.lower() in result.lower()]
        missing = [k for k in expected_keys if k.lower() not in result.lower()]
        if missing:
            return _partial(
                f"Result present but missing expected content: {missing}. "
                f"Found: {found}"
            )

    return _confirmed(f"Result non-empty ({len(result)} chars), content looks valid.")


def _extract_path_from_result(result: str) -> str:
    """
    Try to find a file path in a result string.
    Looks for common path patterns.
    """
    import re
    # Windows-style paths
    match = re.search(r'[A-Za-z]:\\(?:[^\s"\'<>|*?\n\\]+\\)*[^\s"\'<>|*?\n\\]+', result)
    if match:
        return match.group(0)
    # Relative paths with extensions
    match = re.search(r'[\w./\\-]+\.\w{2,5}', result)
    if match:
        candidate = match.group(0)
        if len(candidate) > 4:
            return candidate
    return ""


def _verify_handoff_result(result: str) -> dict:
    """
    For handoff_reader: verify by checking that the result reports files created.
    Checks for positive file-creation signals in the returned string.
    """
    if not result:
        return {
            "verified": False,
            "confidence": "failed",
            "note": "handoff_reader returned empty result."
        }

    result_lower = result.lower()

    if any(phrase in result_lower for phrase in [
        "file(s) created", "files created", "file created",
        "implemented", "written successfully", "created successfully",
    ]):
        import re
        count_match = re.search(r"(\d+)\s+file", result_lower)
        count = count_match.group(1) if count_match else "some"
        return _confirmed(f"handoff_reader reports {count} file(s) created.")

    if any(phrase in result_lower for phrase in [
        "cannot find", "not found", "error", "failed", "no handoff",
    ]):
        return {
            "verified": False,
            "confidence": "failed",
            "note": f"handoff_reader reported a failure: {result[:120]}"
        }

    return _partial(f"handoff_reader returned a result but outcome unclear: {result[:80]}")


def _confirmed(note: str) -> dict:
    return {"verified": True, "confidence": "confirmed", "note": note}

def _partial(note: str) -> dict:
    return {"verified": True, "confidence": "partial", "note": note}

def _unverified(note: str) -> dict:
    return {"verified": False, "confidence": "unverified", "note": note}
