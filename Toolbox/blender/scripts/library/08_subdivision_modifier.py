"""
08_subdivision_modifier.py — Skill library reference
Applies a Subdivision Surface modifier for smooth organic shapes.
levels=2 = preview quality. levels=3 = render quality (heavier).
NOTE: Do NOT add export calls — blender_tool injects them automatically.
"""
import bpy

# Clear default scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Start with a cube — subdivision turns it into a rounded box/sphere-like form
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
obj = bpy.context.active_object
obj.name = "SubdividedCube"

# Add Subdivision Surface modifier
subd = obj.modifiers.new(name="Subdivision", type='SUBSURF')
subd.levels        = 2   # viewport preview level
subd.render_levels = 3   # render level

# Smooth shading after subdivision
bpy.ops.object.shade_smooth()

print("HAYEONG_OK: subdivision modifier applied, smooth shading on")
