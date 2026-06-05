"""
07_camera_look_at.py — Skill library reference
Positions a camera at a given point aimed at the origin.
Use this pattern whenever Hayeong needs to set up a render camera.
NOTE: Do NOT add export calls — blender_tool injects them automatically.
"""
import bpy
import math

# Clear default scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Add a subject to frame
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
bpy.context.active_object.name = "Subject"

# Add camera
bpy.ops.object.camera_add(location=(7, -7, 5))
cam = bpy.context.active_object
cam.name = "Camera_Main"

# Point camera at origin using a Track To constraint
track = cam.constraints.new(type='TRACK_TO')
track.target = bpy.data.objects["Subject"]
track.track_axis  = 'TRACK_NEGATIVE_Z'
track.up_axis     = 'UP_Y'

# Make it the active scene camera
bpy.context.scene.camera = cam

print("HAYEONG_OK: camera positioned and aimed at subject")
