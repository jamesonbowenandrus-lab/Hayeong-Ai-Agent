# capabilities/blender_gen_cap.py
# Blender Python generation capability.
#
# Handles: blender_gen action from context_router
# Generates a Blender Python script via LLM, executes it headless,
# and confirms the output file to James.
#
# Path to Blender is stored in hayeong_config.py — update that file,
# not this one, when Blender is installed or the version changes.
#
# Script path injection:
#   Generated scripts use OUTPUT_PATH_PLACEHOLDER and PREVIEW_PATH_PLACEHOLDER
#   as literal strings. This capability replaces them with real paths before
#   passing the script to Blender. No env vars needed.
#
# Error handling:
#   If Blender exits non-zero, stderr and stdout are captured and injected
#   into the AI prompt so Hayeong can read the error and diagnose it.
#   Common first-run errors and their fixes are documented in the prompt.

import os
import re
import subprocess
import tempfile
import datetime
import requests
from pathlib import Path
from capability_loader import result

ACTIONS = ["blender_gen"]

OLLAMA_URL  = "http://localhost:11434/api/chat"
GEN_MODELS  = ["deepseek-coder-v2:16b", "deepseek-coder:33b", "deepseek-r1:latest"]
GEN_TIMEOUT = 120
BLENDER_TIMEOUT = 120

BASE_DIR     = Path(__file__).parent.parent
OUTPUT_DIR   = BASE_DIR / "hayeong_outputs" / "3d_models"
PREVIEW_DIR  = BASE_DIR / "hayeong_outputs" / "3d_previews"
SCRIPTS_DIR  = BASE_DIR / "hayeong_outputs" / "3d_scripts"


# ─────────────────────────────────────────────
# CONFIG — Blender path
# ─────────────────────────────────────────────

def _get_blender_path() -> str:
    try:
        from hayeong_config import BLENDER_PATH
        return BLENDER_PATH
    except ImportError:
        return r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"


# ─────────────────────────────────────────────
# SCRIPT GENERATION PROMPT
# ─────────────────────────────────────────────

SCRIPT_SYSTEM = """\
You are a Blender Python script generator for 3D furniture and kitchen objects.
Generate a complete, self-contained Blender Python script.
The script runs in Blender headless mode (--background) with no UI.
Output ONLY the Python script — no markdown fences, no explanation, no comments about what you're doing.

REQUIRED STRUCTURE — follow exactly:
  1. import bpy
  2. Clear the default scene
  3. Define dimensions as variables (ALL IN METERS — see conversion below)
  4. Build geometry
  5. Apply materials
  6. Export using OUTPUT_PATH_PLACEHOLDER as a literal string (do not replace it)
  7. Print HAYEONG_SUCCESS: <message> on completion

INCH TO METER CONVERSION (use in your variable definitions):
  1 inch = 0.0254 meters
  Example: width_m = 36 * 0.0254  # 36 inches = 0.9144 meters

UNITS NOTE — CRITICAL:
  Live Home 3D reads OBJ units as meters. Generate all coordinates in METERS.
  A cabinet at 34.5 meters tall is a skyscraper. At 0.8763 meters it is correct.

CLEAR SCENE BOILERPLATE (required at top):
  bpy.ops.object.select_all(action='SELECT')
  bpy.ops.object.delete()
  for block in list(bpy.data.meshes): bpy.data.meshes.remove(block)

EXPORT (use exact placeholder string — it gets replaced before execution):
  bpy.ops.wm.obj_export(
      filepath="OUTPUT_PATH_PLACEHOLDER",
      export_selected_objects=False
  )

MATERIALS — Principled BSDF only:
  mat = bpy.data.materials.new(name="CabinetMat")
  mat.use_nodes = True
  bsdf = mat.node_tree.nodes["Principled BSDF"]
  bsdf.inputs["Base Color"].default_value = (0.94, 0.94, 0.93, 1.0)
  bsdf.inputs["Roughness"].default_value = 0.6
  obj.data.materials.append(mat)

KITCHEN STANDARDS (convert all to meters in code):
  Base Cabinet     : H 34.5in (0.876m), D 24in (0.610m)
  Wall Cabinet     : H 30-42in, D 12in (0.305m)
  Sink Base        : H 34.5in, D 24in, NO interior shelf
  Toe kick         : H 3.5in (0.089m), setback 3.25in from front
  Panel thickness  : 0.75in (0.019m)

END WITH:
  print("HAYEONG_SUCCESS: <object_name> exported.")
"""


# ─────────────────────────────────────────────
# LLM CALL — SCRIPT GENERATION
# ─────────────────────────────────────────────

