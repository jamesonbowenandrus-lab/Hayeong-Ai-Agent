# Hayeong — Decision Rescue System

This document covers the three-function pipeline in `main.py` that parses, repairs,
and normalises every decision the presence LLM returns before any action is taken.
The system is called informally "the rescue system" because its job is to salvage
usable decisions from LLM output that is structurally imperfect.

---

## Context: where it sits in the loop

The presence loop calls Qwen 32b (port 11435) and receives a raw string back.
That string contains Hayeong's spoken response to James **and** a JSON decision block
telling the task loop what to do next. The rescue system sits between "raw LLM output"
and "action dispatched to a tool":

```
LLM raw output
     ↓
_extract_decision()       ← tries 3 strategies to find the JSON block
     ↓
_ensure_decision_defaults()  ← fills missing fields with safe values
     ↓
_rescue_file_path()       ← moves any file path out of prose into params
     ↓
clean decision dict → task loop → tool call
```

All three functions are defined in `main.py`. None of them make LLM calls.
They run synchronously before the task loop is triggered.

---

## Function 1: `_extract_decision(text: str) -> dict`

**Location:** `main.py`, called from `presence_loop()` on every LLM response.

**Job:** Find and parse the JSON decision block in the raw LLM output string.
Returns a populated dict on success, empty dict `{}` on total failure.

The LLM is instructed to end every response with a fenced JSON block:

```
```json
{
    "action": "blender",
    "description": "...",
    "params": {},
    ...
}
```
```

But the model does not always comply perfectly. `_extract_decision` tries three
strategies in order, stopping at the first one that succeeds.

### Strategy 1 — fenced ` ```json ``` ` block (primary path)

```python
fence_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
if fence_match:
    result = json.loads(fence_match.group(1))
    if "action" in result:
        _ensure_decision_defaults(result)
        return result
```

Looks for the explicit ` ```json ... ``` ` wrapper the prompt asks for.
Requires the parsed dict to contain an `"action"` key — without it the block
is treated as non-decision JSON (e.g. an example in a code explanation) and
the search continues.

### Strategy 2 — last `{ ... }` object in the response (fallback)

```python
brace_matches = list(re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}", text, re.DOTALL))
for match in reversed(brace_matches):
    result = json.loads(match.group(0))
    if "action" in result:
        _ensure_decision_defaults(result)
        return result
```

If the fenced block is absent or malformed, scan the whole response for anything
that looks like a JSON object (up to one level of nesting). Iterates in **reverse**
order — the decision block should be at the end of the response, so the last
valid match is the most likely candidate. Again requires `"action"` to be present.

### Strategy 3 — legacy `DECISION:` text block (backwards compatibility)

```python
if "DECISION:" in text:
    decision_text = text.split("DECISION:")[-1].strip()
    result = {}
    for line in decision_text.splitlines():
        if line.lower().startswith("action:"):
            result["action"] = line.split(":", 1)[1].strip().lower()
        elif line.lower().startswith("description:"):
            result["description"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("for_james:"):
            result["for_james"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("emotion:"):
            result["emotion"] = line.split(":", 1)[1].strip().lower()
        elif line.lower().startswith("certainty:"):
            result["certainty"] = line.split(":", 1)[1].strip().lower()
        elif line.lower().startswith("params:"):
            # parses key=value pairs from a comma-separated string
            ...
```

An older prompt format that predates the JSON block instruction. The LLM would
emit a plain-text `DECISION:` section with `key: value` lines. This strategy
is kept for backwards compatibility. It also logs a warning so the caller knows
the prompt format is out of date.

### Total failure

If all three strategies fail, the function logs a warning and returns `{}`.
The presence loop treats an empty decision as `action = "none"` — Hayeong spoke
but no tool was called.

---

## Function 2: `_ensure_decision_defaults(d: dict)`

**Location:** `main.py`, called at the end of every successful parse path in
`_extract_decision`.

**Job:** Fill in any field the LLM omitted with a safe default value, so the
rest of the system never needs to handle `KeyError` or `None`.

