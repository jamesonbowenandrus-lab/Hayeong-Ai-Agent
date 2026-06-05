"""
06_three_point_light.py — Skill library reference
Standard 3-point lighting rig: key, fill, rim.
Add this pattern to any scene that needs clean rendering.
NOTE: Do NOT add export calls — blender_tool injects them automatically.
"""
import bpy

# Clear default scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# ── Key light (main source, front-left, warm) ──────────────────────────
bpy.ops.object.light_add(type='AREA', location=(4, -3, 6))
key = bpy.context.active_object
key.name = "Light_Key"
key.data.energy = 800
key.data.color  = (1.0, 0.95, 0.85)   # warm white
key.data.size   = 2.0

# ── Fill light (softer, front-right, cooler) ───────────────────────────
bpy.ops.object.light_add(type='AREA', location=(-4, -2, 4))
fill = bpy.context.active_object
fill.name = "Light_Fill"
fill.data.energy = 200
fill.data.color  = (0.85, 0.9, 1.0)   # cool blue-white
fill.data.size   = 3.0

# ── Rim light (back, highlights silhouette) ────────────────────────────
bpy.ops.object.light_add(type='SPOT', location=(0, 5, 5))
rim = bpy.context.active_object
rim.name = "Light_Rim"
rim.data.energy     = 400
rim.data.spot_size  = 0.8
rim.data.spot_blend = 0.15

# Add a test subject so the scene isn't empty
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
bpy.context.active_object.name = "Subject"

print("HAYEONG_OK: 3-point light rig created")
