# capabilities/blender_gen_cap.py
# Blender Python generation capability.
#
# Handles: blender_gen action from context_router
# Generates Blender Python scripts via LLM and executes them headless.
# Output: exported 3D files (.obj, .fbx, .gltf, .dae) + optional render preview.
#
# Why Blender for higher-quality output:
#   - Free, no license required
#   - Full modifier support: bevels, subdivision, boolean ops
#   - Headless execution: blender --background --python script.py
#   - Multi-format export and built-in renderer
#   - Path for Etsy/game art quality — not needed for basic kitchen objects
#
# Execution flow:
#   LLM generates Blender Python script
#   → script saved to temp file
#   → blender called as subprocess (--background --python)
#   → output file and optional render saved to hayeong_outputs/
#   → file path returned to James
#
# Script improvement loop:
#   If blender returns a non-zero exit code, stderr is captured and returned
#   as context so Hayeong can read the error, revise the script, and retry.
#   This is not automatic in v1 — James triggers a retry explicitly.

import os
import re
import subprocess
import tempfile
import datetime
import requests
from pathlib import Path
from capability_loader import result

ACTIONS = ["blender_gen"]

OLLAMA_URL   = "http://localhost:11434/api/chat"
GEN_MODELS   = ["deepseek-coder-v2:16b", "deepseek-coder:33b", "qwen2.5:14b"]
OUTPUT_DIR   = Path(__file__).parent.parent / "hayeong_outputs" / "3d_models"
PREVIEW_DIR  = Path(__file__).parent.parent / "hayeong_outputs" / "3d_previews"
GEN_TIMEOUT  = 120
BLENDER_TIMEOUT = 120

# Blender executable — try common Windows paths, fall back to PATH
BLENDER_CANDIDATES = [
    r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
    "blender",  # fallback: try PATH
]


# ─────────────────────────────────────────────
# BLENDER DETECTION
# ─────────────────────────────────────────────

def _find_blender() -> str | None:
    for candidate in BLENDER_CANDIDATES:
        try:
            r = subprocess.run(
                [candidate, "--version"],
                capture_output=True, timeout=10,
            )
            if r.returncode == 0:
                print(f"[BlenderGen] Found Blender at: {candidate}")
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    return None


_blender_path: str | None = None

def _get_blender() -> str | None:
    global _blender_path
    if _blender_path is None:
        _blender_path = _find_blender()
    return _blender_path


# ─────────────────────────────────────────────
# SCRIPT GENERATION PROMPT
# ─────────────────────────────────────────────

SCRIPT_SYSTEM = """\
You are a Blender Python script generator for 3D furniture and objects.
Generate a complete, self-contained Blender Python script.
The script runs in Blender headless mode (--background) — no UI, no popups.
Output ONLY the Python script — no markdown fences, no explanation.

REQUIRED STRUCTURE — follow this exactly:
  1. import bpy
  2. Clear default scene
  3. Set dimensions as variables (all in METERS — Live Home 3D reads OBJ as meters)
  4. Build geometry using bpy.ops or bmesh
  5. Apply materials
  6. Export to OUTPUT_FILE (the script receives this via an environment variable)
  7. Optionally render to PREVIEW_FILE if RENDER_PREVIEW env var is "1"

INCH TO METER CONVERSION:
  1 inch = 0.0254 meters
  Example: 34.5 inches = 34.5 * 0.0254 = 0.8763 meters

REQUIRED BOILERPLATE:
```python
import bpy, os

OUTPUT_FILE  = os.environ.get("HAYEONG_OUTPUT", "output.obj")
PREVIEW_FILE = os.environ.get("HAYEONG_PREVIEW", "")
DO_RENDER    = os.environ.get("RENDER_PREVIEW", "0") == "1"

# Clear default scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
for block in bpy.data.meshes:
    bpy.data.meshes.remove(block)
```

EXPORT — always use the new-style exporter (Blender 4.x):
```python
ext = os.path.splitext(OUTPUT_FILE)[1].lower()
if ext == ".obj":
    bpy.ops.wm.obj_export(filepath=OUTPUT_FILE, export_selected_objects=False)
elif ext == ".fbx":
    bpy.ops.export_scene.fbx(filepath=OUTPUT_FILE)
elif ext in (".gltf", ".glb"):
    bpy.ops.export_scene.gltf(filepath=OUTPUT_FILE)
```

RENDER (only if DO_RENDER):
```python
if DO_RENDER and PREVIEW_FILE:
    bpy.context.scene.render.filepath = PREVIEW_FILE
    bpy.context.scene.render.resolution_x = 800
    bpy.context.scene.render.resolution_y = 600
    bpy.ops.render.render(write_still=True)
```

MATERIALS — use simple diffuse colors (Principled BSDF):
```python
mat = bpy.data.materials.new(name="Cabinet_White")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.94, 0.94, 0.93, 1.0)
bsdf.inputs["Roughness"].default_value = 0.6
obj.data.materials.append(mat)
```

KITCHEN STANDARDS (inches → convert to meters in code):
  Base Cabinet     : H 34.5", D 24"
  Wall Cabinet     : H 30-42", D 12"
  Sink Base        : H 34.5", D 24", no interior shelf
  Tall Cabinet     : H 84-96", D 24"
  Toe kick         : H 3.5", setback 3.25" from front
  Panel thickness  : 0.75"
"""


