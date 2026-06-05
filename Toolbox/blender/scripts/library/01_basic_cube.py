"""
01_basic_cube.py — Skill library reference
Creates a single default cube at the origin with no material.
Use as the minimal starting point for any box-based object.
NOTE: Do NOT add export calls — blender_tool injects them automatically.
"""
import bpy

# Clear default scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Add cube (2x2x2 units, centered at origin)
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
cube = bpy.context.active_object
cube.name = "Cube"

print("HAYEONG_OK: basic cube created")
