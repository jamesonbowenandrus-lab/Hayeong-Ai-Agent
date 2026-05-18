# HANDOFF — Register Phase 2 Tools + Fix self_check
*For: Claude Code | Two small changes*

---

## Change 1 — Add Phase 2 tools to registry.json

Add these entries to `Toolbox/registry.json`:

```json
"web_search":   { "module": "toolbox.web_search.web_search",     "function": "run" },
"file_manager": { "module": "toolbox.file_manager.file_manager",  "function": "run" }
```

Also add to the PARAMS GUIDE in `build_presence_system()` in `main.py`:

Find the PARAMS GUIDE block and add these two lines:

```
- web_search    : {"operation": "search", "query": "search terms", "max_results": 5}
- file_manager  : {"operation": "read", "path": "relative/path/to/file.txt"}
```

---

## Change 2 — Fix self_check for handoff_reader verification

**Problem:** self_check verifies that the *handoff source file* exists on disk,
but handoff_reader deletes or ignores the source — what matters is the *output files*
that were created. Currently reports `failed` even when the implementation succeeded.

**File:** `Toolbox/self_check/self_check.py`

Find the `handoff_reader` dispatch case:

```python
        if tool in ("handoff_reader", "dev_tool", "hayeong_dev_tool"):
            return _verify_file_written(params, result)
```

Replace with:

```python
        if tool in ("handoff_reader",):
            return _verify_handoff_result(result)

        elif tool in ("dev_tool", "hayeong_dev_tool"):
            return _verify_file_written(params, result)
```

Then add this new function anywhere in the helpers section:

```python
def _verify_handoff_result(result: str) -> dict:
    """
    For handoff_reader: verify by checking that the result reports files created.
    handoff_reader returns something like:
      "Implementation of 'tool_name' from file.md:\n  3 file(s) created, ..."
    We check for a positive file-creation report in the result string.
    """
    if not result:
        return {
            "verified": False,
            "confidence": "failed",
            "note": "handoff_reader returned empty result."
        }

    result_lower = result.lower()

    # Positive signals — files were created
    if any(phrase in result_lower for phrase in [
        "file(s) created",
        "files created",
        "file created",
        "implemented",
        "written successfully",
        "created successfully",
    ]):
        # Try to extract the count for a more informative note
        import re
        count_match = re.search(r"(\d+)\s+file", result_lower)
        count = count_match.group(1) if count_match else "some"
        return _confirmed(f"handoff_reader reports {count} file(s) created.")

    # Negative signals — something went wrong
    if any(phrase in result_lower for phrase in [
        "cannot find",
        "not found",
        "error",
        "failed",
        "no handoff",
    ]):
        return {
            "verified": False,
            "confidence": "failed",
            "note": f"handoff_reader reported a failure: {result[:120]}"
        }

    # Ambiguous result — has content but unclear outcome
    return _partial(f"handoff_reader returned a result but outcome unclear: {result[:80]}")
```

---

## Verification

1. Apply changes.
2. Tell Hayeong: `implement the handoff file handoff_web_search.md`
3. Watch for `[task] Verified: confirmed — handoff_reader reports 3 file(s) created.`
4. Check filesystem: `Toolbox/web_search/` exists with web_search.py, __init__.py, README.md
5. Tell Hayeong: `search the web for "python asyncio tutorial"`
6. Watch for `[task] Executing: web_search` and a result with URLs

---

*End of handoff. Apply via Claude Code.*