# ─────────────────────────────────────────────
# LLM CALL — SCRIPT GENERATION
# ─────────────────────────────────────────────

def _generate_script(
    object_type: str,
    description: str,
    dimensions: dict,
    export_format: str,
) -> str | None:
    dim_note = ""
    if dimensions:
        parts = [f"{k}={v} inches" for k, v in dimensions.items()]
        dim_note = f"\nRequired dimensions: {', '.join(parts)}. Convert to meters in the script."

    user_msg = (
        f"Generate a Blender Python script for: {object_type.replace('_', ' ')}\n"
        f"Description: {description}{dim_note}\n"
        f"Export format: {export_format}\n"
        f"Output ONLY the Python script."
    )

    for model in GEN_MODELS:
        try:
            print(f"[BlenderGen] Generating script with {model}...")
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model":    model,
                    "messages": [
                        {"role": "system", "content": SCRIPT_SYSTEM},
                        {"role": "user",   "content": user_msg},
                    ],
                    "stream": False,
                },
                timeout=GEN_TIMEOUT,
            )
            if resp.status_code == 200:
                raw = resp.json()["message"]["content"].strip()
                script = _clean_script(raw)
                print(f"[BlenderGen] ✅ Script from {model} ({len(script)} chars)")
                return script
        except requests.exceptions.ConnectionError:
            print("[BlenderGen] Ollama not reachable.")
            return None
        except Exception as e:
            print(f"[BlenderGen] {model} failed: {e}")

    print("[BlenderGen] All models failed.")
    return None


def _clean_script(raw: str) -> str:
    """Strip markdown fences from LLM output."""
    raw = re.sub(r"^```(?:python)?\s*", "", raw.strip(), flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw.strip(), flags=re.MULTILINE)
    return raw.strip()


# ─────────────────────────────────────────────
# BLENDER EXECUTION
# ─────────────────────────────────────────────