def _generate_script(object_type: str, description: str, dimensions: dict) -> str | None:
    dim_note = ""
    if dimensions:
        parts = [f"{k}={v} inches (= {float(v)*0.0254:.4f}m)" for k, v in dimensions.items()]
        dim_note = f"\nRequired dimensions: {', '.join(parts)}."

    user_msg = (
        f"Generate a Blender Python script for: {object_type.replace('_', ' ')}\n"
        f"Description: {description}{dim_note}\n"
        f"Export as OBJ. Use OUTPUT_PATH_PLACEHOLDER as the filepath string.\n"
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

    return None


def _clean_script(raw: str) -> str:
    raw = re.sub(r"^```(?:python)?\s*", "", raw.strip(), flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw.strip(), flags=re.MULTILINE)
    return raw.strip()


# ─────────────────────────────────────────────
# BLENDER EXECUTION
# ─────────────────────────────────────────────

def _run_blender(script: str, output_path: Path, preview_path: Path | None) -> dict:
    blender_path = _get_blender_path()

    # Inject real paths into script
    script = script.replace("OUTPUT_PATH_PLACEHOLDER", str(output_path).replace("\\", "/"))
    if preview_path:
        script = script.replace("PREVIEW_PATH_PLACEHOLDER", str(preview_path).replace("\\", "/"))

    # Save script to 3d_scripts/ for debugging
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    script_save_path = SCRIPTS_DIR / f"{output_path.stem}.py"
    script_save_path.write_text(script, encoding="utf-8")

    # Also write to temp file for execution
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(script)
        temp_script = f.name

    try:
        proc = subprocess.run(
            [blender_path, "--background", "--python", temp_script],
            capture_output=True, text=True, timeout=BLENDER_TIMEOUT,
        )
        success = proc.returncode == 0 and output_path.exists()
        return {
            "success":      success,
            "returncode":   proc.returncode,
            "file_exists":  output_path.exists(),
            "blender_log":  proc.stdout,
            "stderr":       proc.stderr,
            "script_path":  str(script_save_path),
        }
    except subprocess.TimeoutExpired:
        return {
            "success":    False,
            "error":      "Blender timed out after 120 seconds.",
            "blender_log": "",
            "stderr":     "",
        }
    except FileNotFoundError:
        return {
            "success":    False,
            "error":      f"Blender not found at: {blender_path}\nUpdate BLENDER_PATH in hayeong_config.py.",
            "blender_log": "",
            "stderr":     "",
        }
    except Exception as e:
        return {
            "success":    False,
            "error":      str(e),
            "blender_log": "",
            "stderr":     "",
        }
    finally:
        try:
            os.unlink(temp_script)
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
    render_preview = bool(decision.get("render_preview", False))

    label = object_type.replace("_", " ")

    if speak_fn:
        speak_fn(f"Generating the {label} in Blender.", emotion="focused")

    # Step 1 — generate script
    script = _generate_script(object_type, description, dimensions)
    if not script:
        return result(
            success=False,
            speak="I couldn't generate the Blender script — Ollama may not be running.",
            data={"error": "script_generation_failed"},
        )

    # Step 2 — prepare output paths
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    timestamp    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe         = object_type.replace(" ", "_").lower()
    out_path     = OUTPUT_DIR  / f"{safe}_{timestamp}.obj"
    prev_path    = PREVIEW_DIR / f"{safe}_{timestamp}.png" if render_preview else None

    # Step 3 — run Blender
    run = _run_blender(script, out_path, prev_path)

    # Log
    if logger:
        try:
            logger.log_capability_used(
                "blender_gen", action="generate",
                outcome="success" if run["success"] else "failure",
                details={"object_type": object_type, "file": str(out_path)},
            )
        except Exception:
            pass

    if not run.get("success"):
        error_msg = run.get("error") or run.get("stderr", "")
        stderr    = run.get("stderr", "")
        log_snip  = (run.get("blender_log") or "")[-1000:]

        # Diagnostic hint
        hint = ""
        if "not found" in error_msg.lower() or "FileNotFoundError" in error_msg:
            hint = "BLENDER_PATH in hayeong_config.py points to the wrong location. Update it to the correct blender.exe path."
        elif "obj_export" in stderr.lower():
            hint = "bpy.ops.wm.obj_export may not exist on this Blender version. Try bpy.ops.export_scene.obj instead (legacy exporter)."
        elif not run.get("file_exists", True):
            hint = "Blender exited cleanly but the output file wasn't created. Check the filepath in the script uses forward slashes."

        response_ctx = (
            f"[BLENDER FAILED]\n"
            f"Object: {object_type}\n"
            f"Error: {error_msg[:600]}\n"
            f"{f'Hint: {hint}' if hint else ''}\n"
            f"Blender log (last 1000 chars):\n{log_snip}\n\n"
            f"Read the error carefully and tell James what went wrong. "
            f"If the hint above applies, mention it specifically. "
            f"Ask James if he wants you to try fixing the script and retrying."
        )
        return result(
            success=False,
            response=response_ctx,
            speak=f"Blender hit an error on the {label}.",
            data={"error": error_msg, "stderr": stderr, "log": log_snip},
        )

    # Success
    log_snip     = (run.get("blender_log") or "")[-500:]
    preview_note = f"\nPreview: {prev_path}" if (prev_path and prev_path.exists()) else ""
    script_note  = f"\nScript saved: {run.get('script_path', '')}"

    response_ctx = (
        f"[BLENDER SUCCESS]\n"
        f"Object: {object_type}\n"
        f"File: {out_path}{preview_note}{script_note}\n"
        f"Blender log:\n{log_snip}\n\n"
        f"Tell James the file is ready and give him the filename. "
        f"How to import: Live Home 3D → File → Import → {out_path.name}\n"
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
            "script_path": run.get("script_path"),
            "object_type": object_type,
            "blender_log": run.get("blender_log", ""),
        },
    )


# ─────────────────────────────────────────────
# LIFECYCLE
# ─────────────────────────────────────────────

def on_load():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    blender_path = _get_blender_path()
    if os.path.exists(blender_path):
        print(f"[BlenderGen] ✅ Blender found: {blender_path}")
    else:
        print(f"[BlenderGen] ⚠️  Blender NOT found at: {blender_path}")
        print(f"[BlenderGen]    Download Blender at blender.org, then update BLENDER_PATH in hayeong_config.py")


def on_unload():
    pass
