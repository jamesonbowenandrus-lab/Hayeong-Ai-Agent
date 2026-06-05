"""
05_principled_material.py — Skill library reference
Creates and applies a Principled BSDF material to the active object.
Covers the most common material properties: color, roughness, metallic, emission.
NOTE: Do NOT add export calls — blender_tool injects them automatically.
"""
import bpy

# Clear default scene and add a test object
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
obj = bpy.context.active_object
obj.name = "MaterialDemo"

# Create material
mat = bpy.data.materials.new(name="DemoMaterial")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]

# Set properties (RGBA values 0.0–1.0)
bsdf.inputs["Base Color"].default_value = (0.2, 0.5, 0.8, 1.0)   # blue-ish
bsdf.inputs["Roughness"].default_value  = 0.4
bsdf.inputs["Metallic"].default_value   = 0.0

# Assign to object (slot 0 or append new slot)
if obj.data.materials:
    obj.data.materials[0] = mat
else:
    obj.data.materials.append(mat)

print("HAYEONG_OK: Principled BSDF material applied")
