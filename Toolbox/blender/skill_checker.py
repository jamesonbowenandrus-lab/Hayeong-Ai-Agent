"""
toolbox/blender/skill_checker.py

Pre-flight static validator for bpy scripts before Blender is invoked.
Catches the most common mistakes that would cause silent failures or wrong output.

Usage:
    from toolbox.blender.skill_checker import check_script
    warnings = check_script(script_str)
    if warnings:
        return f"[ERROR] blender_tool: script failed pre-flight check: {'; '.join(warnings)}"
"""

import ast
import re


def check_script(script: str) -> list[str]:
    """
    Statically validate a bpy script string.
    Returns a list of warning/error strings. Empty list = clean.
    Does NOT run the script.
    """
    issues = []
    issues.extend(_check_syntax(script))
    issues.extend(_check_dangerous_calls(script))
    issues.extend(_check_export_calls(script))
    issues.extend(_check_scene_clear(script))
    return issues


# ── Syntax ─────────────────────────────────────────────────────────────────

def _check_syntax(script: str) -> list[str]:
    try:
        ast.parse(script)
    except SyntaxError as e:
        return [f"SyntaxError at line {e.lineno}: {e.msg}"]
    return []


# ── Dangerous calls ────────────────────────────────────────────────────────

_DANGEROUS_PATTERNS = [
    (r"\bos\.system\s*\(", "os.system() is not allowed in blender scripts"),
    (r"\bsubprocess\b",     "subprocess is not allowed in blender scripts"),
    (r"\beval\s*\(",        "eval() is not allowed in blender scripts"),
    (r"\bexec\s*\(",        "exec() is not allowed in blender scripts"),
    (r"\bopen\s*\(",        "open() is not allowed — blender_tool manages file I/O"),
    (r"\b__import__\s*\(",  "__import__() is not allowed in blender scripts"),
]


def _check_dangerous_calls(script: str) -> list[str]:
    issues = []
    for pattern, message in _DANGEROUS_PATTERNS:
        if re.search(pattern, script):
            issues.append(message)
    return issues


# ── Export calls ───────────────────────────────────────────────────────────

_EXPORT_PATTERNS = [
    r"bpy\.ops\.export_scene\.",
    r"bpy\.ops\.export_mesh\.",
    r"bpy\.ops\.wm\.save_as_mainfile",
]


def _check_export_calls(script: str) -> list[str]:
    for pattern in _EXPORT_PATTERNS:
        if re.search(pattern, script):
            return [
                "Script contains an export call. blender_tool injects the export "
                "automatically — remove any export_scene.*, export_mesh.*, or "
                "wm.save_as_mainfile() calls from the script."
            ]
    return []


# ── Scene clear ────────────────────────────────────────────────────────────

def _check_scene_clear(script: str) -> list[str]:
    has_select_all = bool(re.search(r"select_all\s*\(", script))
    has_delete     = bool(re.search(r"\.delete\s*\(", script))
    has_remove     = bool(re.search(r"bpy\.data\.objects\.remove\s*\(", script))

    if not (has_select_all or has_remove):
        return [
            "Script does not appear to clear the default scene. "
            "Add: bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete() "
            "at the start, or the default cube/camera/light will pollute the scene."
        ]
    return []
