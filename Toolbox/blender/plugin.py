"""
Toolbox/blender/plugin.py

Proactive context injection for the Blender tool.
Injects a compact blender usage block into every presence context tick
so Hayeong knows the correct params and script format BEFORE she
attempts a blender call — not after it fails.

PERSISTENT = True: loaded at startup so the context is available from
the very first session tick. Lazy loading would defeat the purpose —
the plugin must be in the context pool before the first script is written.
"""

PERSISTENT = True   # must be visible BEFORE first blender call, not triggered by it

_CONTEXT_BLOCK = """\
[BLENDER TOOL]
Params: blender_script (required), output_filename, export_format (glb/stl/fbx)
Rules: import bpy | clear scene first | NO export calls (auto-added) | end with print("HAYEONG_OK")
Example:
import bpy
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete()
bpy.ops.mesh.primitive_cube_add(size=2, location=(0,0,0))
bpy.context.active_object.name = "MyCube"
print("HAYEONG_OK: done")
[/BLENDER TOOL]"""


def tick():
    """Called every 2 seconds by the plugin loop. Blender has no background state to poll."""
    pass


def get_context_injection(state: dict = None) -> list:
    """
    Return the compact blender context block and current skills summary
    for injection into presence context.
    """
    lines = [_CONTEXT_BLOCK]
    try:
        from toolbox.blender.skills_tracker import get_skills_summary
        summary = get_skills_summary()
        if summary:
            lines.append(summary)
    except Exception:
        pass
    return lines
