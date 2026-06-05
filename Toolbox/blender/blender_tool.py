
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
    str   — [SUCCESS] message with output file path, or [ERROR] message on failure.
             Never raises. All errors are returned as strings.
"""

import subprocess
from datetime import datetime
from pathlib import Path

from brain.config import BLENDER_PATH, BLENDER_OUTPUT, BLENDER_SCRIPTS
from toolbox.blender.skill_checker import check_script


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
        return (
            f"[ERROR] blender_tool: Blender not found at {BLENDER_PATH}. "
            "Update BLENDER_PATH in brain/config.py."
        )

    # ── 2. Extract params ─────────────────────────────────────────────
    blender_script  = params.get("blender_script", "")
    output_filename = params.get("output_filename", "output.glb")
    export_format   = params.get("export_format", "glb").lower()
    timeout         = int(params.get("timeout", 120))
    asset_name      = params.get("asset_name", "").strip()
    asset_type      = params.get("asset_type", "").strip()
    story_context   = params.get("story_context", "").strip()

    if not blender_script:
        return (
            "[ERROR] blender_tool: No blender_script provided in params. "
            "Pass blender_script as a string containing a complete bpy Python script. "
            "The script must import bpy, clear the scene, build the geometry, "
            "and end with print(\"HAYEONG_OK: done\"). "
            "Do NOT include export calls — the pipeline adds them automatically."
        )

    # ── 2b. Pre-flight static validation ─────────────────────────────
    issues = check_script(blender_script)
    if issues:
        return f"[ERROR] blender_tool: script failed pre-flight check: {'; '.join(issues)}"

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

    # ── 6b. Save permanent script copy alongside output ───────────────
    base_name        = Path(safe_name).stem   # e.g. "red_cube" from "red_cube.glb"
    perm_script_path = output_dir / "scripts" / f"{base_name}_script.py"
    _write_permanent_script(blender_script, perm_script_path, safe_name)

    # ── 7. Run Blender headless ───────────────────────────────────────
    try:
        proc = subprocess.run(
            [str(blender_exe), "--background", "--python", str(script_path)],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(output_dir),
        )
    except subprocess.TimeoutExpired:
        _update_script_status(perm_script_path, "failed (timeout)")
        return f"[ERROR] blender_tool: Blender timed out after {timeout}s. Try a simpler scene or increase timeout param."
    except FileNotFoundError:
        _update_script_status(perm_script_path, "failed (blender not found)")
        return f"[ERROR] blender_tool: Could not launch Blender at {blender_exe}. Check BLENDER_PATH in brain/config.py."

    # ── 8. Write log ──────────────────────────────────────────────────
    blender_log = (proc.stdout or "") + (proc.stderr or "")
    log_path    = scripts_dir / f"gen_{timestamp}.log"
    log_path.write_text(blender_log, encoding="utf-8")

    # ── 9. Check output ───────────────────────────────────────────────
    if output_path.exists():
        size = output_path.stat().st_size
        _update_script_status(perm_script_path, "success")

        # ── Optional asset registration ───────────────────────────────
        asset_id = ""
        if asset_name and asset_type:
            try:
                from toolbox.blender.asset_manager import register_asset
                asset_id = register_asset(
                    name=asset_name,
                    asset_type=asset_type,
                    blend_path=str(output_path),
                    script_path=str(perm_script_path),
                    metadata={"story_context": story_context, "description": description},
                )
            except Exception as e:
                print(f"[blender_tool] Asset registration failed: {e}")

        return (
            f"[SUCCESS] Blender generation complete. Output: {output_path} ({size} bytes). "
            f"Script: {perm_script_path}."
            + (f" Asset registered: {asset_id}." if asset_id else "")
            + f" Log: {log_path}"
        )

    _update_script_status(perm_script_path, f"failed (no output, rc={proc.returncode})")
    error_tail = blender_log[-800:] if len(blender_log) > 800 else blender_log
    return (
        f"[ERROR] blender_tool: Blender ran but produced no output at {output_path}. "
        f"Return code: {proc.returncode}. Log tail:\n{error_tail}"
    )


def _write_permanent_script(
    script: str, perm_path: Path, output_filename: str
) -> None:
    """Write the original bpy script (without the injected export snippet) to permanent storage."""
    try:
        perm_path.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"# Generated by Hayeong\n"
            f"# Timestamp: {datetime.now().isoformat()}\n"
            f"# Output: {output_filename}\n"
            f"# Status: unknown\n"
            f"#\n"
            f"# --- SCRIPT ---\n\n"
        )
        perm_path.write_text(header + script.strip(), encoding="utf-8")
    except Exception as e:
        print(f"[blender_tool] Failed to save permanent script: {e}")


def _update_script_status(perm_path: Path, status: str) -> None:
    """Patch the # Status: line in the permanent script file."""
    try:
        if not perm_path.exists():
            return
        content = perm_path.read_text(encoding="utf-8")
        updated = content.replace("# Status: unknown", f"# Status: {status}", 1)
        perm_path.write_text(updated, encoding="utf-8")
    except Exception as e:
        print(f"[blender_tool] Failed to update script status: {e}")


def _build_export_snippet(output_path: str, export_format: str) -> str:
    path_str = output_path.replace("\\", "/")

    snippets = {
        "glb": f"""import bpy\nbpy.ops.export_scene.gltf(filepath=r"{path_str}", export_format='GLB', use_selection=False, export_materials='EXPORT')\nprint("HAYEONG_EXPORT_OK: {path_str}")""",
        "blend": f"""import bpy\nbpy.ops.wm.save_as_mainfile(filepath=r"{path_str}")\nprint("HAYEONG_EXPORT_OK: {path_str}")""",
        "stl": f"""import bpy\nbpy.ops.export_mesh.stl(filepath=r"{path_str}")\nprint("HAYEONG_EXPORT_OK: {path_str}")""",
        "fbx": f"""import bpy\nbpy.ops.export_scene.fbx(filepath=r"{path_str}")\nprint("HAYEONG_EXPORT_OK: {path_str}")""",
    }
    return snippets.get(export_format, snippets["glb"])