```python
def _ensure_decision_defaults(d: dict):
    d.setdefault("action",           "none")
    d.setdefault("description",      "")
    d.setdefault("params",           {})
    d.setdefault("certainty",        "high")
    d.setdefault("expected_outcome", "")
    d.setdefault("for_james",        "")
    d.setdefault("emotion",          "calm")
    if not isinstance(d["params"], dict):
        d["params"] = {}

    _rescue_file_path(d)
```

The `params` type check is deliberate: if the LLM emitted `"params": null` or
`"params": "none"`, the dict replaces it with `{}` rather than letting a
non-dict propagate to a tool call.

After filling defaults, it immediately calls `_rescue_file_path`.

---

## Function 3: `_rescue_file_path(d: dict)`

**Location:** `main.py`, called from `_ensure_decision_defaults`.

**Job:** If the LLM put a file path in the human-readable `description` field
instead of in `params`, move it to the correct params key before dispatch.

This exists because file paths are **precise data** — if they sit in the
`description` string they can be truncated, rephrased, or lost. Moving them
into `params` makes them a first-class argument to the tool.

```python
def _rescue_file_path(d: dict):
    desc   = d.get("description", "")
    params = d.get("params", {})

    # Skip if params already has a file key — nothing to rescue
    if any(k in params for k in ("handoff_path", "path", "file_path", "filename")):
        return

    # Look for a filename-like pattern in the description
    match = re.search(r'[\w\-/\\]+\.(?:md|py|json|txt|bat|yaml|yml|sh|js)', desc)
    if not match:
        return

    filename = match.group(0)
    action   = d.get("action", "")

    # Route to the correct param key based on which tool was called
    if action == "handoff_reader":
        params["handoff_path"] = filename
    elif action in ("file_manager", "script"):
        params["path"] = filename
    else:
        params["file_path"] = filename

    d["params"] = params
```

**Key decisions:**
- The check for existing file keys prevents double-rescue and avoids clobbering
  a correctly supplied path.
- The regex matches common project file extensions: `.md .py .json .txt .bat
  .yaml .yml .sh .js`
- The routing logic mirrors the tool registry's param conventions:
  - `handoff_reader` expects `handoff_path`
  - `file_manager` and `script` expect `path`
  - Everything else gets `file_path`

---

## What it protects against

| LLM failure mode | Which function catches it |
|---|---|
| No fenced block, raw JSON at end of prose | `_extract_decision` Strategy 2 |
| Very old prompt format (`DECISION:` text) | `_extract_decision` Strategy 3 |
| Missing `action` field in JSON | `_ensure_decision_defaults` |
| `"params": null` or `"params": "none"` | `_ensure_decision_defaults` |
| File path in description instead of params | `_rescue_file_path` |
| Completely unparseable output | `_extract_decision` returns `{}`, action defaults to `"none"` |

---

## What it does NOT handle

- **Hallucinated tool names** — if the LLM writes `"action": "web"` instead of
  `"action": "web_search"`, the task loop will receive an unknown tool name and
  return `[ERROR] Unknown task type: web`. The presence loop sees this on the next
  cycle and can retry. The rescue system does not attempt to fuzzy-match tool names.
- **Semantically wrong actions** — if the LLM picks the right tool but wrong params,
  the rescue system does not detect this. That is the domain of the self-check tool
  (`Toolbox/self_check/`) which runs after the tool returns.
- **Nested JSON** — Strategy 2's regex handles one level of nesting. Deeply nested
  objects in the decision block may fail to parse. In practice the decision schema
  is shallow enough that this has not been an issue.

---

## Full code (verbatim from `main.py`)