def _run_blender(
    script: str,
    output_path: Path,
    preview_path: Path | None,
    render_preview: bool,
) -> dict:
    blender = _get_blender()
    if not blender:
        return {
            "success": False,
            "error":   "Blender not found. Install from blender.org and ensure it's on PATH.",
        }

    # Write script to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(script)
        script_path = f.name

    env = os.environ.copy()
    env["HAYEONG_OUTPUT"]  = str(output_path)
    env["HAYEONG_PREVIEW"] = str(preview_path) if preview_path else ""
    env["RENDER_PREVIEW"]  = "1" if render_preview else "0"

    try:
        proc = subprocess.run(
            [blender, "--background", "--python", script_path],
            capture_output=True, text=True,
            timeout=BLENDER_TIMEOUT, env=env,
        )
        return {
            "success":     proc.returncode == 0,
            "returncode":  proc.returncode,
            "stdout":      proc.stdout[-2000:] if proc.stdout else "",
            "stderr":      proc.stderr[-2000:] if proc.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Blender timed out after 120 seconds."}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


# ─────────────────────────────────────────────
# HANDLER
# ─────────────────────────────────────────────

def handle(action: str, user_input: str, context: dict) -> dict:
    decision       = context.get("decision", {})
    speak_fn       = context.get("speak_fn")
    logger         = context.get("logger")

    object_type    = decision.get("object_type") or "object"
    description    = decision.get("description") or user_input
    dimensions     = decision.get("dimensions") or {}
    export_format  = decision.get("export_format", "obj").lower()
    render_preview = bool(decision.get("render_preview", False))

    label = object_type.replace("_", " ")

    if speak_fn:
        speak_fn(f"Generating the {label} in Blender.", emotion="focused")

    # Step 1 — generate script
    script = _generate_script(object_type, description, dimensions, export_format)
    if not script:
        return result(
            success=False,
            speak="I couldn't generate the Blender script — Ollama may not be running.",
            data={"error": "script_generation_failed"},
        )

    # Step 2 — prepare output paths
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    timestamp   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe        = object_type.replace(" ", "_").lower()
    ext         = {"obj": "obj", "fbx": "fbx", "gltf": "gltf", "glb": "glb", "dae": "dae"}.get(export_format, "obj")
    out_path    = OUTPUT_DIR  / f"{safe}_{timestamp}.{ext}"
    prev_path   = PREVIEW_DIR / f"{safe}_{timestamp}.png" if render_preview else None

    # Step 3 — run Blender
    run_result = _run_blender(script, out_path, prev_path, render_preview)

    if not run_result.get("success"):
        error_detail = run_result.get("error") or run_result.get("stderr", "Unknown error")
        return result(
            success=False,
            speak=f"Blender ran into an error generating the {label}.",
            response=(
                f"[BLENDER ERROR]\n"
                f"Object: {object_type}\n"
                f"Error: {error_detail[:800]}\n\n"
                f"Tell James Blender returned an error and show him the first part of it. "
                f"Ask if he wants you to try to fix the script and retry."
            ),
            data={
                "error":  error_detail,
                "script": script[:500],
                "stderr": run_result.get("stderr", ""),
            },
        )

    # Log
    if logger:
        try:
            logger.log_capability_used(
                "blender_gen", action="generate", outcome="success",
                details={"object_type": object_type, "file": str(out_path)},
            )
        except Exception:
            pass

    # Build response context
    preview_note = ""
    if render_preview and prev_path and prev_path.exists():
        preview_note = f"\nPreview render: {prev_path}"

    response_ctx = (
        f"[BLENDER MODEL GENERATED]\n"
        f"Object: {object_type}\n"
        f"File: {out_path}{preview_note}\n\n"
        f"How James uses it:\n"
        f"  Option A — import directly: Live Home 3D → File → Import → {out_path.name}\n"
        f"  Option B — open in Blender for tweaking, then export\n\n"
        f"Tell James the file is ready. If there's a preview image, mention it. "
        f"Ask if the proportions look right or if he wants any changes."
    )

    return result(
        success=True,
        response=response_ctx,
        speak=f"Done — the {label} is ready.",
        emotion="pleased",
        data={
            "out_path":    str(out_path),
            "preview":     str(prev_path) if prev_path else None,
            "object_type": object_type,
        },
    )


# ─────────────────────────────────────────────
# LIFECYCLE
# ─────────────────────────────────────────────

def on_load():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    blender = _get_blender()
    if blender:
        print(f"[BlenderGen] ✅ Loaded — Blender at: {blender}")
    else:
        print("[BlenderGen] ⚠️  Loaded — Blender not found. Install from blender.org.")


def on_unload():
    pass
