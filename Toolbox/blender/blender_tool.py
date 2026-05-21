"""
toolbox/blender/blender_tool.py

Hayeong's Blender control layer.
Receives a task description and params from the task loop.
Writes a Blender Python script to disk, runs Blender headless, captures output.

Called via registry:
    module:   toolbox.blender.blender_tool
    function: run

Params the reasoning LLM should provide:
    blender_script  (str) — full bpy Python script to execute
    output_filename (str) — desired output filename, e.g. "chair.glb"
    export_format   (str) — "glb", "blend", "stl", "fbx" — defaults to "glb"
    timeout         (int) — seconds before killing Blender, default 120

Returns:
    str   — success message with output file path
    raises RuntimeError / ValueError on failure (caught by _execute_tool)
"""

import subprocess
from datetime import datetime
from pathlib import Path

from brain.config import BLENDER_PATH, BLENDER_OUTPUT, BLENDER_SCRIPTS


def run(description: str, params: dict) -> str:
    """Entry point called by main.py task loop via registry."""
    try:
        return _run_pipeline(description, params)
    except Exception as e:
        return f"[ERROR] blender_tool: {e}"


def _run_pipeline(description: str, params: dict) -> str:
    # ── 1. Validate Blender path ──────────────────────────────────────
    blender_exe = Path(BLENDER_PATH)
    if not blender_exe.exists():
        raise FileNotFoundError(
            f"Blender not found at {BLENDER_PATH}. "
            "Update BLENDER_PATH in brain/config.py."
        )

    # ── 2. Extract params ─────────────────────────────────────────────
    blender_script  = params.get("blender_script", "")
    output_filename = params.get("output_filename", "output.glb")
    export_format   = params.get("export_format", "glb").lower()
    timeout         = int(params.get("timeout", 120))

    if not blender_script:
        raise ValueError(
            "No blender_script provided in task_params. "
            "The reasoning LLM must provide a bpy Python script string."
        )

    # ── 3. Ensure output directories exist ────────────────────────────
    output_dir  = Path(BLENDER_OUTPUT)
    scripts_dir = Path(BLENDER_SCRIPTS)
    output_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)

    # ── 4. Build output path ──────────────────────────────────────────
    safe_name = Path(output_filename).name or \
        f"blender_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{export_format}"
    output_path = output_dir / safe_name

    # ── 5. Inject export call into the script ─────────────────────────
    full_script = blender_script.strip() + "\n\n" + _build_export_snippet(str(output_path), export_format)

    # ── 6. Write script to disk ───────────────────────────────────────
    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_path = scripts_dir / f"gen_{timestamp}.py"
    script_path.write_text(full_script, encoding="utf-8")

    # ── 7. Run Blender headless ───────────────────────────────────────
    try:
        proc = subprocess.run(
            [str(blender_exe), "--background", "--python", str(script_path)],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(output_dir),
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Blender timed out after {timeout}s. Try a simpler scene or increase timeout.")
    except FileNotFoundError:
        raise RuntimeError(f"Could not launch Blender at {blender_exe}. Check BLENDER_PATH in brain/config.py.")

    # ── 8. Write log ──────────────────────────────────────────────────
    blender_log = (proc.stdout or "") + (proc.stderr or "")
    log_path    = scripts_dir / f"gen_{timestamp}.log"
    log_path.write_text(blender_log, encoding="utf-8")

    # ── 9. Check output ───────────────────────────────────────────────
    if output_path.exists():
        size = output_path.stat().st_size
        return f"[SUCCESS] Blender generation complete. Output: {output_path} ({size} bytes). Log: {log_path}"

    error_tail = blender_log[-800:] if len(blender_log) > 800 else blender_log
    raise RuntimeError(
        f"Blender ran but produced no output at {output_path}. "
        f"Return code: {proc.returncode}. Log tail:\n{error_tail}"
    )


def _build_export_snippet(output_path: str, export_format: str) -> str:
    path_str = output_path.replace("\\", "/")

    snippets = {
        "glb": f"""import bpy\nbpy.ops.export_scene.gltf(filepath=r"{path_str}", export_format='GLB', use_selection=False)\nprint("HAYEONG_EXPORT_OK: {path_str}")""",
        "blend": f"""import bpy\nbpy.ops.wm.save_as_mainfile(filepath=r"{path_str}")\nprint("HAYEONG_EXPORT_OK: {path_str}")""",
        "stl": f"""import bpy\nbpy.ops.export_mesh.stl(filepath=r"{path_str}")\nprint("HAYEONG_EXPORT_OK: {path_str}")""",
        "fbx": f"""import bpy\nbpy.ops.export_scene.fbx(filepath=r"{path_str}")\nprint("HAYEONG_EXPORT_OK: {path_str}")""",
    }
    return snippets.get(export_format, snippets["glb"])
