# Handoff 02 — Post-Generation Vision Eval
**Scope:** Modify `capabilities/image_gen_cap.py` only
**Who does this:** Claude Code (modifies an existing capability script)
**Main.py touched:** No
**comfyui_tool.py touched:** No
**capability_registry.json touched:** No

---

## What This Does

After ComfyUI finishes generating an image, Hayeong automatically passes the output
to the vision bridge (`look_at_image`) using llava:13b, gets a description of what
was actually produced, and includes that in her response to James.

This closes the awareness gap: right now she reports a file path. After this change
she reports what she sees — composition, subject, colors, style quality — so James
doesn't have to open the file to know if it's worth keeping.

This is a vision layer addition to the control layer script. Main.py is untouched.
The three-layer design is preserved: brain decided to generate, control executed it,
vision now observes the result and feeds it back to brain for the response.

---

## Architecture

```
Brain layer: decides action = image_gen
Control layer (image_gen_cap.py): calls comfyui_tool → gets output path
Vision layer (vision_bridge.look_at_image): analyzes the output file
Brain layer: responds to James with what was generated AND what it looks like
```

The vision context is injected into the capability result string, which main.py
already passes back to the brain as context before generating the response.

---

## Change: `capabilities/image_gen_cap.py`

### Current behavior (approximate)
```python
def run(description, params):
    result = comfyui_tool.run(description, params)
    return result  # returns path + prompt + workflow info
```

### New behavior

Add a vision eval step after successful generation. The key is:
1. Only attempt vision eval if the result contains a valid file path (generation succeeded)
2. Use `look_at_image` from the existing `VisionBridge` — don't reinvent it
3. If vision fails for any reason, return the original result unchanged — never break generation
4. Append the vision description to the result string so brain gets it as context

```python
"""
capabilities/image_gen_cap.py

Handles image_gen action. Calls comfyui_tool to generate, then optionally
runs vision analysis on the output so Hayeong can describe what was produced.
"""

import importlib
import sys
from pathlib import Path

# ── resolve project root ──────────────────────────────────────────────────────
_CAP_DIR   = Path(__file__).parent
_ROOT      = _CAP_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── imports ───────────────────────────────────────────────────────────────────
from Toolbox.comfyui import comfyui_tool


def run(description: str, params: dict, context: dict = None) -> str:
    """
    Entry point called by main.py capability loader.

    params expected:
        prompt      (str, required) — image description
        workflow    (str, optional) — defaults to txt2img_default
        negative    (str, optional)
        width       (int, optional)
        height      (int, optional)
        steps       (int, optional)
        cfg         (float, optional)
        seed        (int, optional)
    """
    # ── 1. Generate ───────────────────────────────────────────────────────────
    result = comfyui_tool.run(description, params)

    # ── 2. Vision eval — only if generation succeeded ─────────────────────────
    # comfyui_tool returns a path on success; "error", "not running", "timed out"
    # on failure. Parse the output path from the result string.
    output_path = _extract_output_path(result)

    if output_path:
        vision_context = _evaluate_image(output_path)
        if vision_context:
            result = result + "\n\n" + vision_context

    return result


def _extract_output_path(result: str) -> str | None:
    """
    Pull the output file path out of comfyui_tool's result string.
    Result format: "Image generated: C:/path/to/file.png\nPrompt: ..."
    Returns the path string if it exists and the file is on disk, else None.
    """
    try:
        for line in result.splitlines():
            if line.startswith("Image generated:"):
                candidate = line.replace("Image generated:", "").strip()
                if Path(candidate).exists():
                    return candidate
    except Exception:
        pass
    return None


def _evaluate_image(image_path: str) -> str | None:
    """
    Run vision analysis on the generated image.
    Returns a formatted context string, or None if vision is unavailable.
    Never raises — vision is optional, generation is not.
    """
    try:
        from Toolbox.vision_tools.vision_bridge import VisionBridge
        vision = VisionBridge()

        question = (
            "Describe this generated image in detail. Cover: "
            "what is depicted, the main subject, colors, art style, "
            "composition quality, any issues like distorted anatomy or "
            "artifacts, and an overall quality assessment. Be specific."
        )

        description = vision.look_at_image(image_path, question)

        # look_at_image returns a formatted context block — extract just the text
        # so brain gets clean vision output without the [VISION — IMAGE] wrapper
        # (the wrapper is designed for system prompt injection, not cap results)
        return f"[Vision eval of output]\n{description}"

    except Exception as e:
        # Vision unavailable — generation result still returned cleanly
        return f"[Vision eval unavailable: {e}]"
```

---

## Import Path Notes

Check the actual import path for `comfyui_tool` and `VisionBridge` in the existing
`image_gen_cap.py` before writing — the paths above match the directory structure
seen in the project (`Toolbox/comfyui/comfyui_tool.py` and
`Toolbox/vision_tools/vision_bridge.py`) but confirm they match what the current
`image_gen_cap.py` already uses for its comfyui import.

If `image_gen_cap.py` currently uses a different import pattern (e.g. relative imports,
or a capability loader abstraction), match that pattern — don't change the import style.

---

## What Changes for James

**Before:** "Image generated: Logs/outputs/comfyui/hayeong_20260525_143022.png"

**After:**
```
Image generated: Logs/outputs/comfyui/hayeong_20260525_143022.png
Prompt: misty forest at dawn with golden light
Workflow: txt2img_default | Steps: 20 | CFG: 7.0 | Seed: 4821

[Vision eval of output]
[VISION — IMAGE (Logs/outputs/comfyui/hayeong_20260525_143022.png) via llava:13b]
The image depicts a softly lit forest scene at early morning. Tall pine trees with
detailed bark texture fade into a golden-tinted mist in the background. The lighting
is warm and directional, suggesting sunrise from the right. Composition is centered
with good depth. No visible anatomy issues. Overall quality is high — sharp foreground
detail with pleasant atmospheric depth. Minor note: the mist blending at the tree bases
could be smoother.

You have analyzed the image above. Respond naturally about what you see.
```

Hayeong sees this full block and responds naturally — "The forest came out well, the
mist effect worked. Want me to try a version with more golden light in the foreground?"

---

## Failure Modes — All Safe

| Situation | Behavior |
|---|---|
| Vision models not loaded | `[Vision eval unavailable: ...]` appended, generation result still returned |
| llava:13b not installed | Same — unavailable message, no crash |
| File path parse fails | Vision step skipped entirely, generation result unchanged |
| ComfyUI generation failed | `_extract_output_path` returns None, vision step never runs |

---

## Verification

1. Ask Hayeong to generate an image
2. Confirm response includes both the file path AND a description of the image content
3. Ask Hayeong to generate when ComfyUI is NOT running — confirm she still responds
   cleanly with the "not running" message and no vision error leaks through
