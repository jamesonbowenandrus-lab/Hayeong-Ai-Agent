"""
10_simple_house.py — Skill library reference
A minimal house: box body + pyramid roof + door cutout suggestion.
Demonstrates combining primitives and basic transforms.
NOTE: Do NOT add export calls — blender_tool injects them automatically.
"""
import bpy
import math


def make_material(name, r, g, b, roughness=0.7):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
    bsdf.inputs["Roughness"].default_value  = roughness
    return mat


def assign_material(obj, mat):
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


# Clear default scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# ── Foundation / floor ────────────────────────────────────────────────
bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
ground = bpy.context.active_object
ground.name = "Ground"
assign_material(ground, make_material("Mat_Ground", 0.55, 0.45, 0.3, roughness=0.95))

# ── House body (4x4x3 box) ────────────────────────────────────────────
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 1.5))
body = bpy.context.active_object
body.name = "House_Body"
body.scale = (4, 4, 3)   # 8 wide × 8 deep × 6 tall (before apply)
bpy.ops.object.transform_apply(scale=True)
assign_material(body, make_material("Mat_Walls", 0.92, 0.88, 0.78, roughness=0.8))

# ── Roof (cone acts as pyramid; 4 vertices = true pyramid) ────────────
bpy.ops.mesh.primitive_cone_add(
    vertices=4,
    radius1=4.5,    # slightly wider than walls to overhang
    radius2=0.0,
    depth=2.5,
    location=(0, 0, 5.25)   # sits on top of 6-tall body (z=0..6), centred at 5.25
)
roof = bpy.context.active_object
roof.name = "House_Roof"
roof.rotation_euler[2] = math.radians(45)   # align corners over walls
bpy.ops.object.transform_apply(rotation=True)
assign_material(roof, make_material("Mat_Roof", 0.5, 0.2, 0.15, roughness=0.6))

# ── Door (dark rectangle, front face) ────────────────────────────────
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -4.05, 1.0))
door = bpy.context.active_object
door.name = "House_Door"
door.scale = (0.8, 0.05, 1.0)
bpy.ops.object.transform_apply(scale=True)
assign_material(door, make_material("Mat_Door", 0.25, 0.15, 0.08, roughness=0.9))

print("HAYEONG_OK: simple house scene created (ground + body + roof + door)")
