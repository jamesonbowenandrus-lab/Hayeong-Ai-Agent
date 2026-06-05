"""
02_cylinder.py — Skill library reference
Creates a cylinder. Good for pillars, cups, legs, poles.
Adjust vertices for smoothness: 8=faceted, 32=smooth-looking, 64=high quality.
NOTE: Do NOT add export calls — blender_tool injects them automatically.
"""
import bpy

# Clear default scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Add cylinder: 32 vertices = smooth at normal render distances
bpy.ops.mesh.primitive_cylinder_add(
    vertices=32,
    radius=1.0,
    depth=2.0,
    location=(0, 0, 0)
)
cyl = bpy.context.active_object
cyl.name = "Cylinder"

print("HAYEONG_OK: cylinder created")
