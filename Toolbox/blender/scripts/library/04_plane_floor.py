"""
04_plane_floor.py — Skill library reference
Adds a large flat plane as a floor/ground surface.
Pair with 05_principled_material.py pattern to add a ground material.
NOTE: Do NOT add export calls — blender_tool injects them automatically.
"""
import bpy

# Clear default scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Floor plane: 20x20 units, at Z=0
bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
floor = bpy.context.active_object
floor.name = "Floor"

print("HAYEONG_OK: floor plane created")
