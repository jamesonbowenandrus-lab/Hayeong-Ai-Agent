# Handoff 03 — Image Session Context
**Scope:** New file `Memory/image_session.json` + small additions to `capabilities/image_gen_cap.py`
**Who does this:** Hayeong (she can write this herself — it's a new standalone script addition)
**Main.py touched:** No
**comfyui_tool.py touched:** No
**capability_registry.json touched:** No (optional addition at end)

**Dependency:** Complete Handoff 02 first — this builds on the updated `image_gen_cap.py`

---

## What This Does

Creates a lightweight persistent JSON file that tracks the last generated image.
When James says "tweak it", "change the background", "try a darker version" — Hayeong
knows exactly which image he's referring to and what parameters produced it, without
James having to re-describe anything.

This is the memory layer for the image generation loop.

---

## Design

```
image_session.json — written after every successful generation
    last_output_path    absolute path to the last generated image
    last_prompt         prompt that produced it
    last_workflow       workflow used
    last_seed           seed used (for near-identical reruns)
    last_cfg            CFG value used
    last_steps          steps used
    generated_at        timestamp
    comfyui_input_copy  path where the image was copied for img2img use
```

The session file is read by `image_gen_cap.py` when an `img2img` action is requested,
so it can automatically populate the `LoadImage` node with the correct source image.

---

## File 1: `Memory/image_session.json`

Create this file as an empty template. It will be overwritten on first successful generation.

```json
{
  "last_output_path": null,
  "last_prompt": null,
  "last_workflow": null,
  "last_seed": null,
  "last_cfg": null,
  "last_steps": null,
  "generated_at": null,
  "comfyui_input_copy": null
}
```

---

## File 2: Add session management to `capabilities/image_gen_cap.py`

Add these two functions to `image_gen_cap.py` (the file updated in Handoff 02).
Call `_save_session()` after a successful generation (before the vision eval).
Call `_load_session()` at the top of `run()` when the workflow is `txt2img_img2img`.

```python
import json
import shutil
from datetime import datetime
from pathlib import Path

# Path to session file — relative to project root
_SESSION_FILE = _ROOT / "Memory" / "image_session.json"

# Path to ComfyUI's input directory — update to match your ComfyUI install location
# ComfyUI reads LoadImage from: H:/ComfyUI/input/  (or wherever ComfyUI is installed)
_COMFYUI_INPUT_DIR = Path("H:/ComfyUI/input")


def _save_session(output_path: str, params: dict) -> None:
    """
    Write session data after a successful generation.
    Also copies the output to ComfyUI's input dir as hayeong_latest.png
    so the img2img workflow can reference it by stable name.
    """
    try:
        comfyui_copy = None

        if _COMFYUI_INPUT_DIR.exists():
            dest = _COMFYUI_INPUT_DIR / "hayeong_latest.png"
            shutil.copy2(output_path, dest)
            comfyui_copy = str(dest)

        session = {
            "last_output_path":   output_path,
            "last_prompt":        params.get("prompt"),
            "last_workflow":      params.get("workflow", "txt2img_default"),
            "last_seed":          params.get("seed"),
            "last_cfg":           params.get("cfg"),
            "last_steps":         params.get("steps"),
            "generated_at":       datetime.now().isoformat(),
            "comfyui_input_copy": comfyui_copy,
        }

        _SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SESSION_FILE.write_text(json.dumps(session, indent=2), encoding="utf-8")

    except Exception as e:
        # Session save is non-critical — log but never break generation
        print(f"[image_gen_cap] session save failed: {e}")


def _load_session() -> dict | None:
    """
    Load the last image session. Returns None if no session exists yet.
    Used by img2img flow to confirm a source image is available.
    """
    try:
        if not _SESSION_FILE.exists():
            return None
        return json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
```

### Updated `run()` function — integrate session

```python
def run(description: str, params: dict, context: dict = None) -> str:

    workflow = params.get("workflow", "txt2img_default")

    # ── img2img guard: confirm a source image exists ──────────────────────────
    if workflow == "txt2img_img2img":
        session = _load_session()
        if not session or not session.get("comfyui_input_copy"):
            return (
                "No previous image found to refine. "
                "Generate a new image first, then ask me to change or refine it."
            )
        # Inform brain what we're working from
        source_info = (
            f"[Refining previous image]\n"
            f"Source: {session['last_output_path']}\n"
            f"Original prompt: {session['last_prompt']}\n"
            f"Original seed: {session['last_seed']}"
        )
    else:
        source_info = None

    # ── Generate ──────────────────────────────────────────────────────────────
    result = comfyui_tool.run(description, params)

    # ── Save session on success ───────────────────────────────────────────────
    output_path = _extract_output_path(result)
    if output_path:
        _save_session(output_path, params)

    # ── Vision eval ───────────────────────────────────────────────────────────
    if output_path:
        vision_context = _evaluate_image(output_path)
        if vision_context:
            result = result + "\n\n" + vision_context

    # ── Prepend source context for img2img so brain knows what changed ────────
    if source_info and output_path:
        result = source_info + "\n\n" + result

    return result
```

---

## ComfyUI Input Directory

The `LoadImage` node in the img2img workflow (Handoff 01) reads from ComfyUI's own
`input/` folder. The path in `_COMFYUI_INPUT_DIR` must match your actual ComfyUI
install location.

Check where ComfyUI is installed and confirm the input folder path. Common locations:
- `H:/ComfyUI/input/`
- `C:/ComfyUI/input/`
- `D:/AI/ComfyUI/input/`

Update `_COMFYUI_INPUT_DIR` in `image_gen_cap.py` to match. If uncertain, check
`brain/config.py` — there may already be a `COMFYUI_URL` or path constant defined
there that implies the install location.

---

## Optional: `denoise` as a conversational parameter

Once this is all working, Hayeong can expose `denoise` as a natural language param.
The brain layer can learn to translate:

| James says | denoise value |
|---|---|
| "just slightly change the background" | 0.3 |
| "refine it" / "tweak it" | 0.55 (default) |
| "big changes but keep the composition" | 0.75 |
| "basically regenerate but keep the layout" | 0.85 |

This doesn't require any code change — just a note in the `capability_registry.json`
decision_hint for `image_gen` so the brain knows to include it in the action JSON:

```
"img2img also accepts denoise (float 0.0-1.0): 0.3=subtle, 0.55=moderate (default), 0.75=significant, 0.85=near-full regen"
```

---

## Full Flow After All Three Handoffs

```
James: "Generate a misty forest at dawn"
  → Brain: action=image_gen, workflow=txt2img_default, prompt=...
  → image_gen_cap.run() → comfyui_tool generates → saves session → vision eval
  → Hayeong: "Generated. I can see a softly lit forest with golden mist..."

James: "Nice, but change the background to a rainy city instead"
  → Brain: action=image_gen, workflow=txt2img_img2img, prompt=same character but rainy city background
  → image_gen_cap.run() → loads session → confirms hayeong_latest.png exists → comfyui_tool refines
  → saves new session → vision eval of refined result
  → Hayeong: "Refined from the previous image. Now showing the character in a rain-slicked city street..."

James: "Make it a bit darker"
  → Same flow — img2img from new hayeong_latest.png, lower denoise
```

---

## Verification

1. Generate a fresh image — confirm `Memory/image_session.json` is written with correct data
2. Confirm `H:/ComfyUI/input/hayeong_latest.png` (or your path) was copied there
3. Ask to "change the background" — confirm img2img flow runs without error
4. Delete `Memory/image_session.json` and ask to "tweak it" — confirm she responds
   with "no previous image found" rather than crashing
