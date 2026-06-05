"""
03_uv_sphere.py — Skill library reference
Creates a UV sphere. Use for balls, heads, rounded shapes.
segments x rings: 32x16 = standard; 64x32 = high quality.
NOTE: Do NOT add export calls — blender_tool injects them automatically.
"""
import bpy

# Clear default scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Add UV sphere
bpy.ops.mesh.primitive_uv_sphere_add(
    segments=32,
    ring_count=16,
    radius=1.0,
    location=(0, 0, 0)
)
sphere = bpy.context.active_object
sphere.name = "Sphere"

# Smooth shading
bpy.ops.object.shade_smooth()

print("HAYEONG_OK: UV sphere created")