```python
# ── Decision Extractor ───────────────────────────────────────────────
def _extract_decision(text: str) -> dict:
    """
    Extract the JSON decision block from the presence LLM response.
    Looks for a ```json ... ``` block first, then falls back to finding
    a raw { ... } object containing an "action" key.
    Returns empty dict if nothing valid is found.
    """
    import re

    # ── Strategy 1: fenced ```json block ─────────────────────────────
    fence_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            result = json.loads(fence_match.group(1))
            if "action" in result:
                _ensure_decision_defaults(result)
                return result
        except json.JSONDecodeError:
            pass

    # ── Strategy 2: last { ... } block in the response ───────────────
    brace_matches = list(re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}", text, re.DOTALL))
    for match in reversed(brace_matches):
        try:
            result = json.loads(match.group(0))
            if "action" in result:
                _ensure_decision_defaults(result)
                return result
        except json.JSONDecodeError:
            continue

    # ── Strategy 3: legacy DECISION: text block (backwards compat) ───
    if "DECISION:" in text:
        print("[presence] Warning: LLM used legacy DECISION text format — update prompt.")
        decision_text = text.split("DECISION:")[-1].strip()
        result = {}
        for line in decision_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.lower().startswith("action:"):
                result["action"] = line.split(":", 1)[1].strip().lower()
            elif line.lower().startswith("description:"):
                result["description"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("for_james:"):
                result["for_james"] = line.split(":", 1)[1].strip()
            elif line.lower().startswith("emotion:"):
                result["emotion"] = line.split(":", 1)[1].strip().lower()
            elif line.lower().startswith("certainty:"):
                result["certainty"] = line.split(":", 1)[1].strip().lower()
            elif line.lower().startswith("params:"):
                params_text = line.split(":", 1)[1].strip()
                params = {}
                if params_text.lower() not in ("none", ""):
                    for part in params_text.split(","):
                        part = part.strip()
                        if "=" in part:
                            k, v = part.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if v.lower() == "true":
                                v = True
                            elif v.lower() == "false":
                                v = False
                            else:
                                try:
                                    v = int(v)
                                except ValueError:
                                    pass
                            params[k] = v
                result["params"] = params
        if "action" in result:
            _ensure_decision_defaults(result)
            return result

    print("[presence] Warning: no decision block found in LLM response.")
    return {}


def _ensure_decision_defaults(d: dict):
    """Fill in any missing fields with safe defaults. Mutates in place."""
    d.setdefault("action",           "none")
    d.setdefault("description",      "")
    d.setdefault("params",           {})
    d.setdefault("certainty",        "high")
    d.setdefault("expected_outcome", "")
    d.setdefault("for_james",        "")
    d.setdefault("emotion",          "calm")
    if not isinstance(d["params"], dict):
        d["params"] = {}

    # Move file paths from description into params so they cannot be truncated.
    _rescue_file_path(d)


def _rescue_file_path(d: dict):
    """
    If a file path or filename appears in the description but not in params,
    move it into params so it cannot be truncated.
    File paths are precise data — they belong in params, not description prose.
    """
    desc   = d.get("description", "")
    params = d.get("params", {})

    # Already has explicit file params — nothing to rescue
    if any(k in params for k in ("handoff_path", "path", "file_path", "filename")):
        print(f"[rescue] params already has file key — skipping")
        return

    # Look for anything that looks like a filename (.md, .py, .json, .txt, .bat, etc.)
    match = re.search(r'[\w\-/\\]+\.(?:md|py|json|txt|bat|yaml|yml|sh|js)', desc)
    if not match:
        print(f"[rescue] no filename found in: {desc[:80]}")
        return

    filename = match.group(0)
    action   = d.get("action", "")
    print(f"[rescue] rescued '{filename}' from description into params")

    if action == "handoff_reader":
        params["handoff_path"] = filename
    elif action in ("file_manager", "script"):
        params["path"] = filename
    else:
        params["file_path"] = filename

    d["params"] = params
```

---

## Known limitations / potential improvement areas

1. **Strategy 2 regex depth** — `\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}` handles one
   level of nesting. If the LLM embeds a nested object (e.g. `"params": {"schema": {"col": "type"}}`),
   Strategy 2 will fail and the system falls back to Strategy 3 or returns `{}`.
   Strategy 1 (fenced block with `re.DOTALL`) does not have this limitation.

2. **`_rescue_file_path` fires on every parse** — even when the action is `"none"`
   and no file is relevant. The early-return guard (`if any(k in params ...)`) keeps
   this cheap, but it also prints a debug line (`[rescue] no filename found`) on
   every `"none"` decision, which creates noise in the console log.

3. **File path regex is extension-whitelist only** — paths without a recognised
   extension (e.g. a path to a directory, or a file named `Makefile`) will not be
   rescued. This is intentional conservatism but can miss edge cases.

4. **Strategy 3 params parser is line-oriented** — it only handles a single
   `params:` line in the legacy format. Multi-line params in the legacy format
   would be silently truncated.
